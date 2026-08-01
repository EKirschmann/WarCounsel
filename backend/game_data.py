"""Wiki-grounded game data for the advisor.

Fetches class pages and the Alternate Advancement page from the EQL wiki
(eqlwiki.com, via the local MCP server), compacts their verbose tables into
terse one-liners an LLM can digest, and caches results for a day.

Fails soft: returns "" when the MCP server or wiki is unavailable, so the
advisor can still answer ungrounded (and says so).

Wiki text shapes this parser expects (verified 2026-07-06):
- Class pages: "Spells[edit | edit source]" then "Level N[edit...]" blocks;
  each spell row starts with the name DOUBLED and a stat blob
  ("StrikeStrikePAL(1)Mana: 7Cast: ..."), followed by table columns on their
  own lines: Type, Target, Mana, Max Effect, Duration, Description, ...
- "Alternate Advancement" page: General/Archetype/<Class> Class/Special AA
  sections, each a table of 4-line records: Name / Ranks / Cost / Description.
"""
import logging
import math
import re
from pathlib import Path
from typing import List, Optional

from backend.cache import wiki_page_cache
from backend.config import settings
from backend.map_system import _canonical
from backend import builds_data
from backend.mcp_client import get_mcp_client

logger = logging.getLogger(__name__)

WIKI_TTL = 24 * 3600
AA_PAGE = "Alternate Advancement"
MAX_CONTEXT_CHARS = 20_000

RE_LEVEL = re.compile(r"Level (\d+)\[edit[^\]]*\]")
RE_EDIT = re.compile(r"\[edit[^\]]*\]")


