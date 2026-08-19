"""Changing the game folder must not silently empty the map pack list.

The settings endpoint reassigned eql_maps_custom_dir to Dark Brewall and
nothing else whenever the install folder changed. A player running several
packs lost the rest of them: the folders stayed on disk and merely stopped
being searched, so it reads as maps going missing rather than as a setting
being reset.

Packs now follow the move by name, and _maps_dirs resolves a bare name
against the maps folder -- so the stored list is portable and an absolute
path to a pack kept somewhere else still works.
"""
from pathlib import Path

import pytest

from backend import map_system
from backend.config import settings
from backend.main import _repoint_packs

OLD = Path(r"C:\Games\EQL\maps")
NEW = Path(r"D:\Elsewhere\EQL\maps")
PACKS = ("Spiken's Maps", "Spiken's Brewall", "Dark Brewall")


def test_every_pack_survives_a_game_folder_change():
    stored = ";".join(str(OLD / p) for p in PACKS)
    assert _repoint_packs(stored, NEW) == ";".join(PACKS)


def test_a_pack_kept_outside_the_maps_folder_is_left_alone():
    outside = r"E:\shared\MyPack"
    stored = str(OLD / "Spiken's Maps") + ";" + outside
    assert _repoint_packs(stored, NEW) == "Spiken's Maps;" + outside


def test_an_empty_list_still_falls_back_to_brewall():
    assert _repoint_packs("", NEW) == "Dark Brewall"
    assert _repoint_packs("  ;  ", NEW) == "Dark Brewall"


def test_repointing_is_idempotent():
    once = _repoint_packs(";".join(str(OLD / p) for p in PACKS), NEW)
    assert _repoint_packs(once, NEW) == once


@pytest.fixture
def maps(tmp_path, monkeypatch):
    d = tmp_path / "maps"
    for p in PACKS:
        (d / p).mkdir(parents=True)
    monkeypatch.setattr(settings, "eql_maps_dir", str(d), raising=False)
    return d


def test_bare_names_resolve_against_the_maps_folder(maps, monkeypatch):
    monkeypatch.setattr(settings, "eql_maps_custom_dir", ";".join(PACKS),
                        raising=False)
    found = map_system._maps_dirs()
    assert found[:3] == [maps / p for p in PACKS]
    assert found[3] == maps          # stock maps sit behind every pack


def test_absolute_entries_give_the_same_search_order(maps, monkeypatch):
    """The old stored form must keep working unchanged."""
    monkeypatch.setattr(settings, "eql_maps_custom_dir",
                        ";".join(str(maps / p) for p in PACKS), raising=False)
    assert map_system._maps_dirs()[:4] == [maps / p for p in PACKS] + [maps]


def test_search_order_survives_a_round_trip_through_a_move(maps, monkeypatch):
    stored = ";".join(str(maps / p) for p in PACKS)
    moved_and_back = _repoint_packs(_repoint_packs(stored, NEW), maps)
    monkeypatch.setattr(settings, "eql_maps_custom_dir", moved_and_back,
                        raising=False)
    assert map_system._maps_dirs()[:3] == [maps / p for p in PACKS]
