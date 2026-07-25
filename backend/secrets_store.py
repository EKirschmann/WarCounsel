"""API keys, kept apart from everything else on purpose.

Keys live in data/secrets.json and NOTHING else does. The separation is the
whole point: data/llm_config.json, data/app_config.json and the log file all
get pasted into bug reports, and a key that shares a file with ordinary
settings eventually gets shared with it. This file is the one place that is
never rendered, never logged, and never returned to the browser -- the API
reports whether a key is set, never what it is.

Values here take precedence over the matching .env fields, so a packaged
build (which has no .env to edit) can be configured entirely from the UI
while a source install can keep using .env.
"""
import json
import logging
import os
from typing import Optional

from backend.paths import data_path

logger = logging.getLogger(__name__)

# Only these may be stored. An allow-list rather than a filter: a typo in a
# caller must not silently create a new secret field.
FIELDS = ("openai_api_key", "anthropic_api_key", "custom_api_key")

_PATH = data_path("secrets.json")


def _load() -> dict:
    try:
        data = json.loads(_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def get(field: str) -> str:
    """Stored key, or "" when unset. Never logged."""
    if field not in FIELDS:
        return ""
    return str(_load().get(field) or "")


def resolve(field: str, fallback: str = "") -> str:
    """Stored key first, then the .env value passed as fallback."""
    return get(field) or fallback


def which_are_set() -> dict:
    """{field: bool} — safe to send to the UI."""
    stored = _load()
    return {f: bool(stored.get(f)) for f in FIELDS}


def update(values: dict) -> dict:
    """Merge in the given keys. "" CLEARS a key; a field that is absent is
    left alone, so the UI can save other settings without resending secrets
    it was never shown. Returns which_are_set()."""
    data = _load()
    touched = []
    for field in FIELDS:
        if field not in values:
            continue
        raw = values.get(field)
        new = "" if raw is None else str(raw).strip()
        if new:
            data[field] = new
        else:
            data.pop(field, None)
        touched.append(field)
    _PATH.parent.mkdir(parents=True, exist_ok=True)
    _PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")
    _restrict(_PATH)
    if touched:
        # names only, never values
        logger.info("Secrets updated: %s", ", ".join(sorted(touched)))
    return which_are_set()


def _restrict(path) -> None:
    """Best-effort owner-only permissions. Windows ACLs are not chmod, so
    this is a nicety rather than a guarantee -- the real protection is that
    the file holds nothing but keys and is never surfaced anywhere."""
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
