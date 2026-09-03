"""Direct reader for the eqlbuilds.com dataset snapshot.

The MCP server clone ships a CI-refreshed snapshot of eqlbuilds.com (per-
class spell lists with EXACT unlock levels, AA ranks/costs, skills) under
dist/data/eqlbuilds. Reading the JSON directly beats per-lookup stdio calls:
deterministic, instant, and it works even where Node cannot run. Everything
here is optional — no clone means every function returns None/{} and the
callers keep their MCP/wiki fallback paths.
"""
import json
import logging
import re
from pathlib import Path
from typing import Optional

from backend.config import settings
from backend.paths import bundle_path

logger = logging.getLogger(__name__)

_cache: dict = {"file": None, "mtime": None, "data": None, "index": None}


def _snapshot_file() -> Optional[Path]:
    # bundled copy first (self-contained exe / no MCP clone needed);
    # read-only, so it rides inside the bundle rather than the state dir
    local = bundle_path("data", "eqlbuilds", "classes.json")
    if local.exists():
        return local
    if not settings.mcp_server_dir:
        return None
    for sub in ("dist", "src"):
        p = Path(settings.mcp_server_dir) / sub / "data" / "eqlbuilds" / "classes.json"
        if p.exists():
            return p
    return None


def _class_key(name: str) -> str:
    """'Shadow Knight' -> 'shadowKnight' (the snapshot's key style)."""
    words = (name or "").strip().lower().split()
    return words[0] + "".join(w.title() for w in words[1:]) if words else ""


def _pretty(key: str) -> str:
    """'shadowKnight' -> 'Shadow Knight'."""
    spaced = re.sub("(?<!^)([A-Z])", lambda m: " " + m.group(1), key)
    return spaced.title()


def classes_data() -> Optional[dict]:
    f = _snapshot_file()
    if f is None:
        return None
    try:
        mtime = f.stat().st_mtime
        if _cache["file"] != str(f) or _cache["mtime"] != mtime:
            _cache.update(file=str(f), mtime=mtime, index=None,
                          data=json.loads(f.read_text(encoding="utf-8")))
            logger.info("eqlbuilds snapshot loaded: %s", f)
        return _cache["data"]
    except Exception:
        logger.exception("eqlbuilds snapshot unreadable")
        return None


def available() -> bool:
    return classes_data() is not None


def class_spells(cls_name: str) -> Optional[list]:
    d = classes_data()
    if not d:
        return None
    c = d.get(_class_key(cls_name))
    return c.get("spellList") if c else None


def class_aas(cls_name: str) -> Optional[list]:
    d = classes_data()
    if not d:
        return None
    c = d.get(_class_key(cls_name))
    return c.get("alternateAbilityList") if c else None


def _index() -> dict:
    """spell name (lower) -> {'levels': {Pretty Class: level}, 'entry': first}"""
    d = classes_data()
    if not d:
        return {}
    if _cache["index"] is None:
        idx: dict = {}
        for key, c in d.items():
            pretty = _pretty(key)
            for s in c.get("spellList") or []:
                slot = idx.setdefault(str(s.get("name", "")).lower(),
                                      {"levels": {}, "entry": s})
                slot["levels"][pretty] = s.get("level")
        _cache["index"] = idx
    return _cache["index"]


def spell_levels(name: str) -> dict:
    """{Pretty Class: unlock level} for a spell; {} when unknown/no snapshot."""
    hit = _index().get((name or "").strip().lower())
    return dict(hit["levels"]) if hit else {}


def spell_entry(name: str) -> Optional[dict]:
    """Full snapshot record with classes attached — a spell_record substitute
    when the MCP server cannot answer."""
    hit = _index().get((name or "").strip().lower())
    if not hit:
        return None
    return {**hit["entry"],
            "classes": sorted(hit["levels"]),
            "levels": dict(hit["levels"])}


# Effect ids eqlbuilds leaves unnamed ("Effect 457") whose meaning is
# established by EVIDENCE, not guesswork. 457: carried by Leech, whose
# in-game tooltip reads "100% of the life-force taken is used to heal
# your wounds", and carried by NONE of the plain DoTs checked (Poison
# Bolt, Disease Cloud, Clinging Darkness) — so it is the damage-returned-
# as-healing conversion, in TENTHS of a percent (base 1000 = 100%).
# Verified 2026-07-30 from a player screenshot of the client tooltip.
_EFFECT_NOTES = {457: ("life drained returned as healing", 0.1, "%")}

# self-heal-on-damage target types, per spell_file.py's documented set
_LIFETAP_TARGETS = {13, 20}


