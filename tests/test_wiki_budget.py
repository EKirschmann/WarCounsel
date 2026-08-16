"""The wiki context must not starve whole sections.

build_wiki_context truncates its TAIL, and the tail is the AA list. Measured
on a real character at the production 12,000-char budget: 4 of 7 sections
arrived and **0 of 73 AA entries**, while the prompt still asked for
aa_now/aa_save "using the per-rank costs in the data". Two skill-cap sections
vanished the same way.

_fit_wiki shares the budget instead of cutting the end off, and names what it
dropped so a partial list is never read as a complete one.
"""
from backend.agent.advisor import _fit_wiki, _trim_wiki


def _doc(sections):
    return "\n".join("## %s\n%s" % (name, "\n".join(rows))
                     for name, rows in sections)


BIG = _doc([
    ("Paladin spells", ["L%d Spell %d [mana 40] does a thing" % (i, i)
                        for i in range(120)]),
    ("Necromancer spells", ["L%d Dark %d [mana 40] does a thing" % (i, i)
                            for i in range(120)]),
    ("AAs", ["[class] AA %d (5 ranks, 3 pts) something useful" % i
             for i in range(70)]),
])


def test_untouched_when_it_already_fits():
    small = _doc([("AAs", ["[class] AA 1 (1 rank, 1 pt) x"])])
    assert _fit_wiki(small, 10_000) == small


def test_every_section_survives_the_budget():
    out = _fit_wiki(BIG, 6_000)
    for name in ("Paladin spells", "Necromancer spells", "AAs"):
        assert "## " + name in out, f"{name} was starved out of the budget"


def test_the_tail_section_keeps_real_entries():
    """The regression: AAs are last and used to arrive empty."""
    out = _fit_wiki(BIG, 6_000)
    aa_body = out.split("## AAs", 1)[1]
    assert aa_body.count("[class] AA") >= 5, (
        "the last section must carry real entries, not just its header")


def test_budget_is_respected():
    out = _fit_wiki(BIG, 6_000)
    assert len(out) <= 6_000


def test_partial_sections_say_so():
    """A truncated list read as complete is worse than a short one."""
    out = _fit_wiki(BIG, 6_000)
    assert "this list is PARTIAL" in out
    assert "more entries not shown" in out


def test_trim_drops_only_pregated_rows():
    wiki = _doc([("Paladin spells", [
        "L24 Symbol of Transal [mana 55] buffs hp",
        "L20 Courage [mana 10] weak buff",
    ])])
    out = _trim_wiki(wiki, {"Courage": "superseded by owned Valor"})
    assert "Symbol of Transal" in out
    assert "Courage" not in out


def test_trim_is_a_noop_without_pregated_spells():
    wiki = _doc([("Paladin spells", ["L24 Symbol of Transal [mana 55] buffs"])])
    assert _trim_wiki(wiki, {}) == wiki
