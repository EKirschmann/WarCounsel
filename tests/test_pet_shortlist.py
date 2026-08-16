"""The deterministic pet pass runs BEFORE the model and does the arithmetic.

The pet path used to be LLM-proposes / gates-dispose with no independent
comparison, so "nothing better in your bags/bank for the pet" was asserted
whenever the model happened to propose nothing -- and unconditionally when no
LLM was configured. These tests pin the pass that now runs first.

Synthetic wiki lines throughout: no network, and the numbers are chosen so
each rule is exercised in isolation.
"""
import asyncio

import pytest

from backend.agent.advisor import (_pet_shortlist, _pet_shortlist_text,
                                   _pet_vec, _pet_primary, _pet_category)

HELD_2H = ("Slot: PRIMARY; Skill: 2H Slashing Atk Delay: 45; DMG: 25; "
           "STR: +10; Class: WAR SHD BER")
BIG_2H = ("Slot: PRIMARY; Skill: 2H Slashing Atk Delay: 52; DMG: 31; "
          "Class: WAR BER")
PROC_1H = ("Slot: PRIMARY SECONDARY; Skill: 1H Slashing Atk Delay: 24; "
           "DMG: 12; Effect: Ykesha (Combat, Casting Time: Instant); "
           "Class: WAR SHD")
HELD_CHEST = "Slot: CHEST; AC: 16 END: +15; Class: WAR PAL SHD"
BETTER_CHEST = "Slot: CHEST; AC: 20 END: +20; Class: WAR PAL SHD"
WORSE_CHEST = "Slot: CHEST; AC: 8; Class: WAR PAL SHD"


def _run(coro):
    return asyncio.get_event_loop_policy().new_event_loop().run_until_complete(coro)


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    """Held items are resolved through game_data.item_line -- stub it."""
    lines = {"held greataxe": HELD_2H, "held breastplate": HELD_CHEST}

    async def fake_item_line(name, *a, **k):
        return lines.get(str(name).lower())

    import backend.game_data as gd
    monkeypatch.setattr(gd, "item_line", fake_item_line, raising=True)
    yield


def test_delay_is_never_compared():
    """A pet keeps its own attack delay, so DELAY must not reach the vector."""
    assert "DELAY" not in _pet_vec(HELD_2H, 0)
    assert "DELAY" not in _pet_vec(BIG_2H, 0)


def test_primary_metric_is_damage_for_weapons_ac_otherwise():
    assert _pet_primary("WEAPON", _pet_vec(BIG_2H, 0)) == 31.0
    assert _pet_primary("CHEST", _pet_vec(HELD_CHEST, 0)) == 16.0


def test_higher_damage_weapon_surfaces_as_a_tradeoff():
    """The case that was invisible: +6 DMG against -10 STR."""
    sl = _run(_pet_shortlist([("Big Greataxe", BIG_2H)],
                             {1: "Held Greataxe"}, 1))
    assert len(sl) == 1
    e = sl[0]
    assert e["verdict"] == "trade-off"
    assert e["vs"] == "Held Greataxe"
    assert e["gain"].get("DMG") == 6.0
    assert e["loss"].get("STR") == 10.0
    assert "DELAY" not in e["gain"] and "DELAY" not in e["loss"]


def test_strict_win_is_a_clear_upgrade():
    sl = _run(_pet_shortlist([("Better Breastplate", BETTER_CHEST)],
                             {1: "Held Breastplate"}, 1))
    assert [e["verdict"] for e in sl] == ["clear upgrade"]


def test_strictly_worse_item_is_dropped():
    sl = _run(_pet_shortlist([("Worse Breastplate", WORSE_CHEST)],
                             {1: "Held Breastplate"}, 1))
    assert sl == []


def test_proccing_weapon_survives_a_damage_loss():
    """Procs are top picks for a pet even at low listed damage."""
    sl = _run(_pet_shortlist([("Ykesha Sword", PROC_1H)],
                             {1: "Held Greataxe"}, 1))
    assert len(sl) == 1 and sl[0]["proc"] is True
    assert sl[0]["loss"].get("DMG") == 13.0


def test_full_pet_gets_no_free_slot_suggestions():
    """With no room, a candidate must be framed as a SWAP or not at all."""
    sl = _run(_pet_shortlist([("Big Greataxe", BIG_2H)],
                             {1: "Held Greataxe"}, 1))
    assert all(e["vs"] is not None for e in sl)


def test_unreadable_held_item_suppresses_free_slot_fills():
    """An item we cannot read has an unknown KIND.

    Offering a candidate for a "free slot" then hides a displacement. The
    stub returns None for this name, so the pass must stay silent rather
    than guess.
    """
    sl = _run(_pet_shortlist([("Big Greataxe", BIG_2H)],
                             {1: "Mystery Item"}, 6))
    assert sl == [], "must not offer a free-slot fill beside an unreadable held item"


def test_text_render_states_what_is_given_up():
    sl = _run(_pet_shortlist([("Big Greataxe", BIG_2H)],
                             {1: "Held Greataxe"}, 1))
    txt = _pet_shortlist_text(sl)
    assert "TRADE-OFF" in txt
    assert "loses" in txt and "STR" in txt
    assert "delay excluded" in txt
    assert _pet_shortlist_text([]) == "", "no findings must render nothing"


def test_category_helper_recognises_a_weapon_and_a_chest():
    assert _pet_category(HELD_2H) == "WEAPON"
    assert _pet_category(HELD_CHEST) == "CHEST"
