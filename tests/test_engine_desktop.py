from __future__ import annotations

from pathlib import Path

from rpa_core.engine import WorkflowExecutor
from rpa_core.engine.validation import validate_workflow


def test_desktop_workflow_uses_controller(monkeypatch, tmp_path):
    calls = []

    class FakeDesktopController:
        def move(self, x: int, y: int, duration_ms: int = 0) -> None:
            calls.append(("move", x, y, duration_ms))

        def click(self, x: int | None = None, y: int | None = None, button: str = "left", clicks: int = 1) -> None:
            calls.append(("click", x, y, button, clicks))

        def drag(self, x: int, y: int, duration_ms: int = 300, button: str = "left") -> None:
            calls.append(("drag", x, y, duration_ms, button))

        def type_text(self, text: str, interval_ms: int = 0) -> None:
            calls.append(("type", text, interval_ms))

        def press(self, key: str) -> None:
            calls.append(("press", key))

        def hotkey(self, keys: list[str]) -> None:
            calls.append(("hotkey", keys))

        def screenshot(self, path: Path) -> None:
            calls.append(("screenshot", path.name))
            path.write_text("fake image", encoding="utf-8")

        def wait(self, timeout_ms: int) -> None:
            calls.append(("wait", timeout_ms))

    monkeypatch.setattr("rpa_core.engine.executor.DesktopController", FakeDesktopController)

    workflow = {
        "inputs": {"cliente": "HMB"},
        "steps": [
            {"type": "desktop_move", "x": 10, "y": 20, "duration_ms": 150},
            {"type": "desktop_click", "x": 10, "y": 20, "button": "left"},
            {"type": "desktop_double_click", "x": 12, "y": 22, "button": "right"},
            {"type": "desktop_drag", "x": 30, "y": 40, "duration_ms": 250},
            {"type": "desktop_type", "value": "Cliente {{cliente}}", "interval_ms": 5},
            {"type": "desktop_press", "key": "enter"},
            {"type": "desktop_hotkey", "keys": ["ctrl", "s"]},
            {"type": "desktop_screenshot", "name": "desktop-ok"},
            {"type": "desktop_wait", "timeout_ms": 1},
        ],
    }

    artifacts = WorkflowExecutor(tmp_path, headless=True).run(workflow)

    assert calls == [
        ("move", 10, 20, 150),
        ("click", 10, 20, "left", 1),
        ("click", 12, 22, "right", 2),
        ("drag", 30, 40, 250, "left"),
        ("type", "Cliente HMB", 5),
        ("press", "enter"),
        ("hotkey", ["ctrl", "s"]),
        ("screenshot", "desktop-ok.png"),
        ("wait", 1),
    ]
    assert artifacts == [tmp_path / "desktop-ok.png"]


def test_desktop_workflow_validation_requires_required_fields():
    workflow = {
        "inputs": {},
        "steps": [
            {"type": "desktop_move", "x": 10},
            {"type": "desktop_type"},
            {"type": "desktop_press"},
            {"type": "desktop_hotkey"},
            {"type": "desktop_screenshot"},
        ],
    }

    errors = validate_workflow(workflow)

    assert "Passo 1 (desktop_move): informe as coordenadas x e y." in errors
    assert "Passo 2 (desktop_type): informe o texto." in errors
    assert "Passo 3 (desktop_press): informe a tecla." in errors
    assert "Passo 4 (desktop_hotkey): informe as teclas do atalho." in errors
    assert "Passo 5 (desktop_screenshot): informe o nome da evidencia." in errors
