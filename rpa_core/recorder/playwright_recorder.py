from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
import re
from typing import Any

from playwright.sync_api import Error as PlaywrightError, sync_playwright

from rpa_core.variables import normalize_url


RECORDER_SCRIPT = """
window.__rpaEvents = [];
window.__rpaDownloadExts = ['.xlsx', '.xls', '.csv', '.pdf', '.txt', '.zip', '.docx'];
window.__rpaLastEvent = '';
function cleanText(text) {
  return (text || '').replace(/\\s+/g, ' ').trim();
}
function labelFor(el) {
  if (!el) return '';
  const aria = cleanText(el.getAttribute('aria-label'));
  if (aria) return aria;
  if (el.labels && el.labels.length) {
    const text = cleanText(Array.from(el.labels).map((label) => label.innerText).join(' '));
    if (text) return text;
  }
  if (el.id) {
    const label = document.querySelector('label[for="' + CSS.escape(el.id) + '"]');
    const text = label ? cleanText(label.innerText) : '';
    if (text) return text;
  }
  return '';
}
function selectorFor(el) {
  const label = labelFor(el);
  if (label) return { label };
  const role = el.getAttribute ? el.getAttribute('role') : '';
  const text = cleanText(el.innerText || el.value || el.getAttribute?.('title'));
  const tag = el.tagName ? el.tagName.toLowerCase() : '';
  if ((tag === 'button' || role === 'button') && text && text.length < 80) return { role: 'button', name: text };
  if (tag === 'a' && text && text.length < 80) return { text };
  if (el.id) return { css: '#' + CSS.escape(el.id) };
  if (el.getAttribute && el.getAttribute('placeholder')) return { css: '[placeholder="' + el.getAttribute('placeholder') + '"]' };
  if (el.name) return { css: '[name="' + el.name + '"]' };
  if (text && text.length < 80) return { text };
  return { css: el.tagName.toLowerCase() };
}
function targetLabel(el) {
  return labelFor(el) || cleanText(el.getAttribute?.('placeholder')) || cleanText(el.name) || cleanText(el.id) || 'campo';
}
function cleanName(text, fallback) {
  const value = (text || fallback || 'arquivo').trim().split('/').pop().split('?')[0];
  return value || 'arquivo';
}
function pushEvent(rpaEvent) {
  const key = JSON.stringify(rpaEvent);
  if (key === window.__rpaLastEvent) return;
  window.__rpaLastEvent = key;
  window.__rpaEvents.push(rpaEvent);
  if (window.rpaRecord) window.rpaRecord(rpaEvent);
}
document.addEventListener('click', (event) => {
  if (event.target && ['INPUT','TEXTAREA','SELECT','OPTION'].includes(event.target.tagName)) return;
  const link = event.target.closest ? event.target.closest('a') : null;
  if (link && link.href) {
    const href = link.href.toLowerCase();
    const isDownload = link.hasAttribute('download') || window.__rpaDownloadExts.some((ext) => href.includes(ext));
    if (isDownload) {
      const rpaEvent = {
        type: 'download',
        target: selectorFor(link),
        filename: cleanName(link.innerText, link.href)
      };
      pushEvent(rpaEvent);
      return;
    }
  }
  const rpaEvent = { type: 'click', target: selectorFor(event.target) };
  pushEvent(rpaEvent);
}, true);
document.addEventListener('change', (event) => {
  const target = event.target;
  if (target && ['INPUT','TEXTAREA','SELECT'].includes(target.tagName)) {
    const isPassword = target.type && target.type.toLowerCase() === 'password';
    const isSelect = target.tagName === 'SELECT';
    const rpaEvent = isPassword
      ? { type: 'secret_fill', target: selectorFor(target), secret: 'portal.password', meta: { sensitive: true, label: targetLabel(target) } }
      : isSelect
        ? { type: 'select', target: selectorFor(target), value: target.value, meta: { label: targetLabel(target) } }
        : { type: 'fill', target: selectorFor(target), value: '', meta: { recorded_input: true, label: targetLabel(target) } };
    pushEvent(rpaEvent);
  }
}, true);
"""


