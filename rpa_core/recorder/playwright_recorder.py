from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from playwright.sync_api import Error as PlaywrightError, sync_playwright

from rpa_core.variables import normalize_url


RECORDER_SCRIPT = """
window.__rpaEvents = [];
window.__rpaDownloadExts = ['.xlsx', '.xls', '.csv', '.pdf', '.txt', '.zip', '.docx'];
function selectorFor(el) {
  if (el.id) return { css: '#' + CSS.escape(el.id) };
  if (el.getAttribute('aria-label')) return { css: '[aria-label="' + el.getAttribute('aria-label') + '"]' };
  if (el.name) return { css: '[name="' + el.name + '"]' };
  if (el.innerText && el.innerText.trim().length < 80) return { text: el.innerText.trim() };
  return { css: el.tagName.toLowerCase() };
}
function cleanName(text, fallback) {
  const value = (text || fallback || 'arquivo').trim().split('/').pop().split('?')[0];
  return value || 'arquivo';
}
document.addEventListener('click', (event) => {
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
      window.__rpaEvents.push(rpaEvent);
      if (window.rpaRecord) window.rpaRecord(rpaEvent);
      return;
    }
  }
  const rpaEvent = { type: 'click', target: selectorFor(event.target) };
  window.__rpaEvents.push(rpaEvent);
  if (window.rpaRecord) window.rpaRecord(rpaEvent);
}, true);
document.addEventListener('change', (event) => {
  const target = event.target;
  if (target && ['INPUT','TEXTAREA','SELECT'].includes(target.tagName)) {
    const isPassword = target.type && target.type.toLowerCase() === 'password';
    const isSelect = target.tagName === 'SELECT';
    const rpaEvent = isPassword
      ? { type: 'secret_fill', target: selectorFor(target), secret: 'defina_um_segredo', meta: { sensitive: true } }
      : isSelect
        ? { type: 'select', target: selectorFor(target), value: target.value }
        : { type: 'fill', target: selectorFor(target), value: '', meta: { recorded_input: true } };
    window.__rpaEvents.push(rpaEvent);
    if (window.rpaRecord) window.rpaRecord(rpaEvent);
  }
}, true);
"""


def parameterize_events(events: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, str]]:
    steps: list[dict[str, Any]] = []
    inputs: dict[str, str] = {}
    counter = 0
    for event in events:
        step = {key: value for key, value in event.items() if key != "meta"}
        meta = event.get("meta") or {}
        if meta.get("recorded_input"):
            counter += 1
            name = f"campo_{counter}"
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
