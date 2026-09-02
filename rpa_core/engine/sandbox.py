from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


SAFE_ENV_KEYS = frozenset(
    {
        "PATH",
        "PATHEXT",
        "SYSTEMROOT",
        "COMSPEC",
        "WINDIR",
        "TEMP",
        "TMP",
        "TMPDIR",
        "HOME",
        "USERPROFILE",
        "APPDATA",
        "LOCALAPPDATA",
        "PROGRAMFILES",
        "PROGRAMDATA",
        "LANG",
        "LC_ALL",
        "SHELL",
        "TERM",
        "USERNAME",
        "XDG_CONFIG_HOME",
    }
)

DEFAULT_MAX_STEP_TIMEOUT_MS = 3_600_000


@dataclass(frozen=True)
class StepSandbox:
    allowed_roots: tuple[Path, ...] = field(default_factory=tuple)
    allowed_commands: frozenset[str] = frozenset()
    max_step_timeout_ms: int = DEFAULT_MAX_STEP_TIMEOUT_MS

    def check_path(self, path: Path) -> Path:
        if not self.allowed_roots:
            return path
        resolved = path.resolve()
        for root in self.allowed_roots:
            root_resolved = root.resolve()
            if resolved == root_resolved or root_resolved in resolved.parents:
                return path
        allowed = ", ".join(str(root) for root in self.allowed_roots)
        raise ValueError(f"Caminho fora das raizes permitidas: {path}. Raizes configuradas: {allowed}.")

    def check_command(self, command: str) -> None:
        if not self.allowed_commands:
            return
        if command in self.allowed_commands or Path(command).name in self.allowed_commands:
            return
        allowed = ", ".join(sorted(self.allowed_commands))
        raise ValueError(f"Comando nao permitido: {command}. Comandos permitidos: {allowed}.")

    def check_timeout(self, timeout_ms: int | None) -> None:
        if timeout_ms is None:
            return
        if timeout_ms <= 0:
            raise ValueError("timeout_ms deve ser positivo.")
        if timeout_ms > self.max_step_timeout_ms:
            raise ValueError(f"timeout_ms de {timeout_ms} ms excede o limite de {self.max_step_timeout_ms} ms.")

    def child_env(self, extra: dict[str, str]) -> dict[str, str]:
        env = {key: value for key, value in os.environ.items() if key.upper() in SAFE_ENV_KEYS}
        env.update(extra)
        return env
