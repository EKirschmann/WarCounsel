"""Regression coverage for client-derived live spell timers.

The expected caps and formulas below are the EQL client spell data exposed by
the eqlbuilds snapshot and installed spells_us.txt. Keep the full Shaman and
Necromancer DoT rosters because a missing timer is otherwise silent in the UI,
and exhaustively exercise every row whose actual duration depends on level.
"""
from datetime import datetime, timedelta

import pytest

from backend.alert_data import (BASE_DURATION_ROWS, LEVEL_DURATION_ROWS,
                                SPELL_TIMERS)
from backend.log_system.events import CastBegin
from backend.log_system.parser import parse_line
from backend.state_tracker import (CharacterTracker, _duration_formula_ticks,
                                   _level_scaled_duration)


NECROMANCER_DOT_BASE_SECONDS = {
    "asystole": 42,
    "auspice": 54,
    "boil blood": 42,
    "bond of death": 54,
    "cancelling of life": 60,
    "cascading darkness": 96,
    "cessation of life": 96,
    "chilling embrace": 36,
    "clinging darkness": 48,
    "dark soul": 30,
    "disease cloud": 360,
    "dooming darkness": 90,
    "engulfing darkness": 60,
    "envenomed bolt": 36,
    "eternities torment": 126,
    "heart flutter": 36,
    "heat blood": 36,
    "ignite blood": 42,
    "infectious cloud": 126,
    "leech": 54,
    "negation of life": 90,
    "poison bolt": 24,
    "scourge": 72,
    "vampiric curse": 54,
    "venom of the snake": 36,
}

SHAMAN_DOT_BASE_SECONDS = {
    "affliction": 84,
    "curse": 30,
    "envenomed bolt": 36,
    "envenomed breath": 42,
    "infectious cloud": 126,
    "odium": 30,
    "plague": 78,
    "scourge": 72,
    "sicken": 84,
    "tainted breath": 42,
    "venom of the snake": 36,
}


# Exact client metadata for every client-derived timer whose duration cap is
# not reached at every legal caster level through 50. Keeping this independent
# expectation catches both an omitted row and a mistyped formula/cap/learn level.
EXPECTED_LEVEL_DURATION_ROWS = {
    "clinging darkness": (1, 8, 4),
    "dooming darkness": (1, 15, 27),
    "eternities torment": (1, 21, 27),
    "heat blood": (1, 6, 10),
    "negation of life": (1, 15, 18),
    "stinging swarm": (1, 9, 10),
    "ensnaring roots": (2, 16, 21),
    "grasping roots": (2, 8, 2),
    "harmony": (2, 20, 5),
    "instill": (2, 16, 17),
    "root": (2, 8, 3),
    "snare": (2, 39, 1),
    "disease cloud": (3, 60, 1),
    "siphon strength": (3, 60, 1),
    "drowsy": (6, 35, 5),
    "shackle of bone": (6, 35, 17),
    "shackle of spirit": (6, 35, 38),
    "tagar's insects": (6, 35, 27),
    "togor's insects": (6, 35, 38),
    "walking sleep": (6, 35, 13),
    "cancelling of life": (7, 10, 8),
    "disempower": (7, 20, 12),
    "fear": (7, 3, 2),
    "incapacitate": (7, 65, 40),
    "listless power": (7, 65, 25),
    "numb the dead": (8, 20, 2),
    "shadow vortex": (8, 75, 19),
    "wave of enfeeblement": (8, 40, 9),
    "ensnare": (9, 140, 26),
    "fixation of ro": (9, 100, 42),
    "insidious fever": (9, 140, 17),
    "insidious malady": (9, 140, 38),
    "malaise": (9, 140, 18),
    "malaisement": (9, 140, 32),
    "malosi": (9, 140, 48),
    "scent of darkness": (9, 140, 37),
    "scent of dusk": (9, 140, 10),
    "scent of shadow": (9, 140, 21),
    "beguile undead": (10, 205, 31),
    "dominate undead": (10, 205, 18),
    "regeneration": (10, 205, 23),
}


REFERENCE_FORMULAS = {
    1: lambda level: level // 2 if level > 3 else 1,
    2: lambda level: level // 2 + 5 if level > 3 else 6,
    3: lambda level: 30 * level,
    4: lambda level: 50,
    5: lambda level: 2,
    6: lambda level: level // 2 + 2,
    7: lambda level: level,
    8: lambda level: level + 10,
    9: lambda level: 2 * level + 10,
    10: lambda level: 3 * level + 10,
    11: lambda level: 30 * (level + 3),
    12: lambda level: level // 4 if level > 7 else 1,
    13: lambda level: 4 * level + 10,
    14: lambda level: 5 * (level + 2),
    15: lambda level: 10 * (level + 10),
}


LEVEL_34_DYNAMIC_SECONDS = {
    "malaise": 468,
    "malaisement": 468,
    "ensnare": 468,
    "insidious fever": 468,
    "scent of dusk": 468,
    "scent of shadow": 468,
    "dominate undead": 672,
    "beguile undead": 672,
    "listless power": 204,
    "snare": 132,
    "drowsy": 114,
    "walking sleep": 114,
    "tagar's insects": 114,
    "shackle of bone": 114,
    "shadow vortex": 264,
    "eternities torment": 102,
}


