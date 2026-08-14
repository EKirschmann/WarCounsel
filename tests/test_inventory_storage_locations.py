"""Inventory export coverage for worn, carried, and extended storage."""
from pathlib import Path

import pytest

from backend import spellbook


FIXTURE = Path(__file__).parent / "fixtures" / "inventory_extended_storage.tsv"


@pytest.mark.parametrize(
    "location, expected",
    [
        ("Bank1", "bank"),
        ("Bank24", "bank"),
        ("SharedBank1", "bank"),
        ("Hoard 1", "hoard"),
        ("Personal-Depot1", "depot"),
        ("Equipment", "stash"),
        ("General 1", "bags"),
        ("Bankruptcy1", "bags"),
        ("SharedBankruptcy1", "bags"),
        ("Hoarding 1", "bags"),
        ("Personal-DepotBackup1", "bags"),
        ("EquipmentBackup", "bags"),
    ],
)
def test_storage_location_matcher_accepts_only_game_labels(location, expected):
    assert spellbook._inventory_where(location) == expected


def test_inventory_export_preserves_storage_socket_and_stack_semantics(
        monkeypatch, tmp_path):
    export = tmp_path / "TestCharacter_testserver-Inventory.txt"
    export.write_bytes(FIXTURE.read_bytes())
    monkeypatch.setattr(
        spellbook, "_find_export",
        lambda _name, _server, _kind: export,
    )
    spellbook._export_cache.clear()

    got = spellbook.load_export("TestCharacter", "testserver", "Inventory")
    assert got is not None
    by_name = {item["name"]: item for item in got["items"]}

    assert got["worn"] == {
        "Ear 1": "Copper Hoop",
        "Ear 2": "Silver Stud",
        "Fingers 1": "Brass Ring",
        "Chest": "Guardian Tunic",
    }
    assert by_name["Quest Token"]["where"] == "bags"
    assert by_name["Quest Token"]["count"] == 27
    assert by_name["Banker's Satchel"]["where"] == "bank"
    assert by_name["Banked Component"]["where"] == "bank"
    assert by_name["Shared Relic"]["where"] == "bank"
    assert by_name["Shared Component"]["where"] == "bank"
    assert by_name["Stashed Cloak"]["where"] == "stash"
    assert by_name["Archived Spear"]["where"] == "hoard"
    assert by_name["Crafting Powder"]["where"] == "depot"
    assert by_name["Crafting Powder"]["count"] == 42

    # Prefix-like but invalid labels must keep the conservative bags default.
    for name in ("Travel Ledger", "Guild Ledger", "Keepsake",
                 "Spare Powder", "Spare Cloak"):
        assert by_name[name]["where"] == "bags"

    chest = by_name["Guardian Tunic"]
    assert chest["sockets"] == {
        2: "Drum Stone (Exaltation)",
        7: None,
        8: "Socket Metadata",
    }
    assert got["exaltations"] == [{
        "name": "Drum Stone (Exaltation)",
        "socket": 2,
        "host_loc": "Chest",
        "host": "Guardian Tunic",
        "where": "worn",
    }]

    # Socket metadata is not an owned inventory row, including in the Hoard.
    assert "Socket Metadata" not in by_name
    assert "Hoard Socket Metadata" not in by_name
    assert "Empty" not in by_name
    assert "Name" not in by_name
