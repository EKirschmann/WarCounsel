"""Every module holding a gate must move the counsel revision.

PR #8 hashed backend/agent/advisor.py, which left the same bug one file
over: `scale_item_line`, `weapon_indices`, `proc_rates`, `item_stat_vector`
and the location gate live in game_data.py, and the curated stacking lines
in spell_lines.py. A fix to any of those left cached counsel reporting
stale: false.
"""
import importlib
from pathlib import Path

import pytest

from backend import main


def _rev():
    """Uncached — _advisor_revision() memoises for the process lifetime."""
    return main._advisor_code_revision()


@pytest.mark.parametrize("module", list(main._COUNSEL_SOURCES))
def test_editing_any_gate_module_changes_the_revision(module, monkeypatch):
    monkeypatch.setattr(main, "is_frozen", lambda: False)
    path = Path(importlib.import_module(module).__file__)
    before = _rev()
    original = path.read_bytes()
    try:
        path.write_bytes(original + b"\n# gate tweak\n")
        assert _rev() != before, f"editing {module} did not change the revision"
    finally:
        path.write_bytes(original)
    assert _rev() == before, "restoring the file did not restore the revision"


def test_frozen_builds_use_the_release_version(monkeypatch):
    monkeypatch.setattr(main, "is_frozen", lambda: True)
    assert _rev() == main.APP_VERSION


def test_unreadable_sources_fall_back_rather_than_hashing_nothing(monkeypatch):
    """A hash of no files is a constant, which would silently restore the bug."""
    monkeypatch.setattr(main, "is_frozen", lambda: False)
    monkeypatch.setattr(main, "_COUNSEL_SOURCES", ("backend.does_not_exist",))
    assert _rev() == main.APP_VERSION
