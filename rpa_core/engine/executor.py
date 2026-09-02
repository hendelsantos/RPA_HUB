from __future__ import annotations

import os
import time
from collections.abc import Callable
from pathlib import Path
import shutil
import subprocess
from typing import Any
import zipfile

from playwright.sync_api import Page, TimeoutError as PlaywrightTimeoutError, sync_playwright

from rpa_core.engine.models import Target, WorkflowDefinition
from rpa_core.variables import normalize_url, render_template


LogFn = Callable[[str, str, dict[str, Any] | None], None]
SecretResolver = Callable[[str], str | None]
WEB_STEPS = {"goto", "click", "fill", "secret_fill", "select", "press", "wait_for", "assert_text", "download", "screenshot"}


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

        if any(step.type in WEB_STEPS for step in workflow.steps):
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=self.headless)
                page = browser.new_page(accept_downloads=True)
                try:
                    artifacts.extend(self._execute_steps(workflow.steps, context, log, page))
                except PlaywrightTimeoutError as exc:
                    screenshot = self.artifacts_dir / "failure.png"
                    page.screenshot(path=screenshot, full_page=True)
                    artifacts.append(screenshot)
                    raise RuntimeError(f"Timeout executando workflow: {exc}") from exc
                finally:
                    browser.close()
        else:
            artifacts.extend(self._execute_steps(workflow.steps, context, log, None))

        return artifacts

    def _execute_steps(self, steps, context: dict[str, Any], log: LogFn | None, page: Page | None) -> list[Path]:
        artifacts: list[Path] = []
        for index, step in enumerate(steps, start=1):
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
        return artifacts

    def _execute_step(self, page: Page | None, step, context: dict[str, Any], index: int) -> list[Path]:
        artifacts: list[Path] = []

        if step.type == "goto":
            page = self._require_page(page, step.type)
            if not step.url:
                raise ValueError("Etapa goto requer url.")
            page.goto(normalize_url(render_template(step.url, context)), timeout=step.timeout_ms)

        elif step.type == "click":
            page = self._require_page(page, step.type)
            self._locator(page, step.target).click(timeout=step.timeout_ms)

        elif step.type == "fill":
            page = self._require_page(page, step.type)
            value = render_template(step.value, context) or ""
            self._locator(page, step.target).fill(value, timeout=step.timeout_ms)

        elif step.type == "secret_fill":
            page = self._require_page(page, step.type)
            if not step.secret:
                raise ValueError("Etapa secret_fill requer secret.")
            if self.secret_resolver is None:
                raise ValueError("Executor nao recebeu resolvedor de segredos.")
            value = self.secret_resolver(step.secret)
            if value is None:
                raise ValueError(f"Segredo nao encontrado: {step.secret}")
            self._locator(page, step.target).fill(value, timeout=step.timeout_ms)

        elif step.type == "select":
            page = self._require_page(page, step.type)
            value = render_template(step.value, context) or ""
            self._locator(page, step.target).select_option(value, timeout=step.timeout_ms)

        elif step.type == "press":
            page = self._require_page(page, step.type)
            if not step.key:
                raise ValueError("Etapa press requer key.")
            self._locator(page, step.target).press(step.key, timeout=step.timeout_ms)

        elif step.type == "wait_for":
            page = self._require_page(page, step.type)
            self._locator(page, step.target).wait_for(timeout=step.timeout_ms)

        elif step.type == "assert_text":
            page = self._require_page(page, step.type)
            text = render_template(step.value, context) or ""
            self._locator(page, step.target).filter(has_text=text).wait_for(timeout=step.timeout_ms)

        elif step.type == "download":
            page = self._require_page(page, step.type)
            filename = render_template(step.filename, context) or "download"
            with page.expect_download(timeout=step.timeout_ms) as download_info:
                self._locator(page, step.target).click(timeout=step.timeout_ms)
            download = download_info.value
            path = self.artifacts_dir / filename
            download.save_as(path)
            artifacts.append(path)

        elif step.type == "screenshot":
            page = self._require_page(page, step.type)
            name = render_template(step.name, context) or f"step-{index}"
            path = self.artifacts_dir / f"{name}.png"
            page.screenshot(path=path, full_page=True)
            artifacts.append(path)

        elif step.type == "delay":
            time.sleep(step.timeout_ms / 1000)

        elif step.type == "file_create_folder":
            path = self._path(step.path, context, "Etapa file_create_folder requer path.")
            path.mkdir(parents=True, exist_ok=True)

        elif step.type == "file_copy":
            source = self._path(step.source, context, "Etapa file_copy requer source.")
            destination = self._path(step.destination, context, "Etapa file_copy requer destination.")
            self._ensure_can_write(destination, step.overwrite)
            destination.parent.mkdir(parents=True, exist_ok=True)
            if source.is_dir():
                shutil.copytree(source, destination, dirs_exist_ok=step.overwrite)
            else:
                shutil.copy2(source, destination)

        elif step.type == "file_move":
            source = self._path(step.source, context, "Etapa file_move requer source.")
            destination = self._path(step.destination, context, "Etapa file_move requer destination.")
            self._ensure_can_write(destination, step.overwrite)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(source), str(destination))

        elif step.type == "file_delete":
            path = self._path(step.path, context, "Etapa file_delete requer path.")
            if path.is_dir():
                shutil.rmtree(path)
            elif path.exists():
                path.unlink()

        elif step.type == "file_write_text":
            path = self._path(step.path, context, "Etapa file_write_text requer path.")
            self._ensure_can_write(path, step.overwrite)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(render_template(step.value, context) or "", encoding="utf-8")

        elif step.type == "file_read_text":
            path = self._path(step.path, context, "Etapa file_read_text requer path.")
            if not step.variable:
                raise ValueError("Etapa file_read_text requer variable.")
            context[step.variable] = path.read_text(encoding="utf-8")

        elif step.type == "file_zip":
            source = self._path(step.source, context, "Etapa file_zip requer source.")
            destination = self._path(step.destination, context, "Etapa file_zip requer destination.")
            self._ensure_can_write(destination, step.overwrite)
            destination.parent.mkdir(parents=True, exist_ok=True)
            self._zip(source, destination)
            artifacts.append(destination)

        elif step.type == "file_unzip":
            source = self._path(step.source, context, "Etapa file_unzip requer source.")
            destination = self._path(step.destination, context, "Etapa file_unzip requer destination.")
            destination.mkdir(parents=True, exist_ok=True)
            with zipfile.ZipFile(source) as archive:
                archive.extractall(destination)

        elif step.type == "command_run":
            if not step.command:
                raise ValueError("Etapa command_run requer command.")
            command = [render_template(step.command, context), *[render_template(arg, context) for arg in step.args]]
            cwd = self._path(step.cwd, context, "Etapa command_run recebeu cwd vazio.") if step.cwd else None
            env = {key: render_template(value, context) for key, value in step.env.items()}
            result = subprocess.run(
                command,
                cwd=cwd,
                env={**os.environ, **env} if env else None,
                capture_output=True,
                check=False,
                text=True,
                timeout=step.timeout_ms / 1000,
            )
            if step.output_name:
                output_path = self.artifacts_dir / f"{render_template(step.output_name, context)}.txt"
                output_path.write_text((result.stdout or "") + (result.stderr or ""), encoding="utf-8")
                artifacts.append(output_path)
            if result.returncode != 0:
                raise RuntimeError(f"Comando falhou com codigo {result.returncode}: {result.stderr or result.stdout}")

        return artifacts

    def _require_page(self, page: Page | None, step_type: str) -> Page:
        if page is None:
            raise ValueError(f"Etapa {step_type} requer navegador.")
        return page

    def _path(self, value: str | None, context: dict[str, Any], error: str) -> Path:
        if not value:
            raise ValueError(error)
        return Path(render_template(value, context)).expanduser()

    def _ensure_can_write(self, path: Path, overwrite: bool) -> None:
        if path.exists() and not overwrite:
            raise FileExistsError(f"Caminho ja existe: {path}. Marque overwrite=true para substituir.")

    def _zip(self, source: Path, destination: Path) -> None:
        with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            if source.is_dir():
                for path in source.rglob("*"):
                    if path.is_file():
                        archive.write(path, path.relative_to(source))
            else:
                archive.write(source, source.name)

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
