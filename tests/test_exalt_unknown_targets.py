"""An empty relocation list is not proof the stone cannot be moved.

Reported by @soaringswine in #10: `_exalt_targets` returned a bare list, and
an empty one could mean "every candidate was definitively rejected" OR "the
metadata was never there". The caller could not tell them apart, set
targets_checked = True whenever no exception was raised, and the gear line
then asserted:

    Smoldering Robe (focus stone — CANNOT be moved: no other owned item has
    a free focus socket in a slot it fits)

from a lookup that never ran. Not a rare path either -- wiki coverage was
measured at 53 of 79 owned items, so a missing page is the common case.

This is the narrow half: absence of evidence stops being reported as
evidence of absence. The per-candidate proven/incompatible/unknown split is
#10's own proposal and is not this.
"""
import asyncio

from backend.agent import advisor

ROBE = {"classes": {"NEC", "WIZ", "MAG", "ENC"}, "slots": {"CHEST"},
        "is_weapon": False, "is_2h": False}
COAT = {"classes": {"NEC", "WIZ", "MAG", "ENC"}, "slots": {"CHEST"},
        "is_weapon": False, "is_2h": False}
PLATE = {"classes": {"WAR", "CLR", "PAL"}, "slots": {"CHEST"},
         "is_weapon": False, "is_2h": False}


def meta_from(table):
    async def _meta(name):
        return table.get(advisor._item_base(name).lower())
    return _meta


def _run(coro):
    return asyncio.get_event_loop_policy().new_event_loop().run_until_complete(coro)


def targets(monkeypatch, table, candidates, stone="Smoldering Robe"):
    monkeypatch.setattr(advisor, "_item_meta", meta_from(table))
    return _run(advisor._exalt_targets(stone, "focus", candidates, None))


def test_a_real_rejection_is_still_authoritative(monkeypatch):
    """Class mismatch is evidence, so the answer stays checked."""
    found, checked = targets(
        monkeypatch, {"smoldering robe": ROBE, "plate cuirass": PLATE},
        ["Plate Cuirass"])
    assert (found, checked) == ([], True)


def test_a_real_match_is_still_found(monkeypatch):
    found, checked = targets(
        monkeypatch, {"smoldering robe": ROBE, "damask robe": COAT},
        ["Damask Robe"])
    assert (found, checked) == (["Damask Robe"], True)


def test_a_missing_candidate_page_makes_the_answer_incomplete(monkeypatch):
    """The reported case: nothing found, but nothing was actually checked."""
    found, checked = targets(
        monkeypatch, {"smoldering robe": ROBE}, ["Some Unindexed Robe"])
    assert found == []
    assert checked is False, "an unchecked candidate cannot prove a negative"


def test_a_missing_stone_page_makes_the_answer_incomplete(monkeypatch):
    found, checked = targets(monkeypatch, {"damask robe": COAT},
                                   ["Damask Robe"])
    assert (found, checked) == ([], False)


def test_one_unknown_candidate_taints_an_otherwise_good_answer(monkeypatch):
    """A found target is real; "ONLY that one" is what is no longer provable."""
    found, checked = targets(
        monkeypatch, {"smoldering robe": ROBE, "damask robe": COAT},
        ["Damask Robe", "Some Unindexed Robe"])
    assert found == ["Damask Robe"]
    assert checked is False
