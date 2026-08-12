"""Regression coverage for the Shaman/Necromancer live spell timers.

The expected base durations below are the EQL client spell data exposed by
the eqlbuilds snapshot: durationTicks x 6 seconds.  Keep the full DoT rosters
here because a missing timer is otherwise silent in the UI, and Scourge is
shared by both classes.
"""
from datetime import datetime, timedelta

import pytest

from backend.alert_data import BASE_DURATION_ROWS, SPELL_TIMERS
from backend.log_system.events import CastBegin
from backend.log_system.parser import parse_line
from backend.state_tracker import CharacterTracker


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


@pytest.mark.parametrize(
    "spell, expected_seconds",
    [("Regeneration", 1230), ("Scourge", 72)],
)
def test_requested_casts_start_live_timers(spell, expected_seconds):
    tracker = CharacterTracker("Tuldiyen", "halas")
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
