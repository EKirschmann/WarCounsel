"""Trio capabilities, and the two ways this could quietly lie.

The advisor reasons spell by spell and has no notion of a capability, so it
cannot know a PAL/ENC/MNK has no snare and no SoW — which rules out kiting —
or that slow lands at level 9. The vendored eqltools picker snapshot answers
both, but only if two rules hold:

1. Membership in byClass IS the capability; `level` is optional. `track`
   records no level for any of BRD/DRU/RNG, and the original design filtered
   on "level is None" — which would have told a Ranger they cannot track.
2. No snapshot is UNKNOWN, never "lacks everything". Same rule as the gear
   gates: a comparison that never ran is not a verdict.
"""
import json

import pytest

from backend import capabilities as cap


def test_the_snapshot_ships_and_parses():
    snap = cap.load()
    assert snap, "backend/picker_capabilities.json is missing"
    assert snap["capabilities"]
    assert "eqltools.com" in snap["attribution"]


def test_graded_opinion_is_not_vendored():
    """tier* are sealed 'chat' — letter grades from community discussion."""
    names = set(cap.load()["capabilities"])
    assert not (names & {"tierCC", "tierDps", "tierHeal"})


def test_ratings_are_not_vendored():
    """'You get plate at level None' is what this avoids."""
    names = set(cap.load()["capabilities"])
    assert not (names & {"manaPool", "plate", "tone", "weaponCaps",
                         "tankModel"})


def test_no_capability_survives_without_a_class_list():
    for name, row in cap.load()["capabilities"].items():
        assert row.get("byClass"), name


def test_class_names_and_abbreviations_both_resolve():
    assert cap.class_code("Shadow Knight") == "SHD"
    assert cap.class_code("SHD") == "SHD"
    assert cap.class_code("enchanter") == "ENC"
    assert cap.class_code("Bartender") is None


def test_a_tracking_class_is_never_told_it_cannot_track():
    """The trap: track carries no level for anyone who has it."""
    c = cap.trio_capabilities(["Ranger", "Druid", "Bard"])
    track = [h for h in c["has"] if h["name"] == "track"]
    assert track, "track must be present for a Ranger"
    assert track[0]["level"] is None          # and still no invented level
    assert "track" not in c["lacks"]


def test_a_non_tracking_trio_does_lack_track():
    c = cap.trio_capabilities(["Paladin", "Enchanter", "Monk"])
    assert "track" in c["lacks"]


def test_the_worked_example_from_the_design():
    """PAL/ENC/MNK, as the shelved design predicted it three weeks earlier."""
    c = cap.trio_capabilities(["Paladin", "Enchanter", "Monk"])
    lv = {h["name"]: h["level"] for h in c["has"]}
    assert lv["cc"] == 2 and lv["slow"] == 9 and lv["haste"] == 15
    assert lv["fd"] == 17 and lv["heals"] == 1 and lv["root"] == 6
    assert lv["gate"] == 4 and lv["invis"] == 4 and lv["rune"] == 40
    for missing in ("snare", "sow", "ports", "lifetap", "backstab", "iva",
                    "petHaste"):
        assert missing in c["lacks"], missing


def test_earliest_level_wins_and_names_the_class():
    c = cap.trio_capabilities(["Paladin", "Enchanter", "Monk"])
    fd = [h for h in c["has"] if h["name"] == "fd"][0]
    assert fd["classes"] == ["MNK"]           # only the Monk feigns


def test_no_snapshot_is_unknown_not_lacking(monkeypatch, tmp_path):
    monkeypatch.setattr(cap, "SNAPSHOT", tmp_path / "gone.json")
    monkeypatch.setitem(cap._cache, "mtime", None)
    assert cap.load() is None
    assert cap.trio_capabilities(["Ranger"]) is None
    assert cap.trio_capability_line(["Ranger"]) is None


def test_an_unreadable_snapshot_is_unknown_not_a_crash(monkeypatch, tmp_path):
    bad = tmp_path / "picker.json"
    bad.write_text("{ this is not json", encoding="utf-8")
    monkeypatch.setattr(cap, "SNAPSHOT", bad)
    monkeypatch.setitem(cap._cache, "mtime", None)
    assert cap.load() is None
    assert cap.trio_capabilities(["Ranger"]) is None


def test_unknown_classes_say_nothing_rather_than_everything():
    assert cap.trio_capabilities([]) is None
    assert cap.trio_capabilities(["Bartender"]) is None


def test_the_prompt_line_carries_attribution():
    line = cap.trio_capability_line(["Paladin", "Enchanter", "Monk"])
    assert line.startswith("HAS ")
    assert "LACKS " in line
    assert "eqltools.com" in line
    assert "None" not in line                 # no invented levels in prose
