"""Per-hit retention on encounters -- the rows the fight timeline draws.

Counters cannot say WHEN a skill landed or which swings missed; these rows
can. They are in-memory only, capped, and reachable by the fight's start
stamp. Each test feeds real log lines through the parser so the shape on
the wire is the shape the parser actually produces.
"""
from datetime import datetime, timedelta

from backend.log_system.parser import parse_line
from backend.state_tracker import HIT_CAP, CharacterTracker

T0 = datetime(2026, 7, 10, 21, 25, 0)


def stamp(offset: int) -> str:
    return (T0 + timedelta(seconds=offset)).strftime("[%a %b %d %H:%M:%S %Y]")


def feed(tracker: CharacterTracker, *lines: tuple):
    for offset, text in lines:
        e = parse_line(f"{stamp(offset)} {text}")
        assert e is not None, f"parser dropped: {text!r}"
        tracker.apply(e, live=True)


def test_every_kind_of_row_lands_with_its_offset_and_tag():
    t = CharacterTracker("Kenkyo", "freeport")
    feed(t,
         (0, "You slash a wan ghoul knight for 69 points of damage."),
         (1, "You kick a wan ghoul knight for 80 points of damage. (Critical)"),
         (1, "You try to bash a wan ghoul knight, but miss!"),
         (2, "A wan ghoul knight hits YOU for 10 points of damage."),
         (2, "A wan ghoul knight tries to kick YOU, but YOU parry!"),
         (3, "You hit a wan ghoul knight for 40 points of non-melee damage by Smite."),
         (4, "A wan ghoul knight resisted your Fear!"),
         (5, "You healed yourself for 30 (30) hit points by Minor Healing."))
    hits = t.encounter["hits"]
    rows = {(h[1], h[2], h[5]): h for h in hits}

    assert rows[("melee", "Slash", "")][0] == 0
    assert rows[("melee", "Kick", "Critical")][3] == 80
    miss = rows[("melee", "Bash", "miss")]
    assert miss[3] == 0 and miss[4] == "a wan ghoul knight"
    taken = [h for h in hits if h[1] == "in" and h[3] == 10]
    assert len(taken) == 1 and taken[0][4] == "A wan ghoul knight"
    assert rows[("in", "kick", "parry")][0] == 2, "the defense verb is the tag"
    assert ("spell", "Smite", "") in rows
    assert rows[("spell", "Fear", "resist")][3] == 0
    heal = next(h for h in hits if h[1] == "heal")
    assert heal[3] == 30 and heal[0] == 5


def test_a_miss_never_opens_or_extends_a_fight():
    """A miss is not evidence anything is being fought -- it must not start
    an encounter on its own, and must not push `last` forward on one that
    is winding down."""
    t = CharacterTracker("Kenkyo", "freeport")
    feed(t, (0, "You try to bash a wan ghoul knight, but miss!"))
    assert t.encounter is None

    feed(t, (10, "You slash a wan ghoul knight for 69 points of damage."))
    last = t.encounter["last"]
    feed(t, (12, "You try to bash a wan ghoul knight, but miss!"))
    assert t.encounter["last"] == last
    assert any(h[5] == "miss" for h in t.encounter["hits"]), "...but it is on the timeline"


def test_a_stacked_tag_stays_whole():
    t = CharacterTracker("Kenkyo", "freeport")
    # EQL prints a stacked tag as ONE parenthetical, and the parser keeps it
    # whole; the row must too, or "Riposte Slay Undead" becomes two facts.
    feed(t, (0, "You slash a wan ghoul knight for 200 points of damage. (Riposte Slay Undead)"))
    (row,) = t.encounter["hits"]
    assert row[5] == "Riposte Slay Undead", "one annotation in the log, one on the row"


def test_the_cap_holds_and_reports_what_it_dropped():
    t = CharacterTracker("Kenkyo", "freeport")
    lines = [(i // 4, "You slash a wan ghoul knight for 1 points of damage.")
             for i in range(HIT_CAP + 25)]
    feed(t, *lines)
    enc = t.encounter
    assert len(enc["hits"]) == HIT_CAP
    assert enc["hits_dropped"] == 25
    # the counters are untouched by the cap
    assert enc["abilities"]["Slash"]["hits"] == HIT_CAP + 25


def test_hits_are_reachable_by_the_fights_start_stamp_and_only_in_memory():
    t = CharacterTracker("Kenkyo", "freeport")
    feed(t, (0, "You slash a wan ghoul knight for 69 points of damage."))
    started = t.encounter["started"].isoformat()

    view = t.hits_view(started)
    assert view["hits"] and view["cap"] == HIT_CAP and view["dropped"] == 0
    assert t.hits_view("2020-01-01T00:00:00") is None

    # the persisted/broadcast encounter view carries counters, never rows
    assert "hits" not in t.encounter_snapshot()


def test_rows_survive_the_fight_rolling_into_history():
    t = CharacterTracker("Kenkyo", "freeport")
    feed(t, (0, "You slash a wan ghoul knight for 69 points of damage."))
    first = t.encounter["started"].isoformat()
    # well past COMBAT_TIMEOUT_SECONDS: a new fight
    feed(t, (60, "You slash a kor ghoul wizard for 12 points of damage."))
    assert t.encounter["started"].isoformat() != first
    assert t.hits_view(first) is not None, "the last five fights keep their rows"