def _doubled_name(line: str) -> Optional[str]:
    """Spell rows start with the name doubled: 'StrikeStrikePAL(1)...'."""
    best = None
    limit = min(len(line) // 2, 48)
    for i in range(2, limit + 1):
        if line[:i] == line[i:2 * i]:
            best = line[:i]
    return best


def _iter_spell_rows(page_text: str):
    """Yield (level, name, cols) for every spell row on a class page."""
    start = page_text.find("Spells[edit")
    if start < 0:
        return
    end_m = re.search(r"\n[A-Z][A-Za-z' ]*AAs\[edit|\nSkills\[edit", page_text[start:])
    section = page_text[start:start + end_m.start()] if end_m else page_text[start:]

    headers = list(RE_LEVEL.finditer(section))
    for idx, h in enumerate(headers):
        lvl = int(h.group(1))
        stop = headers[idx + 1].start() if idx + 1 < len(headers) else len(section)
        lines = [ln.strip() for ln in section[h.end():stop].split("\n")]
        i = 0
        while i < len(lines):
            ln = lines[i]
            name = _doubled_name(ln) if ("Mana:" in ln or "Cast:" in ln) else None
            if not name:
                i += 1
                continue
            cols: List[str] = []
            j = i + 1
            while (j < len(lines) and lines[j] != ""
                   and "Mana:" not in lines[j] and "Cast:" not in lines[j]):
                cols.append(lines[j])
                j += 1
            yield lvl, name, cols
            i = j


def compact_spells(page_text: str, lo: int, hi: int) -> List[str]:
    """Compact a class page's per-level spell tables to one line per spell."""
    out: List[str] = []
    for lvl, name, cols in _iter_spell_rows(page_text):
        if lvl < lo or lvl > hi:
            continue
        kind = cols[0] if len(cols) > 0 else "?"
        target = cols[1] if len(cols) > 1 else ""
        mana = cols[2] if len(cols) > 2 else "?"
        desc = cols[5] if len(cols) > 5 else ""
        piece = f"L{lvl} {name} [{kind}" + (f", {target}" if target else "")
        piece += f", {mana} mana]"
        if desc and desc != name:
            piece += f" {desc[:120]}"
        out.append(piece)
    return out


# Spell pages carry a "Classes" section: "Necromancer - Level 1" per line.
RE_CLASS_LINE = re.compile(r"^([A-Z][A-Za-z ]+?) - Level \d+\s*$", re.MULTILINE)


async def spell_record(name: str) -> Optional[dict]:
    """Full structured spell record from the builds db (cached 24h)."""
    key = name.strip().lower()
    cached = wiki_page_cache.get("spell_record", key)
    if cached is not None:
        return cached or None
    sc = await get_mcp_client().call_tool(
        "eql_builds_spell", {"idOrName": name.strip()})
    sp = (sc or {}).get("spell")
    if sp is None and sc is None:
        # MCP server absent: the local eqlbuilds snapshot carries the same
        # record (effects, target, per-class levels) — synthesize from it
        sp = builds_data.spell_entry(name)
    if sp is not None and "levels" not in sp:
        lv = builds_data.spell_levels(name)
        if lv:
            sp = {**sp, "levels": lv}
    if sc is not None or sp is not None:
        wiki_page_cache.set(sp or {}, WIKI_TTL, "spell_record", key)
    return sp


# Teleport-family SPAs: 26 gate, 83 teleport (rings/circles), 88 succor/
# evac, 104 translocate (zephyrs). In EQL all of these are RITUALS cast
# outside the spell bar — they must never be suggested for memorization.
TRAVEL_SPAS = {26, 83, 88, 104}
_TRAVEL_NAMES = ("ring of", "circle of", "zephyr", "translocate", "portal")


async def is_travel_ritual(name: str) -> bool:
    low = name.strip().lower()
    if low.startswith(_TRAVEL_NAMES[:2]) or any(t in low for t in _TRAVEL_NAMES[2:]):
        return True
    rec = await spell_record(name)
    if not rec:
        return False
    return any((e.get("effectId") in TRAVEL_SPAS)
               for e in (rec.get("effects") or []))


RES_SPA = 81  # resurrect: returns a dead player to their corpse with xp
# Pet summons (33 pet, 71 undead pet): every rank carries the same effect
# magnitude, so strength lives ONLY in the unlock level — supersession for
# these lines is decided by level (from the eqlbuilds snapshot).
PET_SPAS = {33, 71}


def _is_pet(rec: Optional[dict]) -> bool:
    return any(e.get("effectId") in PET_SPAS
               for e in (rec or {}).get("effects") or [])


def _pet_unlock_level(name: str) -> Optional[int]:
    lv = builds_data.spell_levels(name)
    return min(lv.values()) if lv else None
# Effects whose baseValue is an ID, not a magnitude — never comparable
# ("Summon Drink supersedes Hammer of Striking" was a real bug: both are
# SPA 32 and the summoned item id compared as if it were power).
NONCOMPARABLE_SPAS = {32, 33, 85, 113}


async def is_resurrection(name: str) -> bool:
    """The res line (Reanimation/Reconstitution/Reparation) sounds like
    healing but is not — LLMs keep calling it 'self-sustain'. Detected by
    effect id so future ranks are covered automatically."""
    rec = await spell_record(name)
    if not rec:
        return False
    return any(e.get("effectId") == RES_SPA for e in (rec.get("effects") or []))


async def supersedes_for_slots(using: str, upgrade: str) -> bool:
    """Stricter than same_spell_line: for LOADOUT pruning the two spells
    must also share the exact castable-class set. Cross-class near-twins
    (Smite vs Careless Lightning) both deserve slots — different lines,
    resists, and timing — while true line-mates (Barbcoat -> Bramblecoat)
    share one class list and prune correctly."""
    if not await same_spell_line(using, upgrade):
        return False
    ra = await spell_record(using)
    rb = await spell_record(upgrade)
    ca = {str(x).lower() for x in (ra or {}).get("classes") or []}
    cb = {str(x).lower() for x in (rb or {}).get("classes") or []}
    if _is_pet(ra) and _is_pet(rb):
        # pet lines widen their class set as they rank up (Cavorting Bones
        # is NEC-only, Leering Corpse NEC+SHK) — overlap is enough
        return bool(ca & cb)
    return bool(ca) and ca == cb


def _primary_effect(rec: dict):
    """(effectId, base, magnitude) of the most meaningful effect.
    Symbol-style spells lead with zero-value placeholder slots (id 10
    charisma spacers), so prefer nonzero magnitudes; rank-1 spells like
    Reanimation legitimately carry base 0, so fall back to non-spacer
    effects rather than giving up."""
    effects = rec.get("effects") or []
    effs = [e for e in effects if e.get("baseValue")]
    if not effs:
        effs = [e for e in effects if e.get("effectId") not in (None, 10)]
    if not effs:
        return None
    prim = max(effs, key=lambda e: abs(e.get("baseValue") or 0))
    base = prim.get("baseValue") or 0
    return (prim.get("effectId"), base, abs(base))


async def same_spell_line(using: str, upgrade: str) -> bool:
    """True only when `upgrade` plausibly supersedes `using`: both are real
    spells doing the SAME JOB (same primary effect id and direction, same
    target type) with the upgrade hitting harder. Kills hallucinated pairs
    like a teleport 'upgrading' to a nuke — an LLM judgment this codebase
    no longer trusts unverified."""
    ra = await spell_record(using)
    rb = await spell_record(upgrade)
    if not ra or not rb:
        return False
    if ra.get("targetTypeId") != rb.get("targetTypeId"):
        return False
    if _is_pet(ra) and _is_pet(rb):
        la, lb = _pet_unlock_level(using), _pet_unlock_level(upgrade)
        return la is not None and lb is not None and lb > la
    pa = _primary_effect(ra)
    pb = _primary_effect(rb)
    if not pa or not pb:
        return False
    if pa[0] in NONCOMPARABLE_SPAS or pb[0] in NONCOMPARABLE_SPAS:
        return False
    if pa[0] != pb[0] or pb[2] <= pa[2]:
        return False
    # signs must agree unless one side is a zero-magnitude rank-1
    return pa[1] == 0 or pb[1] == 0 or (pa[1] > 0) == (pb[1] > 0)


_TRADESKILLS = {
    "Alchemy", "Alcohol Tolerance", "Baking", "Begging", "Blacksmithing",
    "Brewing", "Fishing", "Fletching", "Jewelry Making", "Make Poison",
    "Pottery", "Research", "Tailoring", "Tinkering", "Swimming",
}


async def build_modes_context() -> str:
    """Combat stances + invocations (builds db, cached 24h; '' if down)."""
    cached = wiki_page_cache.get("modes_context")
    if cached is not None:
        return cached
    sc = await get_mcp_client().call_tool("eql_builds_modes", {})
    if sc is None:
        return ""
    out = []
    for kind in ("stances", "invocations"):
        for m in sc.get(kind, []) or []:
            desc = str(m.get("description", "")).split(". ")[0][:170]
            out.append(f"{m.get('name')}: {desc}")
    text = chr(10).join(out)
    wiki_page_cache.set(text, WIKI_TTL, "modes_context")
    return text


async def class_skills_context(cls: str) -> str:
    """Combat-relevant skill caps for one class ('' when unavailable)."""
    cid = cls.strip().lower()
    cached = wiki_page_cache.get("skills_context", cid)
    if cached is not None:
        return cached
    sc = None
    for candidate in (cid, cid.replace(" ", ""), cid.replace(" ", "-")):
        sc = await get_mcp_client().call_tool("eql_builds_skills",
                                              {"classId": candidate})
        if sc and sc.get("skills"):
            break
    if not sc:
        return ""
    skills = [s for s in (sc.get("skills") or [])
              if s.get("name") not in _TRADESKILLS and s.get("cap", 0) > 0]
    skills.sort(key=lambda s: -s["cap"])
    text = "; ".join(f"{s['name']} (cap {s['cap']}, from L{s.get('trainedAt', 1)})"
                     for s in skills[:24])
    wiki_page_cache.set(text, WIKI_TTL, "skills_context", cid)
    return text


async def spell_classes(spell: str) -> Optional[set]:
    """Full class names that can cast `spell`, read from the spell's own wiki
    page (complete — unlike class pages, which truncate at 40k chars).
    None = wiki down or no such page (e.g. clicky-only effects): can't judge.
    An empty set (page exists, no Classes section) also means can't judge."""
    key = spell.strip().lower()
    cached = wiki_page_cache.get("spell_classes", key)
    if cached is not None:
        return cached
    sc = await get_mcp_client().call_tool(
        "eql_builds_spell", {"idOrName": spell.strip()})
    sp = (sc or {}).get("spell")
    if sp and sp.get("classes"):
        alias = {"Shadowknight": "Shadow Knight"}
        classes = {alias.get(str(x).title(), str(x).title()) for x in sp["classes"]}
        wiki_page_cache.set(classes, WIKI_TTL, "spell_classes", key)
        return classes
    page = await get_mcp_client().wiki_page(spell.strip(), max_characters=4000)
    if page is None:
        return None  # not cached: source may just be down, retry later
    text = page.get("text", "")
    m = re.search(r"\nClasses\n(.*?)\n(?:Spell Effects|Details)", text, re.DOTALL)
    section = m.group(1) if m else ""
    classes = {mm.group(1).strip() for mm in RE_CLASS_LINE.finditer(section)}
    wiki_page_cache.set(classes, WIKI_TTL, "spell_classes", key)
    return classes


def compact_aas(page_text: str, classes: List[str]) -> List[str]:
    """General + Archetype + the trio's Class AAs + Special, one line each."""
    text = RE_EDIT.sub("", page_text)

    def section(start_pat: str, end_pats: List[str]) -> str:
        m = re.search(start_pat, text)
        if not m:
            return ""
        rest = text[m.end():]
        cut = len(rest)
        for ep in end_pats:
            em = re.search(ep, rest)
            if em:
                cut = min(cut, em.start())
        return rest[:cut]

    # Class sections first: a global size cap trims the tail, and the trio's
    # class AAs matter more than General crafting passives.
    chunks = []
    for cls in classes:
        chunks.append((cls, section(
            rf"\n{re.escape(cls)} Class AAs\n",
            [r"\n[A-Z][A-Za-z ]+ Class AAs\n", r"\nSpecial AAs\n"])))
    chunks.append(("Archetype", section(r"\nArchetype AAs\n", [r"\nClass AAs\n"])))
    chunks.append(("Special", section(r"\nSpecial AAs\n", [])))
    chunks.append(("General", section(r"\nGeneral AAs\n", [r"\nArchetype AAs\n"])))

    out: List[str] = []
    for label, sect in chunks:
        for para in re.split(r"\n\s*\n", sect):
            ls = [x.strip() for x in para.strip().split("\n") if x.strip()]
            if len(ls) < 4 or ls[0] == "Name" or not re.fullmatch(r"\d+", ls[1]):
                continue
            desc = re.sub(r"\s+", " ", " ".join(ls[3:]))[:180]
            if label == "General" and "recipes" in desc:
                continue  # crafting Masteries: real but never advisor-worthy
            out.append(f"[{label}] {ls[0]} (ranks {ls[1]}, cost {ls[2]}) {desc}")
    return out


async def build_wiki_context(classes: List[str], level: Optional[int],
                             max_chars: int = MAX_CONTEXT_CHARS) -> str:
    """Assembled, size-capped wiki context for the advisor prompt ('' if none)."""
    if not settings.mcp_enabled or not classes:
        return ""
    lvl = level or 1
    lo, hi = max(1, lvl - 8), lvl + 12
    mcp = get_mcp_client()
    parts: List[str] = []

    for cls in classes:
        snap = builds_data.class_spell_lines(cls, lo, hi)
        if snap:  # eqlbuilds snapshot: exact levels, no scraping
            parts.append(f"## {cls} spells (window L{lo}-L{hi}, exact levels): "
                         "Lnn name [mana] effect\n" + "\n".join(snap[:60]))
            continue
        cached = wiki_page_cache.get("advisor_spells", cls, lo, hi)
        if cached is None:
            page = await mcp.wiki_page(cls)
            if page is not None:
                cached = "\n".join(compact_spells(page.get("text", ""), lo, hi)[:60])
                wiki_page_cache.set(cached, WIKI_TTL, "advisor_spells", cls, lo, hi)
            else:
                cached = ""  # fetch failed -- do not cache, retry next consult
        if cached:
            parts.append(f"## {cls} spells (window L{lo}-L{hi}): name [type, target, mana] effect\n{cached}")

    modes = await build_modes_context()
    if modes:
        parts.append("## Combat stances & invocations (pick per situation)" + chr(10) + modes)
    for cls in classes:
        sk = await class_skills_context(cls)
        if sk:
            parts.append(f"## {cls} skill caps (weapon/combat training)" + chr(10) + sk)

    aa_snap = builds_data.class_aa_lines(classes)
    if aa_snap:  # snapshot: exact ranks + per-rank costs
        parts.append("## AAs: [tab] name (ranks, cost per rank) effect\n"
                     + "\n".join(aa_snap[:160]))
    else:
        key = "/".join(classes)
        cached = wiki_page_cache.get("advisor_aas", key)
        if cached is None:
            page = await mcp.wiki_page(AA_PAGE)
            if page is not None:
                cached = "\n".join(compact_aas(page.get("text", ""), classes)[:160])
                wiki_page_cache.set(cached, WIKI_TTL, "advisor_aas", key)
            else:
                cached = ""  # fetch failed -- do not cache, retry next consult
        if cached:
            parts.append("## AAs: [tab] name (ranks, cost per rank) effect\n" + cached)

    return "\n\n".join(parts)[:max_chars]

# ------------------------------------------------------------------- gear

ITEM_STAT_PREFIXES = ("Slot:", "AC:", "DMG:", "Skill:", "Effect:",
                      "Focus Effect:", "Haste:")
ITEM_STAT_TOKENS = ("STR:", "STA:", "AGI:", "DEX:", "WIS:", "INT:", "CHA:",
                    "HP:", "MANA:", "SV ", "Atk Delay:")


def _strip_upgrade(name: str) -> str:
    """'Raw-Hide Cloak +4' -> 'Raw-Hide Cloak' (wiki pages use base names)."""
    return re.sub(r"\s*\+\d+$", "", name.strip())


# ------------------------------------------------ item-level (+N) scaling
# Port of eqlwiki's ext.itemLevelSlider (the site's Item Level slider; JS
# fetched 2026-07-21): +N stats are computed CLIENT-SIDE from the base
# stats — the wiki stores nothing per-level. This mirrors the JS exactly
# (Excel-style rounding, float op order) so our numbers match the site.
# In-game "+N" = the slider's full levels (its fractional steps are
# partial combine progress and never appear in item names).

_ILS_PRIMARY = {"AC", "HP", "MP", "END", "STR", "STA", "AGI", "DEX", "WIS",
                "INT", "CHA", "SV_MAGIC", "SV_FIRE", "SV_COLD", "SV_POISON",
                "SV_DISEASE"}
_ILS_VOID_QUALS = {"STR", "STA", "INT", "AGI", "DEX", "CHA", "WIS",
                   "SV_FIRE", "SV_COLD", "SV_POISON", "SV_MAGIC",
                   "SV_DISEASE"}
_ILS_ALIASES = {"DAMAGE": "DMG", "MANA": "MP", "ENDUR": "END",
                "SV MAGIC": "SV_MAGIC", "SV FIRE": "SV_FIRE",
                "SV COLD": "SV_COLD", "SV POISON": "SV_POISON",
                "SV DISEASE": "SV_DISEASE", "MAGIC": "SV_MAGIC",
                "FIRE": "SV_FIRE", "COLD": "SV_COLD", "POISON": "SV_POISON",
                "DISEASE": "SV_DISEASE", "HP REGEN": "HP_REGEN",
                "WEIGHT": "WT"}
_ILS_SCALABLE = ("HP REGEN", "SV DISEASE", "SV POISON", "SV MAGIC",
                 "SV COLD", "SV FIRE", "DAMAGE", "DMG", "AC", "HP", "MP",
                 "MANA", "ENDUR", "END", "STR", "STA", "AGI", "DEX", "WIS",
                 "INT", "CHA", "MAGIC", "FIRE", "COLD", "POISON", "DISEASE",
                 "HASTE", "WEIGHT", "WT")
_ILS_STAT_RE = re.compile(
    r"(\b(?:" + "|".join(re.escape(s) for s in
                         sorted(_ILS_SCALABLE, key=len, reverse=True))
    + r")\b)(:\s*)([+\-]?)(\d+(?:\.\d+)?)(\s*%?)", re.I)
# CASE-INSENSITIVE deliberately. eqlwiki writes resist lines both
# ways -- "SV Cold: +5" on one page, "SV COLD: +3" on another -- and
# matching only the upper form dropped the mixed-case ones SILENTLY.
# A pair of boots then compared as though it had no cold resist at
# all, which is invisible: the stat is not zero, it is absent, so
# nothing looks wrong. Consumers upper-case the captured name.


def item_rank(name: str) -> int:
    """'Raw-Hide Cloak +4' -> 4; unranked -> 0."""
    m = re.search(r"[+](\d+)\s*$", name or "")
    return int(m.group(1)) if m else 0


def _ils_round(value: float, digits: int = 0) -> float:
    """Excel ROUND (half away from zero) — mirrors the JS excelRound."""
    factor = 10.0 ** digits
    scaled = value * factor
    if value >= 0:
        return math.floor(scaled + 0.5) / factor
    return math.ceil(scaled - 0.5) / factor


def _ils_round_up(value: float, digits: int = 0) -> float:
    """Excel ROUNDUP (away from zero) — mirrors the JS excelRoundUp."""
    factor = 10.0 ** digits
    scaled = value * factor
    if value >= 0:
        return math.ceil(scaled) / factor
    return math.floor(scaled) / factor


def _ils_scale(key: str, base: float, n: int) -> float:
    """One stat's value at item level n. Primary stats: +1/level while the
    base is <=10, else ~+10% of base per level (penalties shrink toward 0);
    DMG: +floor(base*n/10); regen/haste: +1/level; weight shrinks ~9% per
    level on the slider's log curve."""
    if key in _ILS_PRIMARY:
        if base == 0:
            return 0
        if 0 < base <= 10:
            return base + n
        if base > 10:
            return math.floor(base + _ils_round(base * n / 10.0, 0))
        return min(0, base + n)
    if key == "DMG":
        return base if base <= 0 else base + math.floor(base * n / 10.0)
    if key in ("HP_REGEN", "HASTE"):
        return base + n if base > 0 else base
    if key == "WT":
        if n <= 0 or base <= 0.1:
            return base
        total = 2.0 ** n
        raw = base * (1 + (-0.09 * (math.log(total) / math.log(2.0))))
        return max(0.0, _ils_round_up(raw, 1))
    return base


def scale_item_line(line: str, rank: int) -> str:
    """Rewrite a compact BASE-stat item line to its values at +rank, per
    the wiki slider's formula; appends the emergent "SV VOID: +N" line
    when the item carries 2+ qualifier stats. Apply only to base (+0)
    lines — scaling an already-scaled line compounds. rank<=0 = as-is."""
    if not line or rank <= 0:
        return line
    # Player-supplied numbers are read off the item AT its current rank,
    # so they are already scaled. The old rule was "callers must not
    # re-scale"; making the line say so enforces it instead of relying on
    # every call site remembering.
    if "PRE-SCALED" in line:
        return line
    quals = set()

    def _sub(m):
        name, colon, sign, num, pct = m.groups()
        key = _ILS_ALIASES.get(name.upper(), name.upper().replace(" ", "_"))
        base = float(num) * (-1.0 if sign == "-" else 1.0)
        if key in _ILS_VOID_QUALS:
            quals.add(key)
        val = _ils_scale(key, base, rank)
        if key == "WT":
            txt = f"{val:.1f}"
        elif abs(val - round(val)) < 1e-7:
            txt = str(int(round(val)))
        else:
            txt = f"{val:.3f}".rstrip("0").rstrip(".")
        if val > 0 and sign == "+":
            txt = "+" + txt
        return f"{name}{colon}{txt}{pct}"

    out = _ILS_STAT_RE.sub(_sub, line)
    if len(quals) >= 2:
        out += f"; SV VOID: +{rank}"
    return out


def weapon_indices(dmg: float, delay: float,
                   level) -> Optional[dict]:
    """Relative white-DPS indices for 1H weapon comparisons (model per
    xaziaver/eql-weapon-inflection-analyzer, MIT, stated wiki-verified
    June 2026 — simplified to inputs we actually know): the main-hand
    DAMAGE BONUS is a FLAT, delay-independent add (floor((level-25)/3)
    from L28), so fast MH weapons carry it more often; the off-hand gets
    NO bonus and only swings ~(level+skill)/400 of the time (skill
    approximated at its cap, 5*level+5). INDEX, not absolute DPS — real
    rolls depend on ATK/AC we cannot see. Procs are NOT included."""
    if not dmg or not delay or not level:
        return None
    db = (level - 25) // 3 if level >= 28 else 0
    delay_s = max(0.5, delay / 10.0)
    roll = dmg * 1.3  # average damage-roll multiplier (mean d20 of 13)
    p_oh = min(1.0, (level + 5 * level + 5) / 400.0)
    return {"mh": round((roll + db) / delay_s, 1),
            "oh": round(roll / delay_s * p_oh, 1), "db": db}


def item_stat_vector(line: str) -> dict:
    """Canonical stat -> value parsed from a (scaled) compact line, for
    deterministic comparisons. Includes DELAY (lower is better) and the
    synthesized SV_VOID; skips WT (not a power stat). {} = no stats."""
    out: dict = {}
    for m in _ILS_STAT_RE.finditer(line or ""):
        name, _, sign, num, _ = m.groups()
        key = _ILS_ALIASES.get(name.upper(), name.upper().replace(" ", "_"))
        if key == "WT":
            continue
        out.setdefault(key, float(num) * (-1.0 if sign == "-" else 1.0))
    m = re.search(r"Atk Delay:\s*(\d+(?:\.\d+)?)", line or "")
    if m:
        out["DELAY"] = float(m.group(1))
    m = re.search(r"SV VOID:\s*[+]?(\d+)", line or "", re.I)
    if m:
        out["SV_VOID"] = float(m.group(1))
    return out


def _compact_item(text: str) -> Optional[str]:
    """One advisor-ready line from an item wiki page, or None when the page
    is not an equippable item (no Slot/DMG lines)."""
    head, _, tail = text.partition("Drops From")
    stats = []
    raw = []
    for line in head.splitlines():
        s = line.strip()
        # the wiki's focus_effect template param renders glued onto the
        # LAST stats line ("Race: ALLFocus Effect: X") — split it off so
        # the Race skip below can't swallow it
        i = s.find("Focus Effect:")
        if i > 0:
            raw.extend((s[:i].strip(), s[i:].strip()))
        else:
            raw.append(s)
    for s in raw:
        if not s:
            continue
        if s.startswith("Race:"):
            # classic-era race lists predate EQL races (no IKS on 1999
            # items) and EQL does not enforce them — omit to avoid false
            # "not equippable" advice
            continue
        if (s.startswith(ITEM_STAT_PREFIXES) or s.startswith("Class:")
                or any(t in s for t in ITEM_STAT_TOKENS)):
            stats.append(s)
    if not any(s.startswith(("Slot:", "DMG:", "Skill:")) for s in stats):
        return None
    drops = []
    if tail:
        section = tail.split("Sold by")[0]
        zone = None
        for para in re.split(r"\n\s*\n", section):
            lines = [x.strip() for x in para.strip().splitlines() if x.strip()]
            if not lines:
                continue
            if len(lines) == 1 and _canonical(lines[0]):
                zone = lines[0]
            elif zone:
                drops.append(f"{zone} ({lines[0]})")
                zone = None
            if len(drops) >= 3:
                break
    sold = "vendor-buyable" if "sold by merchants" in text else ""
    parts = ["; ".join(stats)]
    if drops:
        parts.append("drops: " + ", ".join(drops))
    if sold:
        parts.append(sold)
    return " | ".join(parts)


async def item_line(name: str) -> Optional[str]:
    """Compact stat line for an item (wiki, cached 24h). None = no page or
    not equipment."""
    base = _strip_upgrade(name)
    # A player CORRECTION outranks the page. _supplied_line below is the
    # gap-filler and stays a last resort; this is the other case -- the
    # wiki has a page and it is wrong for this game. Checked before the
    # cache so a correction takes effect immediately rather than after the
    # 24h item_line2 entry expires.
    try:
        from backend import item_facts
        ov = item_facts.override_for(0, base)
    except Exception:
        ov = None
    if ov:
        return ov[0]
    key = base.lower()
    cached = wiki_page_cache.get("item_line2", key)
    if cached is not None:
        return cached or _supplied_line(base)
    page = await get_mcp_client().wiki_page(base, max_characters=4000)
    if page is None:
        # exact title missed — fuzzy-resolve (punctuation/case drift
        # between export names and page titles)
        try:
            alt = await _resolve_item_title(base)
        except Exception:
            alt = None
        if alt and alt.lower() != base.lower():
            page = await get_mcp_client().wiki_page(alt, max_characters=4000)
    if page is None:
        # no page OR wiki down — indistinguishable here. Serve the last
        # good parse when one exists (stale beats nothing), else cache
        # the miss briefly (1h) rather than re-fetching 40+ consumables
        # per consult
        stale = wiki_page_cache.get_stale("item_line2", key)
        if stale:
            return stale
        wiki_page_cache.set("", 3600, "item_line2", key)
        return _supplied_line(base)
    line = _compact_item(page.get("text", ""))
    wiki_page_cache.set(line or "", WIKI_TTL, "item_line2", key)
    return line or _supplied_line(base)


def _supplied_line(base: str) -> Optional[str]:
    """Stats a PLAYER typed in, used ONLY where the wiki has nothing.

    This is a LAST resort, not a first one. It briefly ran first, to skip
    a network round trip, and that was backwards: the wiki carries BASE
    (+0) values that scale correctly to any owned +N, plus the class list,
    the proc and the drop source. A hand-entered figure is pinned to the
    one rank it was read at and cannot scale -- so preferring it would
    have silently overridden better data forever, and eqlwiki is actively
    filling in the launch item block (Burnt Sheer Blade gained a page
    within two days of being unfindable).
    """
    try:
        from backend import item_facts
        rec = item_facts.stats_for(0, base)
    except Exception:
        return None
    return rec[0] if rec else None


def _edit_distance(a: str, b: str) -> int:
    """Levenshtein (iterative DP) — no dependency."""
    if a == b:
        return 0
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[-1] + 1,
                           prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


async def _resolve_item_title(name: str) -> Optional[str]:
    """Fuzzy name -> wiki page title: MediaWiki search, then the hit with
    the best normalized edit distance (small rank penalty breaks ties).
    Resolves export/log names that drift from page titles. Pattern from
    DavisChappins/eql-tooltip (MIT)."""
    from backend.wiki_http import search_pages
    results = await search_pages(name, limit=8)
    if not results:
        # the wiki search is strict ("Barons" never matches "Baron's") —
        # retry with per-word trailing-s stripped; the edit-distance pick
        # against the ORIGINAL name still guards the match
        loosened = re.sub(r"(\w)s\b", r"\1", name)
        if loosened != name:
            results = await search_pages(loosened, limit=8)
    low = name.lower()
    best, best_score = None, 0.35  # above this = probably a different item
    for i, r in enumerate(results):
        title = r.get("title") or ""
        d = _edit_distance(low, title.lower())
        score = d / max(len(low), len(title), 1) + i * 0.02
        if score < best_score:
            best, best_score = title, score
    return best


# Acquisition sections exist ONLY in rendered HTML — the {{Itempage}}
# template emits them, so wikitext lacks them. Extraction approach from
# DavisChappins/eql-tooltip (MIT).
ACQ_SECTIONS = (("Drops_From", "Drops From"), ("Sold_by", "Sold by"),
                ("Related_quests", "Related quests"),
                ("Player_crafted", "Player crafted"),
                ("Tradeskill_recipes", "Tradeskill recipes"))
_ACQ_BOILER = ("not dropped by mobs", "cannot be purchased",
               "no related quests", "not crafted by players",
               "not used in player tradeskills")


def _acq_section(html: str, sec_id: str) -> Optional[str]:
    """Inner HTML between <h2 id=sec_id> (possibly inside the modern
    mw-heading wrapper div) and the next heading."""
    m = re.search(rf'<h2[^>]*id="{sec_id}"', html)
    if not m:
        return None
    tail = html[m.end():]
    body_start = tail.find("</h2>")
    if body_start < 0:
        return None
    tail = tail[body_start + 5:]
    nxt = re.search(r'<h2[\s>]|<div class="mw-heading', tail)
    return tail[:nxt.start()] if nxt else tail


def _acq_lines(section_html: str) -> list:
    """<p> = zone sub-heading, <li> = mob/vendor row; tags stripped; the
    template's empty-section filler is tagged kind=note."""
    out = []
    for m in re.finditer(r"<(p|li)[^>]*>(.*?)</\1>", section_html, re.S):
        txt = re.sub(r"<[^>]+>", "", m.group(2))
        txt = re.sub(r"\s+", " ", txt).strip()
        if not txt:
            continue
        boiler = any(b in txt.lower() for b in _ACQ_BOILER)
        out.append({"text": txt,
                    "kind": ("note" if boiler else
                             "zone" if m.group(1) == "p" else "entry")})
        if len(out) >= 14:
            break
    return out


async def item_acquisition(name: str) -> dict:
    """Where an item comes from (drops / vendors / quests / crafting),
    parsed from the RENDERED item page — feeds the gear-tab hover cards.
    Cached 24h; misses 1h; stale served when a refresh fails."""
    base = _strip_upgrade(name)
    key = base.lower()
    cached = wiki_page_cache.get("item_acq1", key)
    if cached is not None:
        return cached
    from backend.wiki_http import fetch_page_html
    html = await fetch_page_html(base)
    if html is None:
        stale = wiki_page_cache.get_stale("item_acq1", key)
        if stale is not None:
            return stale
        miss = {"item": base, "sections": [], "available": False}
        wiki_page_cache.set(miss, 3600, "item_acq1", key)
        return miss
    sections = []
    for sec_id, label in ACQ_SECTIONS:
        body = _acq_section(html, sec_id)
        if not body:
            continue
        rows = _acq_lines(body)
        # keep sections with real content; solitary boilerplate is noise
        if rows and not all(r["kind"] == "note" for r in rows):
            sections.append({"label": label, "lines": rows})
    out = {"item": base, "sections": sections, "available": bool(sections)}
    wiki_page_cache.set(out, WIKI_TTL, "item_acq1", key)
    return out


# ------------------------------------------------------------ class guides
from backend.paths import bundle_path

CLASS_GUIDES_DIR = bundle_path("class_guides")


# reference files loaded ONLY for the main advisor consult (the gear
# consult keeps its prompt lean — race/stance/ritual data rarely moves
# an equipment decision)
REF_GUIDES = ("races", "stances_invocations", "rituals")


def guide_budget() -> int:
    """Per-guide character budget, scaled to the context we actually have.

    3200 was chosen to protect a model loaded at 8k. That is the floor,
    not the norm: a local server reports its LOADED window and 32k is
    common, where holding guides to 3200 discards most of what we could
    say. Cloud providers stay at the floor deliberately -- their context
    is ample but their tokens are billed, and nobody asked us to spend
    four times as much per consult.

    Scales with the window rather than jumping, and stops at 9000: past
    that the guides would crowd out the gear and spell context they are
    supposed to inform, and prompt size costs real latency (a 10k-token
    prompt measured ~3.9s locally).
    """
    try:
        from backend.llm_runtime import context_limit
        info = context_limit()
    except Exception:
        return 3200
    if info["source"] == "default":
        return 3200
    return max(3200, min(9000, int(info["limit"] * 0.18)))


def class_guide_text(classes, max_chars_per: int | None = None,
                     include_refs: bool = False) -> str:
    """Curated .md guides (community wisdom, maintained by hand — see
    class_guides/README.md). general.md (cross-class mechanics + meta)
    loads FIRST for every trio, then reference files when include_refs,
    then one file per full class name (lowercase, spaces as
    underscores). Empty string when none exist."""
    if max_chars_per is None:
        max_chars_per = guide_budget()
    names = (["general"] + (list(REF_GUIDES) if include_refs else [])
             + [str(c).strip().lower().replace(" ", "_")
                for c in classes or []])
    seen: set = set()
    parts = []
    for nm in names:
        if not nm or nm in seen:
            continue
        seen.add(nm)
        fn = CLASS_GUIDES_DIR / (nm + ".md")
        try:
            txt = fn.read_text(encoding="utf-8").strip()
        except OSError:
            continue
        if txt:
            # Why a cap at all, since it used to be a bare 2600 with no
            # rationale: guides are the LARGEST single slice of the
            # advisor prompt (13k chars of ~25k), and _lmstudio_budget in
            # advisor.py subtracts the prompt from the model's LOADED
            # context to size max_tokens. On a local model loaded at 8k
            # the prompt is already tight, so this bounds it. 3200 fits
            # the two densest guides after trimming rather than silently
            # dropping their back half -- which is where the NEWEST
            # material lives, since new notes get appended.
            cap = 3400 if nm in ("general",) + REF_GUIDES else max_chars_per
            title = ("General (all trios)" if nm == "general"
                     else nm.replace("_", " ").title())
            parts.append(f"### {title}\n{txt[:cap]}")
    return "\n\n".join(parts)


def _trio_usable(line: str, classes: list) -> Optional[bool]:
    """EQL rule: an item is equippable when ANY ONE of the trio's classes
    is on its Class line (or Class: ALL). None = no class data on the item.

    THREE forms appear on the wiki and all three must parse. The capture
    used to be [A-Z ], which cannot cross the lowercase "except" in
    "ALL except NEC WIZ MAG ENC" -- so that form matched NOTHING and
    returned None. A None strips the [USABLE] tag in build_gear_context,
    and the model then does the class math itself: it read the missing
    tag on an "except ... WIZ" item as proof a Shadow Knight/Wizard
    player could not use it, when only ONE of the two was excluded, and
    advised handing it to the pet. A quarter of a real inventory parsed
    this way. Do NOT tighten the capture back to [A-Z ]."""
    from backend.log_system.parser import CLASS_ABBREV
    m = re.search(r"Class: ([^;|\n]+)", line)
    if not m:
        return None
    raw = m.group(1).strip()
    ex = re.match(r"ALL\s+except\s+(.+)$", raw, re.I)
    tokens = set(raw.split())
    if "ALL" in tokens and not ex:
        return True
    abbrs = {a for a, full in CLASS_ABBREV.items()
             if full.lower() in {c.strip().lower() for c in classes}}
    if not abbrs:
        return None  # classes unresolvable -- never claim NOT USABLE
    if ex:
        # usable when at least one of the trio is NOT on the exclusion list
        return bool(abbrs - set(ex.group(1).split()))
    return bool(tokens & abbrs)


async def build_gear_context(items: list, classes: Optional[list] = None,
                             max_items: int = 100,
                             level=None) -> dict:
    """Stat lines for every unique owned item that has an equipment page,
    annotated with deterministic trio eligibility so the LLM never does the
    class math itself. Returns {"lines": [...], "unknown": [names]} — first
    run mines the wiki (~0.5s/item), afterwards it's all cache."""
    seen: dict = {}
    for it in items:
        base = _strip_upgrade(it["name"])
        entry = seen.setdefault(base.lower(), {"name": it["name"],
                                               "where": set(),
                                               "ranks": set()})
        entry["where"].add(it["where"])
        entry["ranks"].add(item_rank(it["name"]))
        if it["where"] == "worn":
            entry["name"] = it["name"]  # prefer the worn (+N) display name
    lines, unknown = [], []
    for key, entry in list(seen.items())[:max_items]:
        line = await item_line(entry["name"])
        if line:
            where = "/".join(sorted(entry["where"]))
            rank = item_rank(entry["name"])
            line = scale_item_line(line, rank)  # stats AT the owned +N
            note = ""
            others = sorted(entry["ranks"] - {rank})
            if others:
                note = (f" [stats at +{rank}; other copies owned at "
                        + ", ".join(f"+{r}" for r in others) + "]")
            elif rank > 0:
                note = f" [stats at +{rank}]"
            tag = ""
            if classes:
                usable = _trio_usable(line, classes)
                if usable is True:
                    tag = " [USABLE]"
                elif usable is False:
                    tag = " [NOT USABLE by this trio]"
            # 1H weapons: deterministic MH/OH white-DPS indices so the
            # model never reasons from ratio alone (flat MH damage bonus
            # is delay-independent; OH swings part-time with no bonus)
            wm = re.search(r"DMG: (\d+)", line)
            dm = re.search(r"Atk Delay: (\d+)", line)
            if wm and dm and level and "Skill: 2H" not in line:
                wi = weapon_indices(int(wm.group(1)), int(dm.group(1)), level)
                if wi:
                    note += (f" [white-DPS index: MH {wi['mh']} / "
                             f"OH {wi['oh']}]")
            lines.append(f"{entry['name']} [{where}]{tag}{note} — {line}")
        else:
            # The prompt line below still lists EVERY wiki-less item, so the
            # model cannot invent numbers for any of them. `unknown` is the
            # ACTIONABLE subset -- what the user can do something about --
            # and a raw dump buries a wearable item under Bread Cakes,
            # Backpacks and Water Flasks. A "+N" rank is the deterministic
            # tell: only equipment merges to a rank, so every wiki-less
            # GEAR item carries one and no consumable does. Launch added a
            # whole item block the wiki has not documented, including
            # pieces the user is already wearing.
            if item_rank(entry["name"]) > 0:
                unknown.append(entry["name"])
            where = "/".join(sorted(entry["where"]))
            lines.append(f"{entry['name']} [{where}] — STATS UNKNOWN "
                         "(no wiki page; do not invent numbers for this item)")
    return {"lines": lines, "unknown": unknown}


# ------------------------------------------------------------------ hunting

# The community "Recommended Levels and ZEM List" table (raw WIKITEXT — the
# rendered page collapses empty cells). 2026-07 redesign: each row carries a
# zone Type (City/Dungeon/Open), an explicit level range, and per-level
# QUALITY circles: lightblue=efficient exp, gold=doable but inefficient,
# lightpink=not recommended, orangeRing=special purposes.
ZEM_RAW_URL = ("https://eqlwiki.com/index.php"
               "?title=Recommended_Levels_and_ZEM_List&action=raw")
IN_ERA_SECTIONS = {"Antonica", "Odus", "Faydwer", "Planes"}
IN_ERA_PLANES = {"Plane of Fear", "Plane of Hate", "Plane of Sky"}

_RE_ZEM_SECTION = re.compile(r"^=+\s*([^=]+?)\s*=+\s*$")
_RE_ZEM_ROW = re.compile(r"^\|\s*\[\[([^\]|]+)(?:\|[^\]]*)?\]\]\s*\|\|(.*)$")
_RE_ZEM_HEADER_COL = re.compile(r"^!.*?\|\s*(\d+)\s*$")
_RE_ZEM_RANGE = re.compile(r"(\d+)\s*-\s*(\d+)")
_TIER = (("lightblue", "efficient"), ("goldcircle", "ok"),
         ("lightpink", "poor"), ("orangering", "special"))


def _cell_tier(cell: str):
    low = cell.lower()
    for token, tier in _TIER:
        if token in low:
            return tier
    return None


def _parse_zem_wikitext(text: str) -> dict:
    zones: dict = {}
    section = None
    cols: list = []
    for line in text.splitlines():
        m = _RE_ZEM_SECTION.match(line)
        if m:
            section = m.group(1).strip()
            cols = []
            continue
        if section not in IN_ERA_SECTIONS:
            continue
        hm = _RE_ZEM_HEADER_COL.match(line)
        if hm:
            cols.append(int(hm.group(1)))
            continue
        rm = _RE_ZEM_ROW.match(line)
        if not rm or not cols:
            continue
        zone = rm.group(1).strip()  # link TARGET = our chart/graph key
        if section == "Planes" and zone not in IN_ERA_PLANES:
            continue
        cells = [c.strip() for c in rm.group(2).split("||")]
        # The Type cell is OPTIONAL in practice: 61 of 119 rows omit it,
        # including the whole Faydark block (Crushbone, Kaladim, Felwithe,
        # Butcherblock, Unrest, Kedge Keep, Steamfont, Mistmoore). Assigning
        # by position therefore put a LEVEL RANGE in `type`, left lo/hi
        # None, and shifted every quality circle one column left -- so
        # Crushbone read as efficient at level 1 when its row says poor,
        # and the City exclusion silently stopped applying to half the
        # table. Detect which shape the row is instead of trusting order.
        first = cells[0] if cells else ""
        if _RE_ZEM_RANGE.search(first):
            ztype, rest = "", cells          # no Type cell: range leads
        else:
            ztype, rest = first.title(), cells[1:]
        lo = hi = None
        if rest and (rng := _RE_ZEM_RANGE.search(rest[0])):
            lo, hi = int(rng.group(1)), int(rng.group(2))
        tiers = {}
        for lvl, cell in zip(cols, rest[1:]):
            t = _cell_tier(cell)
            if t:
                tiers[lvl] = t
        if lo is None and not tiers:
            continue  # row not filled in yet
        zones[zone] = {"type": ztype, "lo": lo, "hi": hi, "tiers": tiers}
    return zones


# Spell pages carry a where_to_obtain table whose SOURCE keeps zone, vendor,
# location and coords as separate parameters -- the rendered page flattens
# them into prose. Row shape:
#   {{SpellWhereRowB | [[Ak'Anon]] | [[Clockwork Merchant]] | Library | (1104,-992) }}
_SPELL_WHERE_ROW = re.compile(r"\{\{SpellWhereRow[B]?\s*\|(?P<body>[^}]*)\}\}",
                              re.IGNORECASE)


_LINK_PIPED = re.compile(r'\[\[([^\]|]+)\|([^\]]+)\]\]')
_LINK_PLAIN = re.compile(r'\[\[([^\]]+)\]\]')


def _delink(s: str) -> str:
    """[[Erudin|Erudin Palace]] -> Erudin Palace; [[Ak'Anon]] -> Ak'Anon.

    Function replacements, not backslash-group strings: the escaping is
    easy to get wrong and fails SILENTLY, substituting a control character
    instead of the captured text.
    """
    s = _LINK_PIPED.sub(lambda m: m.group(2), s)
    s = _LINK_PLAIN.sub(lambda m: m.group(1), s)
    return s.replace(chr(39) * 3, '').strip()

async def spell_vendors(spell: str) -> list:
    """Where to BUY a spell: [{zone, vendor, where, loc}], empty if unknown.

    The advisor already says a spell is a "vendor purchase" and then leaves
    the player to find it, which is half an answer."""
    key = spell.strip().lower()
    cached = wiki_page_cache.get("spell_vendors", key)
    if cached is not None:
        return cached
    rows: list = []
    try:
        from backend.wiki_http import fetch_page_wikitext
        text = await fetch_page_wikitext(spell.strip())
        for m in _SPELL_WHERE_ROW.finditer(text or ""):
            # collapse [[A|B]] to [[B]] FIRST: the pipe inside a wiki
            # link is not a field separator
            body = _LINK_PIPED.sub(lambda mm: '[[' + mm.group(2) + ']]',
                                   m.group("body"))
            parts = [p.strip() for p in body.split("|")]
            if not parts or not parts[0]:
                continue
            zone = _delink(parts[0])
            vendor = _delink(parts[1]) if len(parts) > 1 else ""
            where = _delink(parts[2]) if len(parts) > 2 else ""
            loc = _delink(parts[3]) if len(parts) > 3 else ""
            if zone and vendor:
                rows.append({"zone": zone, "vendor": vendor,
                             "where": where, "loc": loc})
    except Exception:
        logger.exception("spell_vendors(%s) failed", spell)
    wiki_page_cache.set(rows, WIKI_TTL, "spell_vendors", key)
    return rows

_VENDORED_ZEM: dict | None = None


def _vendored_zem() -> dict:
    """The snapshot shipped beside the code (backend/zem_levels.wiki).

    Same raw wikitext the live URL serves, so the tested parser reads it
    unchanged -- no second format, nothing to keep in step. Refresh it with
    scripts/refresh_zem.py.
    """
    global _VENDORED_ZEM
    if _VENDORED_ZEM is None:
        try:
            _VENDORED_ZEM = _parse_zem_wikitext(
                bundle_path("backend", "zem_levels.wiki").read_text(
                    encoding="utf-8"))
        except Exception:
            logger.exception("vendored ZEM snapshot unreadable")
            _VENDORED_ZEM = {}
    return _VENDORED_ZEM


async def zem_zone_levels() -> dict:
    """In-era zone -> {type, lo, hi, tiers}. Live wiki, else the snapshot.

    The fallback matters more than it looks. _gate_locations() reads an
    EMPTY table as "no table" and passes the model's zone picks through
    UNGATED, so a failed fetch silently switches the location verifier off
    -- and a packaged .exe on a machine with no network hit that on every
    single consult. Falling back to the snapshot keeps the table
    authoritative for WHERE even offline.
    """
    cached = wiki_page_cache.get("zem_levels_wt2")
    if cached is not None:
        return cached
    import aiohttp
    text = ""
    try:
        async with aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=20)) as s:
            async with s.get(ZEM_RAW_URL) as r:
                r.raise_for_status()
                text = await r.text()
    except Exception:
        logger.info("ZEM table fetch failed; using the vendored snapshot")
    zones = _parse_zem_wikitext(text) if text else {}
    if not zones:
        # deliberately NOT cached: caching the snapshot under the live key
        # would suppress the next real fetch for a full day
        return _vendored_zem()
    wiki_page_cache.set(zones, WIKI_TTL, "zem_levels_wt2")
    return zones


