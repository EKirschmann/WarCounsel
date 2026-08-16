"""Per-encounter difficulty and survivability signals.

A death is the tail of a distribution we can measure all of. On one real
character 2.6% of fights ended in death while 5.3% cost over half of max HP
and 8.5% ran past 90 seconds -- so a death counter throws away every fight
that went badly and didn't quite kill you, which are exactly the ones more
mitigation would have changed.

Three signals are recorded per fight:
  * hp_floor   -- the deepest HP reached, walked from the log's own damage and
                  heal events (OCR only reads the stats panel, which is open
                  precisely when you are NOT being hit)
  * oom        -- "Insufficient Mana to cast this spell!", a loss condition
                  that otherwise leaves no trace at all (1,997 in one log)
  * mob_level  -- EQL's /con prints "(Lvl: N)" outright, which is objective
                  where con colour and verdict prose are not
"""
import pytest

from backend.log_system.parser import parse_line
from backend.state_tracker import CharacterTracker

S = "[Fri Aug 14 00:00:0%d 2026] "


def _tracker(max_hp=1000, level=37):
    t = CharacterTracker("Gentso", "rivervale")
    t.level = level
    t.max_hp = max_hp
    t.class_str = "Paladin/Monk/Necromancer"
    return t


def _play(t, lines):
    for i, l in enumerate(lines):
        e = parse_line((S % min(i, 9)) + l)
        if e is not None:
            t.apply(e, live=True)
    return t.encounter_snapshot()


def test_consider_records_level_and_rarity():
    e = parse_line(S % 0 + "Baron Telyx V`Zher - a rare creature - scowls at "
                           "you, ready to attack -- tombstone? (Lvl: 41)")
    assert e.type == "consider"
    assert e.name == "Baron Telyx V`Zher"
    assert e.level == 41 and e.rare is True


def test_consider_without_the_rare_tag():
    e = parse_line(S % 0 + "A froglok ton knight scowls at you, ready to "
                           "attack -- quite formidable. (Lvl: 41)")
    assert e.level == 41 and e.rare is False


def test_out_of_mana_parses():
    assert parse_line(S % 0 + "Insufficient Mana to cast this spell!").type == "oom"


def test_mob_level_and_delta_reach_the_encounter():
    snap = _play(_tracker(level=37), [
        "A froglok ton knight scowls at you, ready to attack -- x. (Lvl: 41)",
        "You slash a froglok ton knight for 10 points of damage.",
    ])
    assert snap["mob_level"] == 41
    assert snap["level_delta"] == 4, "difficulty is the GAP, not the raw level"


def test_a_trivial_mob_reports_a_negative_delta():
    """The caller needs to be able to discount a gimme -- so publish the
    number rather than a verdict."""
    snap = _play(_tracker(level=37), [
        "A decaying skeleton scowls at you, ready to attack -- x. (Lvl: 5)",
        "You slash a decaying skeleton for 10 points of damage.",
    ])
    assert snap["level_delta"] == -32


def test_hp_floor_tracks_the_deepest_point_not_the_end():
    """A fight that dipped and recovered must not look like an easy one."""
    snap = _play(_tracker(max_hp=1000), [
        "A froglok ton knight scowls at you, ready to attack -- x. (Lvl: 41)",
        "You slash a froglok ton knight for 10 points of damage.",
        "A froglok ton knight hits YOU for 400 points of damage.",
        "A froglok ton knight hits YOU for 500 points of damage.",
        "Xobekn healed you for 300 hit points by Light Healing.",
    ])
    assert snap["hp_floor"] == 100, "floor is the minimum, not the final value"
    assert snap["hp_floor_pct"] == 10.0


def test_heals_addressed_to_you_are_counted():
    """EQL writes the player as the literal word "you".

    Measured on a real log: all 161 heals landing on the player read
    "healed you" and NONE used the character name, so a bare name-equality
    test counted zero of 17,954 hp.
    """
    t = _tracker(max_hp=1000)
    _play(t, [
        "A froglok ton knight scowls at you, ready to attack -- x. (Lvl: 41)",
        "You slash a froglok ton knight for 10 points of damage.",
        "A froglok ton knight hits YOU for 500 points of damage.",
        "Xobekn healed you for 200 hit points by Light Healing.",
    ])
    assert t.healing_received == 200
    assert t._is_self("you") and t._is_self("YOU") and t._is_self("Gentso")
    assert not t._is_self("Xobekn") and not t._is_self("")


def test_out_of_mana_counts_against_the_fight():
    snap = _play(_tracker(), [
        "A froglok ton knight scowls at you, ready to attack -- x. (Lvl: 41)",
        "You slash a froglok ton knight for 10 points of damage.",
        "Insufficient Mana to cast this spell!",
        "Insufficient Mana to cast this spell!",
    ])
    assert snap["oom"] == 2


def test_unknown_max_hp_reports_no_floor_rather_than_a_guess():
    t = CharacterTracker("Gentso", "rivervale")
    t.level = 37
    t.max_hp = None
    snap = _play(t, [
        "A froglok ton knight scowls at you, ready to attack -- x. (Lvl: 41)",
        "You slash a froglok ton knight for 10 points of damage.",
        "A froglok ton knight hits YOU for 500 points of damage.",
    ])
    assert snap["hp_floor"] is None and snap["hp_floor_pct"] is None


def test_level_delta_is_none_when_the_mob_was_never_considered():
    snap = _play(_tracker(), [
        "You slash a froglok ton knight for 10 points of damage.",
    ])
    assert snap["mob_level"] is None and snap["level_delta"] is None
