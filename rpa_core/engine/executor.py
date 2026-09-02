from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from playwright.sync_api import Page, TimeoutError as PlaywrightTimeoutError, sync_playwright

from rpa_core.engine.models import Target, WorkflowDefinition
from rpa_core.variables import normalize_url, render_template


LogFn = Callable[[str, str, dict[str, Any] | None], None]
SecretResolver = Callable[[str], str | None]


class WorkflowExecutor:
    def __init__(self, artifacts_dir: Path, headless: bool = False, secret_resolver: SecretResolver | None = None) -> None:
        self.artifacts_dir = artifacts_dir
        self.headless = headless
        self.secret_resolver = secret_resolver

    def run(
        self,
        workflow_data: dict[str, Any],
        inputs: dict[str, Any] | None = None,
        log: LogFn | None = None,
    ) -> list[Path]:
        workflow = WorkflowDefinition.model_validate(workflow_data)
        context = {**workflow.inputs, **(inputs or {})}
        artifacts: list[Path] = []
        self.artifacts_dir.mkdir(parents=True, exist_ok=True)

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=self.headless)
            page = browser.new_page(accept_downloads=True)
            try:
                for index, step in enumerate(workflow.steps, start=1):
                    attempts = step.retry + 1
                    for attempt in range(1, attempts + 1):
                        try:
                            self._log(log, "INFO", f"Executando etapa {index}: {step.type}", {"step": index, "attempt": attempt})
                            created = self._execute_step(page, step, context, index)
                            artifacts.extend(created)
                            break
                        except Exception as exc:
                            if attempt >= attempts:
                                raise
                            self._log(log, "WARN", f"Retry da etapa {index}: {exc}", {"step": index, "attempt": attempt})
            except PlaywrightTimeoutError as exc:
                screenshot = self.artifacts_dir / "failure.png"
                page.screenshot(path=screenshot, full_page=True)
                artifacts.append(screenshot)
                raise RuntimeError(f"Timeout executando workflow: {exc}") from exc
            finally:
                browser.close()

        return artifacts

    def _execute_step(self, page: Page, step, context: dict[str, Any], index: int) -> list[Path]:
        artifacts: list[Path] = []

        if step.type == "goto":
            if not step.url:
                raise ValueError("Etapa goto requer url.")
            page.goto(normalize_url(render_template(step.url, context)), timeout=step.timeout_ms)

        elif step.type == "click":
            self._locator(page, step.target).click(timeout=step.timeout_ms)

        elif step.type == "fill":
            value = render_template(step.value, context) or ""
            self._locator(page, step.target).fill(value, timeout=step.timeout_ms)

        elif step.type == "secret_fill":
            if not step.secret:
                raise ValueError("Etapa secret_fill requer secret.")
            if self.secret_resolver is None:
                raise ValueError("Executor nao recebeu resolvedor de segredos.")
            value = self.secret_resolver(step.secret)
            if value is None:
                raise ValueError(f"Segredo nao encontrado: {step.secret}")
            self._locator(page, step.target).fill(value, timeout=step.timeout_ms)

        elif step.type == "select":
            value = render_template(step.value, context) or ""
            self._locator(page, step.target).select_option(value, timeout=step.timeout_ms)

        elif step.type == "press":
            if not step.key:
                raise ValueError("Etapa press requer key.")
            self._locator(page, step.target).press(step.key, timeout=step.timeout_ms)

        elif step.type == "wait_for":
            self._locator(page, step.target).wait_for(timeout=step.timeout_ms)

        elif step.type == "assert_text":
            text = render_template(step.value, context) or ""
            self._locator(page, step.target).filter(has_text=text).wait_for(timeout=step.timeout_ms)

        elif step.type == "download":
            filename = render_template(step.filename, context) or "download"
            with page.expect_download(timeout=step.timeout_ms) as download_info:
                self._locator(page, step.target).click(timeout=step.timeout_ms)
            download = download_info.value
            path = self.artifacts_dir / filename
            download.save_as(path)
            artifacts.append(path)

        elif step.type == "screenshot":
            name = render_template(step.name, context) or f"step-{index}"
            path = self.artifacts_dir / f"{name}.png"
            page.screenshot(path=path, full_page=True)
            artifacts.append(path)

        elif step.type == "delay":
            time.sleep(step.timeout_ms / 1000)

        return artifacts

    def _locator(self, page: Page, target: Target | None):
        if target is None:
            raise ValueError("Etapa requer target.")
        if target.role and target.name:
            return page.get_by_role(target.role, name=target.name)
        if target.label:
            return page.get_by_label(target.label)
        if target.text:
            return page.get_by_text(target.text)
        if target.css:
            return page.locator(target.css)
        raise ValueError("Target precisa ter role+name, label, text ou css.")

    def _log(self, log: LogFn | None, level: str, message: str, data: dict[str, Any] | None = None) -> None:
        if log:
            log(level, message, data)