def _zone_band(z: dict) -> tuple:
    """(lo, hi) merging the explicit range with the marked tiers — the
    sheet is mid-edit and the two sometimes disagree (Everfrost: range
    1-12 but efficient circles at 40-45)."""
    marked = [l for l, t in z["tiers"].items() if t in ("efficient", "ok")]
    pool = [x for x in (z["lo"], z["hi"], *marked) if x is not None]
    if not pool:
        return None, None
    return min(pool), max(pool)


# Zones revamped by PATCH NOTES newer than the community sheet — the
# override wins on the level BAND (the sheet's per-level quality circles
# stay authoritative where they exist). Prune entries when the sheet
# catches up.
PATCH_BAND_OVERRIDES = {
    "crushbone": (4, 22, "revamped in the 2026-07-14 patch: now levels "
                         "4-22 with new loot and enemies"),
    "splitpaw lair": (25, 42, "revamped in the 2026-07-14 patch: 25-28 at "
                              "the entrance ramping to 40-42, with "
                              "boosted rare-spawn and drop rates"),
}


async def hunting_candidates(level: int) -> list:
    """Non-city in-era zones fitting the level. Quality comes from the
    community circles: efficient > ok; range-only rows count as ok. Cities
    are excluded by their Type column UNLESS the row carries efficient
    marks (the sheet is mid-edit and some hunting zones are mistyped).
    PATCH_BAND_OVERRIDES supersede the sheet's level bands for zones the
    devs revamped after the sheet's last edit."""
    zones = await zem_zone_levels()
    col = max(1, 5 * (level // 5))
    out = []
    for zone, z in zones.items():
        tiers = z["tiers"]
        has_eff = "efficient" in tiers.values()
        if z["type"] == "City" and not has_eff:
            continue
        lo, hi = _zone_band(z)
        note = None
        ov = PATCH_BAND_OVERRIDES.get(zone.lower())
        if ov:
            lo, hi, note = ov
            # the sheet's per-level circles predate the revamp — drop
            # marks outside the patched band so stale ratings can't
            # resurface the old range
            tiers = {l: t for l, t in tiers.items() if lo <= l <= (hi or lo)}
            has_eff = "efficient" in tiers.values()
        if lo is None:
            continue
        tier_here = tiers.get(col) or tiers.get(col + 5)
        in_range = lo <= level <= (hi or lo)
        stretch = level < lo <= level + 5
        if not (tier_here in ("efficient", "ok") or in_range or stretch):
            continue
        quality = (tier_here if tier_here in ("efficient", "ok")
                   else ("ok" if in_range else "stretch"))
        marked = sorted(l for l, t in tiers.items() if t in ("efficient", "ok"))
        out.append({
            "zone": zone,
            "band": f"{lo}-{hi or lo}",
            "at_level": quality != "stretch",
            "quality": quality,
            "note": note,
            "type": z["type"] or "",
            "marks": [m for m in marked if m in (col, col + 5)],
            "levels": marked or [l for l in range(lo, (hi or lo) + 1)
                                 if l % 5 == 0 or l == lo],
        })
    order = {"efficient": 0, "ok": 1, "stretch": 2}
    # Dungeons rank above open zones AT EQUAL QUALITY -- a tiebreak, never
    # a filter. Filtering to Type == "Dungeon" is tempting and wrong: 15
    # in-era rows carry NO Type at all (the sheet omits the cell), and
    # Crushbone is one of them, so a hard dungeon filter drops the single
    # zone most often wanted at this level. Quality still leads, because a
    # dungeon you cannot efficiently kill in is not a better answer.
    def _rank(z):
        mid = (int(z["band"].split("-")[0]) + int(z["band"].split("-")[1])) // 2
        return (order[z["quality"]],
                0 if z.get("type") == "Dungeon" else 1,
                abs(mid - level))
    out.sort(key=_rank)
    return out
