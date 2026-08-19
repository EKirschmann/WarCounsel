"""The starter catalogue is offered, never applied.

A bigger seed would have reached fresh installs only -- load_rules writes
_EXAMPLE just once, when the file does not exist -- and merging into an
existing file would resurrect rules somebody deleted on purpose. So the
catalogue lives beside the user's file and the panel copies one row at a
time, disabled.

The fade patterns are checked here against the shape they must have, and
were checked once against the client spell table (73,971 names) when
written: "Mesmerize" matches 3 names and misses all 60 "Mesmerization"
spells, "Levitate" misses "Levitation". The truncated stems are load-
bearing, so a well-meant "fix" to the full word is a regression.
"""
import json

import pytest

from backend import alerts

RULE_KEYS = {"kind", "pattern", "enabled", "sound"}


def test_every_starter_rule_is_a_kind_that_can_fire():
    for r in alerts.starter_set():
        assert r["kind"] in alerts.KINDS, r


def test_starter_rules_ship_disabled():
    """A catalogue row must never start firing just by being offered."""
    assert all(r["enabled"] is False for r in alerts.starter_set())


def test_starter_rules_survive_the_cleaner_unchanged():
    """What the panel adds must be what gets stored -- kind and pattern."""
    starter = alerts.starter_set()
    cleaned = alerts._clean(starter)
    assert len(cleaned) == len(starter)
    for before, after in zip(starter, cleaned):
        assert (after["kind"], after["pattern"]) == (before["kind"],
                                                     before["pattern"])
        assert set(after) == RULE_KEYS      # label/group/why never stored


def test_no_duplicate_rows_in_the_catalogue():
    keys = [(r["kind"], r["pattern"]) for r in alerts.starter_set()]
    assert len(keys) == len(set(keys))


def test_every_row_says_what_it_is_for():
    for r in alerts.starter_set():
        assert r["group"] and r["label"] and r["why"], r


def test_mez_and_levitate_patterns_are_stems_not_whole_words():
    """Guards the spell-table finding: the full words match too little."""
    fades = {r["pattern"] for r in alerts.starter_set() if r["kind"] == "fade"}
    assert "Mesmeriz" in fades and "Mesmerize" not in fades
    assert "Levitat" in fades and "Levitate" not in fades


def test_the_seed_is_drawn_from_the_catalogue():
    """One source of truth: a seeded rule must exist in the catalogue."""
    catalogue = {(r["kind"], r["pattern"]) for r in alerts.starter_set()}
    assert alerts._EXAMPLE
    for r in alerts._EXAMPLE:
        assert (r["kind"], r["pattern"]) in catalogue
        assert set(r) == RULE_KEYS
        assert r["enabled"] is False


def test_bighit_starter_pattern_is_a_usable_threshold(tmp_path, monkeypatch):
    """bighit's pattern is a NUMBER; a non-numeric one is silently ignored."""
    monkeypatch.setattr(alerts, "RULES_FILE", tmp_path / "rules.json")
    rows = [dict(r, enabled=True) for r in alerts.starter_set()
            if r["kind"] == "bighit"]
    alerts.save(rows)
    assert alerts.bighit_threshold() == 800


@pytest.fixture
def rules_file(tmp_path, monkeypatch):
    f = tmp_path / "tracked_rules.json"
    monkeypatch.setattr(alerts, "RULES_FILE", f)
    alerts._cache.update({"mtime": None, "rules": [], "all": []})
    return f


def test_a_fresh_install_is_seeded_and_nothing_is_enabled(rules_file):
    alerts.load_rules()
    stored = json.loads(rules_file.read_text(encoding="utf-8"))
    assert len(stored) == len(alerts._EXAMPLE)
    assert alerts.load_rules() == []          # matching sees none of them
    assert len(alerts.all_rules()) == len(alerts._EXAMPLE)


def test_seeding_never_overwrites_an_existing_file(rules_file):
    """The reason the catalogue exists: an existing file is left alone."""
    mine = [{"kind": "loot", "pattern": "Fungi Tunic", "enabled": True,
             "sound": True}]
    rules_file.write_text(json.dumps(mine), encoding="utf-8")
    alerts.load_rules()
    assert json.loads(rules_file.read_text(encoding="utf-8")) == mine
    assert alerts.all_rules() == mine
