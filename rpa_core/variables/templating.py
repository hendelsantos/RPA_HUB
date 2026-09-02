from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Any


TOKEN_RE = re.compile(r"{{\s*([a-zA-Z0-9_.-]+)\s*}}")


def default_context() -> dict[str, str]:
    today = date.today()
    yesterday = today - timedelta(days=1)
    return {
        "today": today.isoformat(),
        "ontem": yesterday.isoformat(),
        "yesterday": yesterday.isoformat(),
        "run_date": today.strftime("%Y%m%d"),
    }


def render_template(value: str | None, context: dict[str, Any]) -> str | None:
    if value is None:
        return None

    merged = {**default_context(), **context}

    def replace(match: re.Match[str]) -> str:
        key = match.group(1)
        return str(merged.get(key, match.group(0)))

    return TOKEN_RE.sub(replace, value)


def normalize_url(value: str | None) -> str | None:
    if value is None:
        return None
    if value.startswith(("http://", "https://")):
        return value
    return f"https://{value}"