def effect_summary(entry: dict, cap: int = 110) -> str:
    """Compact effect prose for a spell the snapshot describes with an
    EMPTY description (26 of 1223 spells, Leech among them). The client
    composes its tooltip from exactly this data, so rendering it keeps the
    advisor grounded instead of filling the hole from model memory — which
    is what put an invented 'larger lifetap' Leech in a real consult, and
    then had a checker correctly call it unsupported.

    Spacer slots (id-10 charisma placeholders, the convention documented
    in game_data._primary_effect) are skipped."""
    effects = entry.get("effects") or []
    ticks = entry.get("durationTicks") or 0
    per_tick = " per tick" if ticks else ""
    bits = []
    for e in effects:
        eid, base = e.get("effectId"), e.get("baseValue") or 0
        if eid == 10 and not base:
            continue  # spacer
        if not base:
            continue
        note = _EFFECT_NOTES.get(eid)
        if note:
            label, scale, unit = note
            bits.append(f"{base * scale:g}{unit} {label}")
        elif eid == 0:
            bits.append(f"{abs(base)} damage{per_tick}" if base < 0
                        else f"heals {base}{per_tick}")
        else:
            bits.append(f"{e.get('name') or f'effect {eid}'} {base}")
    if ticks:
        bits.append(f"over {ticks} ticks ({entry.get('duration') or ''})".strip())
    if entry.get("targetTypeId") in _LIFETAP_TARGETS:
        bits.append("lifetap (heals you)")
    return "; ".join(bits)[:cap]


def class_spell_lines(cls_name: str, lo: int, hi: int) -> Optional[list]:
    """Compact per-level spell lines for the advisor prompt window, straight
    from the snapshot (exact levels). None = no snapshot / unknown class."""
    spells = class_spells(cls_name)
    if spells is None:
        return None
    out = []
    for s in sorted(spells, key=lambda x: (x.get("level") or 0, x.get("name") or "")):
        lv = s.get("level")
        if lv is None or not (lo <= lv <= hi):
            continue
        desc = (s.get("resolvedDescription") or s.get("description") or "")
        # no description in the snapshot: synthesize one from the effect
        # data rather than leaving the model a bare name and mana cost
        desc = " ".join(desc.split())[:110] or effect_summary(s)
        mana = s.get("manaCost")
        out.append(f"L{lv} {s.get('name')}"
                   + (f" [mana {mana}]" if mana else "")
                   + (f" {desc}" if desc else ""))
    return out


def class_aa_lines(classes: list) -> Optional[list]:
    """AA lines (name, ranks, per-rank costs, description) for a class trio,
    deduped across the trio's lists. None = no snapshot."""
    if not available():
        return None
    seen, out = set(), []
    for cls in classes:
        for a in class_aas(cls) or []:
            name = a.get("name")
            if not name or name in seen:
                continue
            seen.add(name)
            desc = " ".join((a.get("description") or "").split())[:150]
            cat = a.get("category") or "class"
            cost = a.get("costLabel") or "?"
            out.append(f"[{cat}] {name} (ranks {a.get('maxRank', '?')}, "
                       f"cost {cost}) {desc}")
    return out


def spell_id(name: str) -> Optional[int]:
    """eqlbuilds spell id — the SAME id space the game's LO*.ini spell
    loadouts use (verified against live sets)."""
    hit = _index().get((name or "").strip().lower())
    return hit["entry"].get("id") if hit else None


def spell_name(sid: int) -> Optional[str]:
    d = classes_data()
    if not d:
        return None
    if _cache.get("id_index") is None:
        _cache["id_index"] = {s["id"]: s["name"]
                              for c in d.values()
                              for s in c.get("spellList") or []}
    return _cache["id_index"].get(sid)


def spell_duration_ticks(name: str) -> Optional[int]:
    """durationTicks from the snapshot. In EQL, a BENEFICIAL buff with 0
    ticks is permanent-until-death (Instrument of Nife, Greater Wolf Form);
    timed buffs carry real ticks (Spirit of Wolf = 360)."""
    e = spell_entry(name)
    return None if e is None else (e.get("durationTicks") or 0)


def has_skill(cls_name: str, skill: str) -> Optional[bool]:
    """Does this class train a skill? None when we have no data at all.

    None and False are NOT the same here: a missing dataset must not read
    as "this class cannot dual wield", which would silently strip valid
    off-hand advice from every install without the builds clone.
    """
    d = classes_data()
    if not d:
        return None
    rec = d.get(_class_key(cls_name))
    if not rec:
        return None
    want = skill.strip().lower()
    return any((s.get("name") or "").strip().lower() == want
               for s in (rec.get("skillList") or []))


def any_has_skill(classes: list, skill: str) -> Optional[bool]:
    """True if ANY class in the trio trains it; None if nothing is known."""
    seen = [has_skill(c, skill) for c in (classes or []) if c]
    if not seen or all(v is None for v in seen):
        return None
    return any(v is True for v in seen)