def _input_name(label: str, counter: int) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9_.-]+", "_", label.strip().lower()).strip("_")
    if not cleaned:
        cleaned = f"campo_{counter}"
    if cleaned[0].isdigit():
        cleaned = f"campo_{cleaned}"
    return cleaned[:50]


def parameterize_events(events: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, str]]:
    steps: list[dict[str, Any]] = []
    inputs: dict[str, str] = {}
    counter = 0
    previous_raw: dict[str, Any] | None = None
    for event in events:
        step = {key: value for key, value in event.items() if key != "meta"}
        if step == previous_raw:
            continue
        previous_raw = dict(step)
        meta = event.get("meta") or {}
        if meta.get("recorded_input"):
            counter += 1
            name = _input_name(str(meta.get("label") or ""), counter)
            while name in inputs:
                counter += 1
                name = f"{name}_{counter}"
            step["value"] = "{{" + name + "}}"
            inputs[name] = ""
        steps.append(step)
    return steps, inputs


@dataclass
class RecordingSession:
    id: str
    url: str
    stop_event: threading.Event = field(default_factory=threading.Event)
    events: list[dict[str, Any]] = field(default_factory=list)
    status: str = "starting"
    error: str | None = None
    thread: threading.Thread | None = None

    def workflow(self) -> dict[str, Any]:
        steps, inputs = parameterize_events(self.events)
        return {"inputs": inputs, "steps": [{"type": "goto", "url": self.url}, *steps]}


class RecorderManager:
    def __init__(self) -> None:
        self._sessions: dict[str, RecordingSession] = {}
        self._lock = threading.Lock()

    def start(self, url: str) -> RecordingSession:
        url = normalize_url(url) or url
        session = RecordingSession(id=str(uuid.uuid4()), url=url)
        thread = threading.Thread(target=self._run_session, args=(session,), daemon=True)
        session.thread = thread
        with self._lock:
            self._sessions[session.id] = session
        thread.start()
        return session

    def get(self, session_id: str) -> RecordingSession | None:
        with self._lock:
            return self._sessions.get(session_id)

    def stop(self, session_id: str, timeout: int = 20) -> RecordingSession | None:
        session = self.get(session_id)
        if session is None:
            return None
        session.stop_event.set()
        if session.thread and session.thread.is_alive():
            session.thread.join(timeout=timeout)
        with self._lock:
            self._sessions.pop(session_id, None)
        return session

    def _run_session(self, session: RecordingSession) -> None:
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=False)
                page = browser.new_page()
                page.expose_function("rpaRecord", lambda event: session.events.append(event))
                page.add_init_script(RECORDER_SCRIPT)
                page.goto(session.url)
                session.status = "recording"
                while not session.stop_event.is_set():
                    if page.is_closed():
                        break
                    time.sleep(0.5)
                session.status = "stopping"
                try:
                    browser.close()
                except PlaywrightError:
                    pass
                session.status = "finished"
        except Exception as exc:
            session.status = "failed"
            session.error = str(exc)


def record_browser_session(url: str, seconds: int = 60) -> dict[str, Any]:
    url = normalize_url(url) or url
    events: list[dict[str, Any]] = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=False)
        page = browser.new_page()
        page.expose_function("rpaRecord", lambda event: events.append(event))
        page.add_init_script(RECORDER_SCRIPT)
        page.goto(url)
        try:
            for _ in range(seconds):
                if page.is_closed():
                    break
                time.sleep(1)
        except PlaywrightError:
            pass
        try:
            browser.close()
        except PlaywrightError:
            pass
    steps, inputs = parameterize_events(events)
    return {"inputs": inputs, "steps": [{"type": "goto", "url": url}, *steps]}
