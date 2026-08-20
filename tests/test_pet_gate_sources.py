"""A pet spell is dropped only when there is PROOF the trio has no pet.

The gate exists because a Paladin/Druid/Monk was told to slot Tiny
Companion -- "improves pet mobility" -- with no pet to improve. It read one
source, the eqlbuilds spell snapshot, scanned for effect 33/71, and that
was wrong in both directions:

- A BEASTLORD has no 33/71 spell in that snapshot at all, so a BST/MNK/WAR
  trio had Tiny Companion -- a Beastlord spell -- dropped from its own
  loadout. It survived only when a real summoner happened to share the trio.
- With no snapshot the scan returned False, so a MAGICIAN counted as
  pet-less and lost every pet spell.

Now the vendored capability table answers too: either source saying yes is
yes, only a source that answered can say no, and neither knowing is None,
which leaves the picks alone.
"""
import pytest

from backend import builds_data, capabilities
from backend.agent import advisor

PET_SPELL = {"name": "Tiny Companion"}          # BST L19, target type 14
NOT_A_PET_SPELL = {"name": "Spirit of the Shrew"}


def gate(trio):
    picks = [dict(PET_SPELL), dict(NOT_A_PET_SPELL)]
    return [p["name"] for p in advisor._gate_pet_spells(picks, trio)]


def test_a_beastlord_has_a_pet():
    """The regression. The spell scan alone still says False here."""
    assert advisor._pet_from_spells(["Beastlord"]) is False
    assert advisor._summons_a_pet(["Beastlord"]) is True


def test_a_beastlord_keeps_its_own_pet_spell_without_a_summoner_alongside():
    assert "Tiny Companion" in gate(["Beastlord", "Monk", "Warrior"])


def test_the_original_bug_stays_fixed():
    """PAL/DRU/MNK summons nothing, and both sources agree on that."""
    assert advisor._summons_a_pet(["Paladin", "Druid", "Monk"]) is False
    assert "Tiny Companion" not in gate(["Paladin", "Druid", "Monk"])


def test_both_sources_agree_on_every_other_class():
    from backend.log_system.parser import CLASS_ABBREV
    for full in CLASS_ABBREV.values():
        if full == "Beastlord":
            continue
        assert advisor._pet_from_spells([full]) == advisor._summons_a_pet([full]), full


def test_the_table_alone_carries_it_when_the_spell_snapshot_is_missing(monkeypatch):
    """A Magician without the eqlbuilds clone used to lose every pet spell."""
    monkeypatch.setattr(builds_data, "classes_data", lambda: None)
    assert advisor._pet_from_spells(["Magician"]) is None
    assert advisor._summons_a_pet(["Magician"]) is True
    assert "Tiny Companion" in gate(["Magician", "Wizard", "Enchanter"])


def test_the_spell_scan_alone_still_carries_it_without_the_table(monkeypatch):
    monkeypatch.setattr(capabilities, "trio_capabilities", lambda c: None)
    assert advisor._summons_a_pet(["Magician"]) is True
    assert advisor._summons_a_pet(["Paladin", "Druid", "Monk"]) is False


def test_neither_source_is_unknown_and_drops_nothing(monkeypatch):
    monkeypatch.setattr(capabilities, "trio_capabilities", lambda c: None)
    monkeypatch.setattr(builds_data, "classes_data", lambda: None)
    assert advisor._summons_a_pet(["Magician"]) is None
    assert gate(["Magician", "Wizard", "Enchanter"]) == [
        "Tiny Companion", "Spirit of the Shrew"]


def test_unknown_never_becomes_a_NO_PET_claim_in_the_prompt(monkeypatch):
    """ctx["_no_pet"] is `is False`, so None cannot assert there is no pet."""
    monkeypatch.setattr(capabilities, "trio_capabilities", lambda c: None)
    monkeypatch.setattr(builds_data, "classes_data", lambda: None)
    verdict = advisor._summons_a_pet(["Magician"])
    assert (verdict is False) is False
    assert (not verdict) is True, "the old expression would have claimed NO PET"
