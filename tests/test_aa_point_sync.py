"""AA gain and spend messages keep the unspent counter synchronized."""
import pytest

from backend.log_system import events as ev
from backend.log_system.parser import parse_line
from backend.state_tracker import CharacterTracker


STAMP = "[Fri Aug 14 00:00:00 2026] "


def _parse(message: str):
    event = parse_line(STAMP + message)
    assert event is not None, message
    return event


@pytest.mark.parametrize(
    "message, count, total",
    [
        ("You have gained an ability point!", 1, None),
        ("You have gained an ability point! You now have 1 ability point.",
         1, 1),
        ("You have gained 2 ability point(s)!  "
         "You now have 6 ability point(s).", 2, 6),
    ],
)
def test_parses_singular_batched_and_authoritative_aa_gains(
        message, count, total):
    event = _parse(message)
    assert isinstance(event, ev.AAPoint)
    assert event.count == count
    assert event.total == total


@pytest.mark.parametrize(
    "message, name, cost",
    [
        ('You have gained the ability "Foraging" at a cost of 3 ability '
         'points.', "Foraging", 3),
        ("You have improved Mnemonic Retention 6 at a cost of 3 ability "
         "points.", "Mnemonic Retention 6", 3),
        ("You have improved Symphonic Aura: Enabled at a cost of 0 ability "
         "points.", "Symphonic Aura: Enabled", 0),
    ],
)
def test_parses_both_aa_spend_shapes_including_zero_cost(
        message, name, cost):
    event = _parse(message)
    assert isinstance(event, ev.AASpend)
    assert event.name == name
    assert event.cost == cost


def test_authoritative_total_resyncs_then_spends_and_gains_adjust_it():
    tracker = CharacterTracker("TestCharacter", "testserver")
    tracker.aa_available = 99  # stale manual value

    tracker.apply(_parse(
        "You have gained 2 ability point(s)!  "
        "You now have 6 ability point(s)."), live=True)
    assert tracker.aa_points == 2
    assert tracker.aa_available == 6

    tracker.apply(_parse(
        'You have gained the ability "Foraging" at a cost of 3 ability '
        'points.'), live=True)
    assert tracker.aa_available == 3

    tracker.apply(_parse("You have gained an ability point!"), live=True)
    assert tracker.aa_points == 3
    assert tracker.aa_available == 4


def test_unknown_total_stays_unknown_until_the_log_supplies_one():
    tracker = CharacterTracker("TestCharacter", "testserver")
    assert tracker.aa_available is None

    tracker.apply(_parse(
        "You have improved Mnemonic Retention 6 at a cost of 3 ability "
        "points."), live=True)
    tracker.apply(_parse("You have gained an ability point!"), live=True)
    assert tracker.aa_available is None
    assert tracker.aa_points == 1

    tracker.apply(_parse(
        "You have gained 2 ability point(s)!  "
        "You now have 5 ability point(s)."), live=True)
    assert tracker.aa_available == 5
    assert tracker.aa_points == 3


def test_spends_floor_at_zero_and_zero_cost_toggle_does_not_subtract():
    tracker = CharacterTracker("TestCharacter", "testserver")
    tracker.aa_available = 1

    tracker.apply(_parse(
        "You have improved Mnemonic Retention 6 at a cost of 3 ability "
        "points."), live=True)
    assert tracker.aa_available == 0

    tracker.apply(_parse(
        "You have improved Symphonic Aura: Enabled at a cost of 0 ability "
        "points."), live=True)
    assert tracker.aa_available == 0


@pytest.mark.parametrize(
    "message",
    [
        "You have gained 2 ability points toward your next reward.",
        'You have gained the ability "Foraging" at a cost of three ability '
        "points.",
        "You have improved Mnemonic Retention 6 at no cost.",
    ],
)
def test_rejects_near_miss_aa_messages(message):
    assert parse_line(STAMP + message) is None
