"""Regression coverage for counsel cache invalidation.

These tests intentionally exercise the API cache decision, not an extracted
signature helper, so a future prompt change cannot silently reuse old counsel.
"""
import asyncio
from types import SimpleNamespace

from backend import main


def _tracker():
    return SimpleNamespace(
        name="TestCharacter",
        server="testserver",
        class_str="WAR/CLR/ENC",
        level=40,
        playstyle="balanced",
        zone="The Commonlands",
        aa_available=3,
        spell_slots=10,
        _last_aa_seen="2026-08-13T12:00:00",
        race="Human",
        pet_slots=0,
        pet_inventory={},
    )


def _advisor_sig(tracker, revision):
    return main._sig_norm((
        tracker.class_str,
        tracker.level,
        tracker.playstyle,
        tracker.zone,
        tracker.aa_available,
        tracker.spell_slots,
        None,
        tracker._last_aa_seen,
        None,
        None,
        revision,
    ))


def _gear_sig(tracker, revision):
    return main._sig_norm((
        tracker.class_str,
        tracker.level,
        tracker.race,
        tracker.pet_slots,
        tuple(sorted(tracker.pet_inventory.items())),
        None,
        revision,
    ))


def _stub_exports(monkeypatch, tracker):
    monkeypatch.setattr(main, "tracker", tracker)
    monkeypatch.setattr(main, "load_spellbook", lambda *_args: None)
    monkeypatch.setattr(main, "load_export", lambda *_args: None)


def test_source_revision_is_stable_until_advisor_source_changes(
        monkeypatch, tmp_path):
    from backend.agent import advisor

    source = tmp_path / "advisor.py"
    source.write_text("PROMPT = 'first'\n", encoding="utf-8")
    monkeypatch.setattr(main, "is_frozen", lambda: False)
    monkeypatch.setattr(advisor, "__file__", str(source))

    first = main._advisor_code_revision()
    assert main._advisor_code_revision() == first

    source.write_text("PROMPT = 'corrected'\n", encoding="utf-8")
    assert main._advisor_code_revision() != first


def test_frozen_build_uses_release_version_for_revision(monkeypatch):
    monkeypatch.setattr(main, "is_frozen", lambda: True)
    monkeypatch.setattr(main, "APP_VERSION", "9.8.7")

    assert main._advisor_code_revision() == "9.8.7"


def test_advisor_cache_is_fresh_only_for_current_revision(monkeypatch):
    tracker = _tracker()
    _stub_exports(monkeypatch, tracker)
    monkeypatch.setattr(main, "_advice_cache", {"cached": True})
    monkeypatch.setattr(main, "_ADVISOR_CODE_REV", "prompt-a")
    monkeypatch.setattr(main, "_advice_sig", _advisor_sig(tracker, "prompt-a"))

    fresh = asyncio.run(main.get_advisor(cached=True))
    assert fresh == {"cached": True, "stale": False}

    monkeypatch.setattr(main, "_ADVISOR_CODE_REV", "prompt-b")
    stale = asyncio.run(main.get_advisor(cached=True))
    assert stale == {"cached": True, "stale": True}


def test_gear_cache_is_fresh_only_for_current_revision(monkeypatch):
    tracker = _tracker()
    _stub_exports(monkeypatch, tracker)
    monkeypatch.setattr(main, "_gear_cache", {"cached": True})
    monkeypatch.setattr(main, "_ADVISOR_CODE_REV", "prompt-a")
    monkeypatch.setattr(main, "_gear_sig", _gear_sig(tracker, "prompt-a"))

    fresh = asyncio.run(main.get_gear(cached=True))
    assert fresh == {"cached": True, "stale": False}

    monkeypatch.setattr(main, "_ADVISOR_CODE_REV", "prompt-b")
    stale = asyncio.run(main.get_gear(cached=True))
    assert stale == {"cached": True, "stale": True}
