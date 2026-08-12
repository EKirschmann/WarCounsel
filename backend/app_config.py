"""Non-secret settings the UI can change, persisted across restarts.

A packaged build has no .env to edit, so anything a user must be able to set
lives here (data/app_config.json) and OVERRIDES the corresponding .env field
at startup. Secrets deliberately do not live here -- see secrets_store.

Applied in backend/config.py before the settings validator derives Logs/ and
maps/, so a game folder chosen in the UI behaves exactly like one set in
.env.
"""
import json
import logging
from typing import Any

from backend.paths import data_path

logger = logging.getLogger(__name__)

# Allow-list: only these may be overridden from the UI.
FIELDS = ("eql_game_dir", "eql_character_name", "llm_provider",
          "openai_model", "custom_model", "custom_base_url",
          "lmstudio_base_url", "model",
          "ollama_base_url", "ollama_model", "anthropic_model",
          "llm_context_limit", "allow_spellset_write")

_PATH = data_path("app_config.json")


def load() -> dict:
    try:
        data = json.loads(_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {k: v for k, v in data.items() if k in FIELDS and v not in (None, "")}


def update(values: dict) -> dict:
    """Merge in the given fields; "" removes an override (back to .env)."""
    data = load()
    for field in FIELDS:
        if field not in values:
            continue
        raw = values.get(field)
        new = "" if raw is None else str(raw).strip()
        if new:
            data[field] = new
        else:
            data.pop(field, None)
    _PATH.parent.mkdir(parents=True, exist_ok=True)
    _PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return data


def apply(target: Any) -> None:
    """Push the stored overrides onto a live settings object.

    Every override is stored as a STRING (see `update`), and neither caller
    validates on assignment -- so "false" lands on a bool field intact and
    reads as TRUE, which is exactly what happened to allow_spellset_write:
    the switch saved correctly, the file on disk was right, and the flag
    stayed on. The coercion lives HERE because the startup validator and the
    settings POST both need it and both had written the loop themselves.
    """
    for field, value in load().items():
        if not hasattr(target, field):
            continue
        if isinstance(getattr(target, field), bool):
            value = str(value).strip().lower() in ("1", "true", "yes", "on")
        setattr(target, field, value)


def get(field: str, fallback: Any = "") -> Any:
    return load().get(field, fallback)
