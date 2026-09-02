from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Any
from urllib.parse import urlparse


TOKEN_RE = re.compile(r"{{\s*([a-zA-Z0-9_.-]+)\s*}}")
COMMON_DOMAIN_FIXES = {
    "goolge.com": "google.com",
    "www.goolge.com": "www.google.com",
    "gogle.com": "google.com",
    "www.gogle.com": "www.google.com",
    "googel.com": "google.com",
    "www.googel.com": "www.google.com",
    "gmial.com": "gmail.com",
    "www.gmial.com": "www.gmail.com",
    "gnail.com": "gmail.com",
    "www.gnail.com": "www.gmail.com",
}


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
    clean = value.strip()
    if clean.startswith(("http://", "https://")):
        return clean
    return f"https://{clean}"


def suggest_url_correction(value: str | None) -> str | None:
    normalized = normalize_url(value)
    if not normalized or "{{" in normalized:
        return None
    parsed = urlparse(normalized)
    host = (parsed.hostname or "").lower()
    fixed_host = COMMON_DOMAIN_FIXES.get(host)
    if not fixed_host:
        return None
    return normalized.replace(host, fixed_host, 1)
