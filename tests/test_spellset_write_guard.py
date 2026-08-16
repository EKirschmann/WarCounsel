"""Never write LO*.ini while the client is running.

The write is surgical against the FILE, but the client keeps the whole
[SpellLoadouts] section in MEMORY and rewrites it wholesale when it flushes.
So a write during a session loses data in both directions: the set we wrote is
erased by the client's next flush, and a set the player saved in game -- still
only in memory -- is absent from the file we read and therefore from the copy
we write back.

Reported live: spell sets saved in game kept vanishing, and switching the
feature off fixed it. The endpoint had carried a NOTE about this all along,
which is advice the player has to read and act on, not a guard.
"""
from pathlib import Path

import pytest

import backend.spellsets as ss
from backend.spellsets import GameRunning, write_spell_set

SAMPLE = "\n".join([
    "[HotButtons]",
    "Foo=1",
    "[SpellLoadouts]",
    "SpellLoadout1.inuse=1",
    "SpellLoadout1.name=existing",
    "SpellLoadout1.slot1=42",
    "[Socials]",
    "Bar=2",
    "",
])


@pytest.fixture
def ini(tmp_path):
    p = tmp_path / "Gentso_rivervale_LO1.ini"
    p.write_text(SAMPLE, encoding="utf-8")
    return p


def test_refuses_while_the_game_is_running(monkeypatch, ini):
    monkeypatch.setattr("backend.eqclient.game_running", lambda: True)
    before = ini.read_bytes()
    with pytest.raises(GameRunning):
        write_spell_set(ini, "companion", [1, 2, 3])
    assert ini.read_bytes() == before, "the file must not be touched at all"


def test_writes_when_the_game_is_closed(monkeypatch, ini):
    monkeypatch.setattr("backend.eqclient.game_running", lambda: False)
    write_spell_set(ini, "companion", [7, 8, 9])
    txt = ini.read_text(encoding="utf-8")
    assert "name=companion" in txt
    assert "slot1=7" in txt


def test_existing_sets_are_preserved(monkeypatch, ini):
    monkeypatch.setattr("backend.eqclient.game_running", lambda: False)
    write_spell_set(ini, "companion", [7])
    txt = ini.read_text(encoding="utf-8")
    assert "name=existing" in txt and "slot1=42" in txt
    assert "[HotButtons]" in txt and "[Socials]" in txt


def test_a_failed_process_probe_does_not_block(monkeypatch, ini):
    """Refusing on a broken probe would strand the feature entirely."""
    def boom():
        raise OSError("no process table")
    monkeypatch.setattr("backend.eqclient.game_running", boom)
    write_spell_set(ini, "companion", [5])
    assert "name=companion" in ini.read_text(encoding="utf-8")


def test_explicit_override_still_possible(monkeypatch, ini):
    monkeypatch.setattr("backend.eqclient.game_running", lambda: True)
    write_spell_set(ini, "companion", [5], allow_while_running=True)
    assert "name=companion" in ini.read_text(encoding="utf-8")


def test_message_tells_the_player_what_to_do(monkeypatch, ini):
    monkeypatch.setattr("backend.eqclient.game_running", lambda: True)
    with pytest.raises(GameRunning) as e:
        write_spell_set(ini, "companion", [1])
    msg = str(e.value).lower()
    assert "camp" in msg, "the error must say how to proceed, not just refuse"
