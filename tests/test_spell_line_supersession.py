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
            "classes": ["Necromancer"],
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
