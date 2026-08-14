"""Every location the parser can name must reach the gear gates.

PR #9 taught the inventory parser to tell Equipment overflow, the Dragon's
Hoard and the Personal Depot apart from bags. Three gates in
generate_gear_advice still spelled the answer out as ("bags", "bank"), so
items dropped out of the pet-gear pool purely because they had stopped being
mislabelled — on a real export, 21 of them.

`bank` being on the original list is the giveaway: the rule was never "in
your bags", it was "owned, not worn, go and get it".
"""
import inspect

from backend import spellbook
from backend.agent import advisor


def test_every_non_worn_location_the_parser_emits_is_retrievable():
    """The classifier and the gate cannot drift apart silently."""
    emitted = set()
    for label in ("General 1", "Bank1", "SharedBank2", "Equipment",
                  "Hoard 1", "Personal-Depot1", "Bankruptcy1", "Hoarding 1"):
        emitted.add(spellbook._inventory_where(label))
    emitted.discard("worn")
    missing = emitted - spellbook.RETRIEVABLE
    assert not missing, f"parser emits {missing}, which no gear gate accepts"


def test_worn_is_not_retrievable():
    """Worn gear is not spare — that distinction is the point of the gate."""
    assert "worn" not in spellbook.RETRIEVABLE
    assert spellbook._inventory_where("Chest") == "worn"


def test_gear_gates_use_the_shared_set_not_a_literal():
    """A repeated tuple is what let #9's regression through in the first place."""
    src = inspect.getsource(advisor.generate_gear_advice)
    assert '("bags", "bank")' not in src, "a gate still hardcodes the old pair"
    assert src.count("RETRIEVABLE") >= 2


def test_near_misses_still_fall_back_to_bags():
    """#9's exactness must survive: a near miss is bags, not a wrong pool."""
    for label in ("Bankruptcy1", "SharedBankruptcy1", "Hoarding 1",
                  "Personal-DepotBackup1", "EquipmentBackup"):
        assert spellbook._inventory_where(label) == "bags", label
