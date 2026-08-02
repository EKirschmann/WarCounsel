"""The stats panel parser, against a real capture.

The first version was written from a guess at the layout and passed its own
invented fixtures completely: it looked for "STR" where the panel says
"Strength", matched the "STA" inside "STATS AND RESISTS" and reported a
Stamina of 5, and never read a single cap. Everything downstream of it --
the whole point of the feed -- was therefore dead.

So the fixture here is a REAL capture, kept verbatim.
"""
import pathlib

from backend.ocr_system import parse_stats_text

FIXTURE = pathlib.Path(__file__).parent / "fixtures" / "ocr_stats_panel.txt"


def test_reads_attributes_with_their_caps():
    got = parse_stats_text(FIXTURE.read_text(encoding="utf-8"))
    assert got["str"] == 196 and got["cap_str"] == 510
    assert got["sta"] == 193 and got["agi"] == 95
    assert got["dex"] == 123 and got["wis"] == 87
    assert got["int"] == 82 and got["cha"] == 55


def test_reads_pools_and_resists():
    got = parse_stats_text(FIXTURE.read_text(encoding="utf-8"))
    assert (got["hp"], got["max_hp"]) == (1187, 1187)
    assert (got["mana"], got["max_mana"]) == (672, 672)
    assert got["ac"] == 303
    # resists cap at 1000, not the attributes' 510
    assert got["sv_magic"] == 32 and got["cap_sv_magic"] == 1000


def test_does_not_invent_values():
    # "Attack" reads as a merged "1861238" in this capture -- a number that
    # long is not a stat, and a wrong ATK is worse than no ATK.
    assert "atk" not in parse_stats_text(FIXTURE.read_text(encoding="utf-8"))
    assert parse_stats_text("the quick brown fox 12 34") == {}
    assert parse_stats_text("") == {}
