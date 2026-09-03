"""Timers learn their length from this character's own cast-to-fade cycles.

The vendored table under-promises by design; three agreeing cycles seen in
the log replace it. What must NOT happen: a fade with no cast behind it
teaching a length, a death teaching one, or a single reading being used.
"""
from datetime import datetime, timedelta

import pytest

from backend import learned_durations as ld
from backend.log_system.parser import parse_line
from backend.state_tracker import CharacterTracker

T0 = datetime(2026, 7, 10, 21, 0, 0)
# not in SPELL_TIMERS, so the only way it ever gets a timer is by measurement
SPELL = "Bulwark of Testing II"


@pytest.fixture(autouse=True)
def _scratch(tmp_path, monkeypatch):
    monkeypatch.setattr(ld, "FILE", tmp_path / "learned.json")
    ld._reset_for_tests()
    yield
    ld._reset_for_tests()


def feed(t: CharacterTracker, *lines):
    for offset, text in lines:
        stamp = (T0 + timedelta(seconds=offset)).strftime("[%a %b %d %H:%M:%S %Y]")
        e = parse_line(f"{stamp} {text}")
        assert e is not None, text
        t.apply(e, live=True)


def timer(t: CharacterTracker):
    return next((x for x in t.active_timers if x["name"] == SPELL), None)


def cycle(t, at, length):
    feed(t, (at, f"You begin casting {SPELL}."),
         (at + length, f"Your {SPELL} spell has worn off."))


def test_three_agreeing_cycles_give_a_measured_timer_where_the_table_has_none(monkeypatch):
    # timers_view() prunes against the wall clock; pin it inside the fight
    from backend import state_tracker as st

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return T0 + timedelta(seconds=3001)
    monkeypatch.setattr(st, "datetime", Clock)

    t = CharacterTracker("Kenkyo", "freeport")
    feed(t, (0, f"You begin casting {SPELL}."))
    assert timer(t) is None, "unknown to the table, unmeasured: no timer yet"

    cycle(t, 100, 600)
    cycle(t, 1000, 610)
    feed(t, (2000, f"You begin casting {SPELL}."))
    assert timer(t) is None, "two cycles is measuring, not knowing"

    feed(t, (2000 + 605, f"Your {SPELL} spell has worn off."))
    feed(t, (3000, f"You begin casting {SPELL}."))
    tm = timer(t)
    assert tm is not None and tm["source"] == "measured"
    assert tm["seconds"] == 605, "the median of the agreeing cycles, rounded down"
    assert t.timers_view()[0]["source"] == "measured", "the snapshot says where it came from"


def test_a_fade_with_no_cast_of_ours_teaches_nothing():
    """'Your X spell has worn off.' prints for a mob's debuff leaving us too."""
    t = CharacterTracker("Kenkyo", "freeport")
    feed(t, (10, "Your Tangling Weeds spell has worn off."),
            (20, "Your Tangling Weeds spell has worn off."),
            (30, "Your Tangling Weeds spell has worn off."))
    assert ld.progress(ld.char_key("Kenkyo", "freeport"), "Tangling Weeds") is None


def test_the_fades_that_follow_a_death_are_not_cycles():
    t = CharacterTracker("Kenkyo", "freeport")
    feed(t, (0, f"You begin casting {SPELL}."),
            (50, "You have been slain by a wan ghoul knight!"),
            (51, f"Your {SPELL} spell has worn off."))
    assert ld.progress(ld.char_key("Kenkyo", "freeport"), SPELL) is None


def test_a_refresh_measures_from_the_latest_cast():
    t = CharacterTracker("Kenkyo", "freeport")
    feed(t, (0, f"You begin casting {SPELL}."),
            (200, f"You begin casting {SPELL}."),     # refreshed
            (800, f"Your {SPELL} spell has worn off."))
    p = ld.progress(ld.char_key("Kenkyo", "freeport"), SPELL)
    assert p and p["n"] == 1
    # the stored sample is 600, not 800
    ld._reset_for_tests()
    import json
    raw = json.loads(ld.FILE.read_text())
    assert raw[ld.char_key("Kenkyo", "freeport")][SPELL.lower()]["samples"] == [600]


def test_a_measured_length_outranks_the_table():
    """Pick a spell the table knows, measure something longer, and the
    measurement wins -- the table cannot see this character's focus or AAs."""
    from backend.alert_data import SPELL_TIMERS
    known = next(iter(SPELL_TIMERS))
    name = known.title()
    table = SPELL_TIMERS[known]
    t = CharacterTracker("Kenkyo", "freeport")
    at = 0
    for _ in range(3):
        feed(t, (at, f"You begin casting {name}."),
                (at + table + 100, f"Your {name} spell has worn off."))
        at += table + 200
    feed(t, (at, f"You begin casting {name}."))
    tm = next(x for x in t.active_timers if x["name"] == name)
    assert tm["source"] == "measured" and tm["seconds"] == table + 100