@pytest.mark.parametrize(
    "class_name, expected",
    [
        ("Necromancer", NECROMANCER_DOT_BASE_SECONDS),
        ("Shaman", SHAMAN_DOT_BASE_SECONDS),
    ],
)
def test_every_shaman_and_necromancer_dot_has_the_client_duration(
        class_name, expected):
    actual = {name: SPELL_TIMERS.get(name) for name in expected}
    assert actual == expected, class_name


def test_regeneration_and_scourge_are_tier_scalable_game_data():
    assert SPELL_TIMERS["regeneration"] == 205 * 6
    assert SPELL_TIMERS["scourge"] == 12 * 6
    assert {"regeneration", "scourge"} <= BASE_DURATION_ROWS
    assert LEVEL_DURATION_ROWS["regeneration"] == (10, 205, 23)


def test_all_level_duration_metadata_matches_the_client_audit():
    assert LEVEL_DURATION_ROWS == EXPECTED_LEVEL_DURATION_ROWS
    assert LEVEL_DURATION_ROWS.keys() <= BASE_DURATION_ROWS
    for name, (_, cap_ticks, _) in LEVEL_DURATION_ROWS.items():
        assert SPELL_TIMERS[name] == cap_ticks * 6, name


@pytest.mark.parametrize(
    "formula, level, expected_ticks",
    [
        (1, 3, 1), (1, 34, 17),
        (2, 3, 6), (2, 34, 22),
        (3, 34, 1020),
        (4, 34, 50),
        (5, 34, 2),
        (6, 34, 19),
        (7, 34, 34),
        (8, 34, 44),
        (9, 34, 78),
        (10, 34, 112),
        (11, 34, 1110),
        (12, 7, 1), (12, 34, 8),
        (13, 34, 146),
        (14, 34, 180),
        (15, 34, 440),
    ],
)
def test_complete_client_duration_formula_resolver(
        formula, level, expected_ticks):
    assert _duration_formula_ticks(formula, level) == expected_ticks


def test_every_dynamic_row_at_every_legal_level_matches_client_semantics():
    for name, (formula, cap_ticks, minimum_level) in (
            EXPECTED_LEVEL_DURATION_ROWS.items()):
        for caster_level in range(minimum_level, 51):
            expected_ticks = min(
                REFERENCE_FORMULAS[formula](caster_level), cap_ticks)
            actual_seconds = _level_scaled_duration(
                name, SPELL_TIMERS[name], caster_level)
            assert actual_seconds == expected_ticks * 6, (
                name, caster_level, formula, cap_ticks)


@pytest.mark.parametrize("spell, expected_seconds",
                         LEVEL_34_DYNAMIC_SECONDS.items())
def test_level_34_dynamic_durations(spell, expected_seconds):
    assert _level_scaled_duration(
        spell, SPELL_TIMERS[spell], 34) == expected_seconds


def test_regeneration_formula_10_uses_level_and_caps():
    cap = SPELL_TIMERS["regeneration"]
    assert _level_scaled_duration("regeneration", cap, None) == 79 * 6
    assert _level_scaled_duration("regeneration", cap, 34) == 112 * 6
    assert _level_scaled_duration("regeneration", cap, 50) == 160 * 6
    assert _level_scaled_duration("regeneration", cap, 65) == 205 * 6
    assert _level_scaled_duration("regeneration", cap, 99) == 205 * 6


@pytest.mark.parametrize(
    "spell, expected_seconds",
    [("Regeneration", 672), ("Scourge", 72)],
)
def test_requested_casts_start_live_timers(spell, expected_seconds):
    tracker = CharacterTracker("Tuldiyen", "halas")
    tracker.level = 34
    ts = datetime(2026, 8, 11, 20, 0, 0)
    event = parse_line(
        f"[Tue Aug 11 20:00:00 2026] You begin casting {spell}.",
        character_name="Tuldiyen",
    )

    assert isinstance(event, CastBegin)
    tracker.apply(event, live=True)

    assert len(tracker.active_timers) == 1
    assert tracker.active_timers[0] == {
        "name": spell,
        "kind": "spell",
        "seconds": expected_seconds,
        "target": None,
        "ends": ts + timedelta(seconds=expected_seconds),
    }


def test_new_cast_uses_new_level_without_static_timer_updates():
    tracker = CharacterTracker("Tuldiyen", "halas")
    event = parse_line(
        "[Tue Aug 11 20:00:00 2026] You begin casting Malaise.",
        character_name="Tuldiyen",
    )

    tracker.level = 34
    tracker.apply(event, live=True)
    assert tracker.active_timers[-1]["seconds"] == 468

    tracker.active_timers.clear()
    tracker.level = 35
    event = parse_line(
        "[Tue Aug 11 20:00:01 2026] You begin casting Malaise.",
        character_name="Tuldiyen",
    )
    tracker.apply(event, live=True)
    assert tracker.active_timers[-1]["seconds"] == 480
