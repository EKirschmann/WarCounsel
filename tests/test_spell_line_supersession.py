"""Regression coverage for advisor spell-line pruning."""

import asyncio

from backend import game_data
from backend.agent import advisor


def _dot(counter_spa: int, damage: int) -> dict:
    return {
        "targetTypeId": 5,
        "classes": ["Necromancer", "Shaman"],
        "durationTicks": 12,
        "effects": [
            {"slot": 1, "effectId": counter_spa, "baseValue": 4},
            {"slot": 2, "effectId": 0, "baseValue": -damage},
        ],
    }


def _records() -> dict:
    return {
        "Scourge": _dot(35, 73),       # disease counter
        "Envenomed Bolt": _dot(36, 295),
        "Venom of the Snake": _dot(36, 171),  # poison counter
        "Insidious Malady": {
            "targetTypeId": 5,
            # Shaman-only per the eqlbuilds snapshot (id 527). This
            # fixture said "Necromancer" until the same wrong class
            # reached a live consult -- nothing read `cls`, so nothing
            # caught either one.
            "classes": ["Shaman"],
            "durationTicks": 140,
            "effects": [
                {"slot": 1, "effectId": 35, "baseValue": 9},
                {"slot": 2, "effectId": 49, "baseValue": -10},
            ],
        },
    }


def _install_records(monkeypatch) -> None:
    records = _records()

    async def fake_spell_record(name: str):
        return records.get(name)

    monkeypatch.setattr(game_data, "spell_record", fake_spell_record)
    advisor._VIABLE_MEMO.clear()


def test_poison_upgrade_still_supersedes_weaker_poison_dot(monkeypatch):
    _install_records(monkeypatch)

    assert asyncio.run(game_data.same_spell_line(
        "Venom of the Snake", "Envenomed Bolt"))
    assert asyncio.run(game_data.supersedes_for_slots(
        "Venom of the Snake", "Envenomed Bolt"))


def test_poison_dot_does_not_supersede_disease_dot(monkeypatch):
    _install_records(monkeypatch)

    assert not asyncio.run(game_data.same_spell_line(
        "Scourge", "Venom of the Snake"))
    assert not asyncio.run(game_data.supersedes_for_slots(
        "Scourge", "Venom of the Snake"))


def test_advisor_keeps_disease_dot_poison_dot_and_disease_debuff(monkeypatch):
    _install_records(monkeypatch)
    names = ["Scourge", "Venom of the Snake", "Insidious Malady"]

    live, dropped = asyncio.run(advisor._viable_candidates(names, solo=True))

    assert live == names
    assert dropped == {}


def test_prompt_marks_disease_dot_and_non_damage_debuff(monkeypatch):
    records = _records()
    monkeypatch.setattr(
        advisor.builds_data, "spell_entry", lambda name: records.get(name))
    ctx = {
        "level": 39,
        "spell_slots": 14,
        "spellbook": {
            "age_hours": 0.0,
            "castable": [
                {"name": "Scourge", "level": 31},
                {"name": "Insidious Malady", "level": 38},
            ],
            "other_loadouts": [],
        },
    }

    prompt = advisor._build_prompt(ctx, "")

    assert "Scourge (L31; DoT)" in prompt
    assert "Insidious Malady (L38; non-damage)" in prompt
    assert "never describe a non-damage spell as a DoT" in prompt


# --- `cls` stamping and reason grounding -----------------------------------
#
# Both fields are written free-form by the model and neither was ever read,
# which shipped "Insidious Malady (L38) | Necromancer | Your highest-level
# disease DoT" -- wrong class AND wrong type on one row.

_LEVELS = {
    "insidious malady": {"Shaman": 38},
    "scourge": {"Necromancer": 35, "Shaman": 49},
}


def _install_levels(monkeypatch) -> None:
    records = _records()
    monkeypatch.setattr(
        advisor.builds_data, "spell_levels",
        lambda name: dict(_LEVELS.get(name.strip().lower(), {})))
    monkeypatch.setattr(advisor.builds_data, "spell_entry",
                        lambda name: records.get(name))
    monkeypatch.setattr(advisor.builds_data, "effect_summary",
                        lambda entry, cap=110: "disease resistance 10 to 60")


def test_stamps_the_class_that_actually_learns_the_spell(monkeypatch):
    _install_levels(monkeypatch)
    picks = [{"name": "Insidious Malady", "cls": "Necromancer", "reason": "x"}]

    advisor._stamp_owner_class(picks, ["Bard", "Shaman", "Necromancer"])

    assert picks[0]["cls"] == "Shaman"


def test_stamp_names_every_trio_class_that_learns_it(monkeypatch):
    _install_levels(monkeypatch)
    picks = [{"name": "Scourge", "cls": "Bard", "reason": "x"}]

    advisor._stamp_owner_class(picks, ["Bard", "Shaman", "Necromancer"])

    assert picks[0]["cls"] == "Necromancer/Shaman"


def test_stamp_leaves_unknown_spells_alone(monkeypatch):
    """Absence of data is not evidence -- the partial-coverage rule."""
    _install_levels(monkeypatch)
    picks = [{"name": "Not In The Snapshot", "cls": "Bard", "reason": "x"}]

    advisor._stamp_owner_class(picks, ["Bard", "Shaman"])

    assert picks[0]["cls"] == "Bard"


def test_stamp_leaves_cls_alone_when_no_trio_class_learns_it(monkeypatch):
    """A data mismatch is logged, never silently blanked."""
    _install_levels(monkeypatch)
    picks = [{"name": "Insidious Malady", "cls": "Necromancer", "reason": "x"}]

    advisor._stamp_owner_class(picks, ["Bard", "Necromancer", "Wizard"])

    assert picks[0]["cls"] == "Necromancer"


def test_reason_claiming_damage_on_a_debuff_is_annotated(monkeypatch):
    _install_levels(monkeypatch)
    picks = [{"name": "Insidious Malady", "cls": "Shaman",
              "reason": "Your highest-level disease DoT (L38)."}]

    advisor._gate_reason_claims(picks)

    assert "no HP-loss effect" in picks[0]["reason"]
    assert "disease resistance 10 to 60" in picks[0]["reason"]
    assert picks[0]["reason"].startswith("Your highest-level disease DoT")


def test_a_real_dots_reason_is_left_alone(monkeypatch):
    _install_levels(monkeypatch)
    picks = [{"name": "Scourge", "cls": "Necromancer",
              "reason": "Your strongest disease DoT."}]

    advisor._gate_reason_claims(picks)

    assert picks[0]["reason"] == "Your strongest disease DoT."


def test_correct_debuff_reason_is_annotated_not_rewritten(monkeypatch):
    """The trigger fires on correct prose too -- a resist debuff's real
    rationale names DoTs ("so your disease DoTs land"). Accepted on
    purpose: the note reads as fact there and as refutation on a false
    row, and tightening the pattern would let real fabrications past."""
    _install_levels(monkeypatch)
    picks = [{"name": "Insidious Malady", "cls": "Shaman",
              "reason": "Lowers disease resistance so your DoTs land."}]

    advisor._gate_reason_claims(picks)

    assert picks[0]["reason"].startswith(
        "Lowers disease resistance so your DoTs land.")
    assert "no HP-loss effect" in picks[0]["reason"]


def test_reason_without_a_damage_claim_is_untouched(monkeypatch):
    _install_levels(monkeypatch)
    picks = [{"name": "Insidious Malady", "cls": "Shaman",
              "reason": "Softens the target before you open up."}]

    advisor._gate_reason_claims(picks)

    assert picks[0]["reason"] == "Softens the target before you open up."
