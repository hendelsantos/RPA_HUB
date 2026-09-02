from __future__ import annotations

import time
from pathlib import Path


class DesktopController:
    def __init__(self) -> None:
        try:
            import pyautogui
        except ModuleNotFoundError as exc:
            raise RuntimeError("Automacao de desktop requer pyautogui instalado.") from exc

        self.pyautogui = pyautogui
        self.pyautogui.FAILSAFE = True
        self.pyautogui.PAUSE = 0.1

    def move(self, x: int, y: int, duration_ms: int = 0) -> None:
        self.pyautogui.moveTo(x, y, duration=duration_ms / 1000)

    def click(self, x: int | None = None, y: int | None = None, button: str = "left", clicks: int = 1) -> None:
        self.pyautogui.click(x=x, y=y, button=button, clicks=clicks)

    def drag(self, x: int, y: int, duration_ms: int = 300, button: str = "left") -> None:
        self.pyautogui.dragTo(x, y, duration=duration_ms / 1000, button=button)

    def type_text(self, text: str, interval_ms: int = 0) -> None:
        self.pyautogui.write(text, interval=interval_ms / 1000)

    def press(self, key: str) -> None:
        self.pyautogui.press(key)

    def hotkey(self, keys: list[str]) -> None:
        self.pyautogui.hotkey(*keys)

    def screenshot(self, path: Path) -> None:
        image = self.pyautogui.screenshot()
        image.save(path)

    def wait(self, timeout_ms: int) -> None:
        time.sleep(timeout_ms / 1000)
