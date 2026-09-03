"""Attack rounds: our swings grouped by (second, target, verb).

The log stamps whole seconds, so a round's swings share a stamp and the
group size is the number of attacks it produced. Kick and bash cannot be
dual wielded, so a two-swing round there is a double attack and nothing
else -- the one clean read. Weapon verbs are contaminated by two hands and
the view says so rather than pretending.
"""
from datetime import datetime, timedelta

from backend.log_system.parser import parse_line
from backend.state_tracker import MIN_ROUNDS_FOR_RATE, CharacterTracker

T0 = datetime(2026, 7, 10, 21, 25, 0)


def feed(t: CharacterTracker, *lines):
    for offset, text in lines:
        stamp = (T0 + timedelta(seconds=offset)).strftime("[%a %b %d %H:%M:%S %Y]")
        e = parse_line(f"{stamp} {text}")
        assert e is not None, text
        t.apply(e, live=True)


KICK = "You kick a wan ghoul knight for 5 points of damage."
KICK_MISS = "You try to kick a wan ghoul knight, but miss!"
SLASH = "You slash a wan ghoul knight for 5 points of damage."


def test_same_second_same_target_same_verb_is_one_round():
    t = CharacterTracker("Kenkyo", "freeport")
    feed(t, (0, KICK), (0, KICK), (1, KICK), (2, KICK_MISS), (2, KICK),
         (9, SLASH))  # a later swing closes the last kick round
    r = t.attack_rounds()
    kick = next(v for v in r["verbs"] if v["verb"] == "kick")
    assert kick["dist"] == {1: 1, 2: 2}, "two doubles (one with a miss in it), one single"
    assert kick["rounds"] == 3 and kick["multi"] == 2
    assert kick["clean"] is True


def test_a_different_target_in_the_same_second_is_a_different_round():
    t = CharacterTracker("Kenkyo", "freeport")
    feed(t, (0, KICK),
         (0, "You kick a kor ghoul wizard for 5 points of damage."),
         (5, SLASH))
    kick = next(v for v in t.attack_rounds()["verbs"] if v["verb"] == "kick")
    assert kick["dist"] == {1: 2}


def test_the_final_round_is_closed_by_any_later_event():
    """No swing follows the last one of a fight; the clock moving on --
    an XP line, a zone line, anything a second later -- closes it."""
    t = CharacterTracker("Kenkyo", "freeport")
    feed(t, (0, KICK), (0, KICK))
    assert t.attack_rounds() is None, "still inside the round's second"
    feed(t, (3, "You gain experience! (1.019%)"))
    kick = next(v for v in t.attack_rounds()["verbs"] if v["verb"] == "kick")
    assert kick["dist"] == {2: 1}


def test_rates_wait_for_enough_rounds_and_weapon_verbs_are_marked_unclean():
    t = CharacterTracker("Kenkyo", "freeport")
    lines = []
    for i in range(MIN_ROUNDS_FOR_RATE - 1):
        lines.append((i * 2, KICK))
    lines.append((200, SLASH)); lines.append((200, SLASH)); lines.append((205, KICK))
    feed(t, *lines)
    r = t.attack_rounds()
    kick = next(v for v in r["verbs"] if v["verb"] == "kick")
    slash = next(v for v in r["verbs"] if v["verb"] == "slash")
    assert kick["rounds"] == MIN_ROUNDS_FOR_RATE - 1 and kick["pct"] is None
    assert r["double_attack_pct"] is None and r["clean_rounds"] == MIN_ROUNDS_FOR_RATE - 1
    assert slash["clean"] is False and slash["dist"] == {2: 1}

    feed(t, (300, KICK), (300, KICK), (310, SLASH))
    r = t.attack_rounds()
    kick = next(v for v in r["verbs"] if v["verb"] == "kick")
    assert kick["rounds"] == MIN_ROUNDS_FOR_RATE + 1
    assert r["double_attack_pct"] == kick["pct"] == round(100.0 * 1 / (MIN_ROUNDS_FOR_RATE + 1), 1)
    assert r["verbs"][0]["clean"] is True, "clean verbs lead the list"


def test_rounds_reset_with_the_session():
    t = CharacterTracker("Kenkyo", "freeport")
    feed(t, (0, KICK), (5, SLASH))
    assert t.attack_rounds() is not None
    feed(t, (10, "Welcome to EverQuest Legends!"))
    assert t.attack_rounds() is None
