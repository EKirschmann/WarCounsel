"""Advisor v2: owned-state-grounded counsel for the Advisor tab.

Pipeline per consult: character context (trio, level, focus, zone, AA points,
spell slots) + the /outputfile spellbook (what the character actually OWNS)
+ recently-cast spells from the log + compacted EQL-wiki data -> one LLM call
-> strict JSON:
  loadout      what to memorize right now (fills the spell slots, owned only)
  replace      spells in use that a better spell supersedes
  aa_now/save  AA purchase order vs savings goal
  horizon      significant unlocks in the NEXT 5 LEVELS + prep for them
  locations    where to hunt for this level/trio (+ notable paired drops)
  class_notes  weapon-skill / exaltation guidance per class

Fails soft: without the wiki the model grounds in classic-EQ knowledge and
says so; without the LLM a deterministic fallback keeps the tab alive.
Owned AA ranks come from /alternateadv list when available (parser pending
a real log sample); until then the model is told ranks are unknown.
"""
import asyncio
import json
import logging
import re
from datetime import datetime
from typing import Any, List, Optional

try:
    from langchain_core.messages import HumanMessage
except ImportError:  # deterministic/lite build ships no langchain
    class HumanMessage:  # minimal stand-in; only the LLM path ever uses it
        def __init__(self, content=""):
            self.content = content


from backend.llm_runtime import active as llm_active, get_llm
from backend import builds_data
from backend.config import settings
from backend.spellbook import RETRIEVABLE
from backend.game_data import (build_wiki_context, hunting_candidates, is_resurrection,
                               is_travel_ritual, same_spell_line,
                               supersedes_for_slots)

logger = logging.getLogger(__name__)

ADVISOR_PROMPT = """You are the advisor inside an EverQuest Legends (EQL) companion app. EQL is a reimagined pre-Kunark EverQuest (launched 2026). Mechanics that matter:
- A character runs THREE classes at once (primary / secondary / tertiary) that level together; cross-class synergy drives every decision.
- Travel magic (rings, circles, zephyrs, gate, succor/evacuate) is cast via the RITUALS system, outside the spell bar — it never occupies a spell slot. Never put travel spells in the loadout or in replace pairs.
- Reanimation / Reconstitution / Reparation are RESURRECTION spells: they return a DEAD group member to their corpse with experience. They heal nothing and provide zero sustain — never describe them as healing or self-sustain, and never slot them for a solo focus (you cannot cast while dead).
- Spell slots are scarce: only __SLOTS_NOTE__ spells can be memorized at once.
- AAs are available from level 1 (General / Archetype / Class / Special tabs) and persist across class swaps: a rank bought once is owned in every combo that qualifies, so General and Archetype ranks are better value than a Class rank for a trio that swaps classes.
- Never recommend spending points on an AA the character does not BUY: Special-tab AAs (e.g. Banestrike) and free ranks come from achievements, and AUTOGRANTED class AAs arrive on their own at level (the launch-day Unbound line — Alacrity/Life/Ferocity/Versatility/Drain/Lethality — is autogranted). Recommending any of these wastes the player's points.

__WIKI_HEADER__
__WIKI__

CHARACTER
__CONTEXT__

Reply with ONLY a JSON object (no markdown fences, no prose) shaped exactly like:
{
  "note": "one short sentence of overall counsel, or null",
  "must_have": [{"name": "...", "cls": "...", "reason": "..."}],
  "should_have": [{"name": "...", "cls": "...", "reason": "..."}],
  "nice_to_have": [{"name": "...", "cls": "...", "reason": "..."}],
  "prebuffs": [{"name": "...", "cls": "...", "reason": "..."}],
  "replace": [{"using": "...", "upgrade": "...", "why": "..."}],
  "aa_now": [{"name": "...", "cost": 3, "reason": "..."}],
  "aa_save": [{"name": "...", "cost": 12, "reason": "..."}],
  "horizon": [{"level": 33, "cls": "...", "name": "...", "reason": "..."}],
  "locations": [{"zone": "...", "why": "...", "notable": "..."}],
  "class_notes": [{"topic": "...", "advice": "..."}]
}

Rules:
- The loadout is tiered and must USE ALL __SLOTS_NOTE__ slots. Choose ONLY from the "Spellbook USABLE NOW" list (owned AND at or below the character's level). Name the job each pick does. Never pick a spell superseded by another owned spell.
  - must_have: the core spells that should always be memorized, in priority order (typically 5-7).
  - should_have: fills the REMAINING slots, in priority order — must_have + should_have together must total EXACTLY __SLOTS_NOTE__ picks.
  - nice_to_have: 10-14 EXTRA alternatives beyond the slot count, in priority order, so the player can swap by situation (different zone, tougher pulls, low mana).
- prebuffs: every entry's reason must say WHAT IT DOES and why it matters for this focus, using the effect shown beside it — "Permanent buff." is not a reason. Include long buffs worth re-casting between pulls, not only permanent ones. Separate from the loadout — list PERMANENT buffs (marked in the character data) FIRST: they persist until death, are cast exactly once, and must never be described as needing refreshing. Then long-duration self-buffs worth keeping up (damage shields like Bramblecoat, AC/HP buffs, Spirit of Wolf). The player memorizes one temporarily, casts it, then swaps the slot back to combat spells — so do NOT waste loadout slots on long buffs; put them here. Owned and level-legal only. At most __SLOTS_NOTE__ entries: they are memorized to be cast, so a longer routine does not fit the book in one pass.
- If the character data says NO PET, never recommend pet spells of any kind — no pet haste, no shrink, no pet heals, no pet buffs. They target a pet slot that will be empty. Summoned-pet lines (skeletons, elementals, warders): only ever slot the HIGHEST-level pet the character owns — older ranks are strictly weaker versions of the same pet.
- Respect the focus STRICTLY: for solo focuses, never slot group-only utility — resurrection and corpse-recovery lines, buffs that can only target others — those are dead slots when playing alone.
- If a "Missing spells they could BUY" list is present, fold the best purchases into note or horizon (say they are vendor purchases).
- replace: ONLY same-spell-line pairs — the upgrade must do the same job with the same primary effect (Symbol of Transal -> Symbol of Ryltan; Minor Healing -> Healing). A teleport, utility, or AA ability is NEVER upgraded by a nuke or an unrelated spell. Cover: recently-cast spells superseded by a better OWNED spell, and owned loadout spells with a significant same-line upgrade within 5 levels (say the level). Omit any pair you are not sure about; every pair is machine-verified and wrong ones are discarded.
- aa_now: what to buy right now with the available points (use the per-rank costs in the data). Owned AA ranks are __AA_RANKS_NOTE__ — state assumptions briefly.
- aa_save: 1-3 savings goals, especially anything that preps for the horizon items.
- horizon: the significant spells/abilities arriving within the NEXT 5 LEVELS for any of the three classes (exact level from the tables), plus any AA worth buying in advance for them.
- locations: 2-4 hunting spots for the level and focus. When a "Hunting grounds" list is present in the character data, choose ONLY zones from that list, using its exact names — never a city, never a zone outside the list (picks outside it are machine-discarded). Prefer spots whose band centers on the level over ones they are outgrowing; where you know a notable drop that pairs with this trio, name it in "notable" (else use "").
- class_notes: one entry per class with practical guidance — for melee: which weapon skill to run right now (e.g. fists vs 1H Blunt for a Monk) and exaltations/disciplines if known. Mark uncertainty plainly when the data above does not cover it; never invent numbers.
"""

WIKI_HEADER_PRESENT = ("AUTHORITATIVE EQL WIKI DATA - prefer these exact names, "
                       "levels, and costs over memory:")
WIKI_HEADER_ABSENT = ("No wiki data is available right now. Ground suggestions in "
                      "classic pre-Kunark EverQuest equivalents and briefly mark "
                      "uncertainty inside each reason.")


def _known(v: Any) -> str:
    return str(v) if v is not None else "unknown"


def _build_prompt(ctx: dict, wiki: str) -> str:
    lines = [
        f"- Name: {ctx.get('name') or 'Unknown'} ({ctx.get('race') or 'race unknown'})",
        f"- Classes (primary/secondary/tertiary): {ctx.get('class_str') or 'unknown'}",
        f"- Level: {_known(ctx.get('level'))}",
        f"- Focus / playstyle: {ctx.get('playstyle') or 'balanced'}",
        f"- Current zone: {ctx.get('zone') or 'unknown'}",
        f"- Unspent AA points: {_known(ctx.get('aa_available'))}",
        f"- Recent log activity: {ctx.get('recent_activity') or 'none'}",
    ]
    aas = ctx.get("owned_aas") or {}
    if aas:
        aal = "; ".join(
            f"{n} x{v['ranks']}" + (f" (next rank {v['cost']}pt)" if v.get("cost") else "")
            for n, v in sorted(aas.items()))
        lines.append(f"- Owned AAs (from /alternateadv list, {len(aas)} distinct): {aal}")
    inv = ctx.get("inventory_worn")
    if inv:
        lines.append("- Equipped gear (from /outputfile inventory): "
                     + "; ".join(f"{k}: {v}" for k, v in sorted(inv.items())))
    miss = ctx.get("missing_spells")
    if miss:
        lines.append("- Missing spells they could BUY now (from /outputfile "
                     "missingspells): "
                     + ", ".join(f"{s['name']} (L{s['level']})" for s in miss))
    casts = ctx.get("recent_casts") or []
    lines.append("- Recently cast (live log, newest first): "
                 + (", ".join(casts) if casts else "none seen"))
    if ctx.get("_no_pet"):
        lines.append("- NO PET: none of these classes summons one, so every "
                     "pet-targeted spell is dead weight in the loadout.")
    meas = ctx.get("_measured") or []
    if meas:
        lines.append("- MEASURED from this character's own combat log "
                     "(recent fights; avg per hit, then total): "
                     + "; ".join(meas)
                     + ". Prefer what is actually performing over what looks "
                       "strong on paper.")
    perm = ctx.get("_permanent") or []
    if perm:
        described = [f"{n} ({e})" if (e := _buff_effects(n)) else n for n in perm]
        lines.append("- PERMANENT buffs owned (last until death — cast ONCE "
                     "after login/death, NEVER tell the user to refresh them, "
                     "never spend a combat slot on them): "
                     + ", ".join(described))
    longb = ctx.get("_long_buffs") or []
    if longb:
        lines.append("- LONG buffs owned and castable now, worth re-casting "
                     "between pulls (duration and effect shown): "
                     + ", ".join(longb))
    hunt = ctx.get("_hunting") or []
    if hunt:
        def fmt(c):
            q = c.get("quality")
            tag = {"efficient": "EFFICIENT exp here", "ok": "doable"}.get(q, q)
            note = f" — {c['note']}" if c.get("note") else ""
            return f"{c['zone']} ({c['band']}, {tag}{note})"
        at_lv = [c for c in hunt if c.get("at_level")]
        stretch = [c for c in hunt if not c.get("at_level")]
        txt = "; ".join(fmt(c) for c in at_lv[:20])
        if stretch:
            txt += (" | STRETCH ONLY (content starts above them — pick at most "
                    "one, only if the focus wants a challenge): "
                    + "; ".join(f"{c['zone']} ({c['band']})" for c in stretch[:6]))
        lines.append("- Hunting grounds (community Recommended-Levels table, "
                     "in-era zones only; the community rates per-level "
                     "efficiency — STRONGLY prefer EFFICIENT zones): " + txt)
    book = ctx.get("spellbook")
    if book:
        level = ctx.get("level")
        usable = [s for s in book["castable"]
                  if level is None or s["level"] <= level]
        future = [s for s in book["castable"]
                  if level is not None and s["level"] > level]
        # Prefer the pre-gated list: travel rituals, solo-dead resurrection
        # lines and spells superseded by another owned spell are removed
        # BEFORE prompting, so a loadout slot cannot be spent on one. Falls
        # back to the full list if the pre-pass could not run.
        viable = ctx.get("_viable") or None
        if viable:
            keep = {n.lower() for n in viable}
            usable = [s for s in usable if s["name"].lower() in keep]
        owned = "; ".join(f"{s['name']} (L{s['level']})" for s in usable)
        pre = ""
        if viable and ctx.get("_pregated"):
            pre = (f" [{len(ctx['_pregated'])} owned spells already removed "
                   "for you: travel rituals, resurrection lines when solo, and "
                   "any spell superseded by another you own — every spell below "
                   "is a real option, so you never need to check for those]")
        lines.append(f"- Spellbook USABLE NOW (owned AND at or below their "
                     f"level; from /outputfile spellbook, {book['age_hours']}h "
                     f"old){pre}: {owned}")
        if future:
            lines.append("- Owned but ABOVE their level (scribed for later — "
                         "cannot be memorized yet, NEVER put in the loadout): "
                         + ", ".join(f"{s['name']} (L{s['level']})" for s in future))
        if book["other_loadouts"]:
            lines.append(f"- Also owns {len(book['other_loadouts'])} spells usable "
                         "only by other loadouts (ignore for the loadout).")
    else:
        lines.append("- Spellbook: NO export found — counsel loadout from the wiki "
                     "tables instead and tell the user to type /outputfile "
                     "spellbook in-game for owned-spell grounding.")
    from backend.game_data import class_guide_text
    guides = class_guide_text(
        [x.strip() for x in (ctx.get("class_str") or "").split("/")
         if x.strip()], include_refs=True)
    if guides:
        lines.append("- Community class guides (curated .md files in "
                     "class_guides/ — battle-tested playstyle wisdom; may "
                     "lag game patches, weigh against live data):\n" + guides)
    slots = ctx.get("spell_slots")
    aa = ctx.get("aa_available")
    return (ADVISOR_PROMPT
            .replace("__WIKI_HEADER__", WIKI_HEADER_PRESENT if wiki else WIKI_HEADER_ABSENT)
            .replace("__WIKI__", wiki)
            .replace("__CONTEXT__", "\n".join(lines))
            .replace("__SLOTS_NOTE__", str(slots) if slots is not None else "an unknown number of")
            .replace("__AA_RANKS_NOTE__",
                     "listed in the character data — do not recommend re-buying "
                     "maxed ranks" if ctx.get("owned_aas") else
                     "unknown (tell the user to type /alternateadv list in-game "
                     "to sync them)"))


def _lmstudio_budget(prompt_chars: int) -> int:
    """max_tokens that fits the CURRENTLY loaded context window. JIT
    reloads can bring a model back at a small default context; sizing the
    request to reality prevents the engine's cryptic 400 overflow error."""
    if llm_active()["provider"] != "lmstudio":
        return 0  # frontier/other providers: no bind — their defaults are fine
    try:
        from backend.llm_runtime import context_limit
        ctx = int((context_limit() or {}).get("limit") or 0)
    except Exception:
        ctx = 0
    if not ctx:
        return 6000
    est_prompt = prompt_chars // 3 + 200  # ~3 chars/token, safety pad
    # Ceiling raised from 12000, and the rest of the window is offered. A
    # REASONING model spends its thinking against this same budget: one run
    # burned 5,997 reasoning tokens out of 6,000 and was cut off
    # mid-deliberation with an empty content field, which surfaced as "no
    # JSON in reply" -- a parsing complaint about a model that never got as
    # far as answering.
    return max(1200, min(24000, ctx - est_prompt - 256))


def _reply_text(response: Any) -> str:
    """All the text a reply carries, wherever the provider put it.

    `content` is not always where the answer is. QAT and reasoning builds
    served through LM Studio return an EMPTY content with the whole answer
    in `reasoning_content`, so reading content alone yields "" and the
    caller reports no JSON while the raw reply plainly contains some.
    Anthropic-style block lists are flattened here too.
    """
    out: List[str] = []
    content = getattr(response, "content", None)
    if isinstance(content, str):
        out.append(content)
    elif isinstance(content, list):
        for block in content:
            if isinstance(block, str):
                out.append(block)
            elif isinstance(block, dict):
                out.append(str(block.get("text") or block.get("content") or ""))
    extra = getattr(response, "additional_kwargs", None) or {}
    meta = getattr(response, "response_metadata", None) or {}
    for src in (extra, meta):
        for key in ("reasoning_content", "reasoning", "thinking"):
            val = src.get(key)
            if isinstance(val, str) and val.strip():
                out.append(val)
    return chr(10).join(p for p in out if p)


def _warn_if_truncated(prompt: str, data: dict) -> None:
    """Say so when the prompt cannot have fitted in the model's context.

    Ollama truncates silently -- no error, no flag on the response -- so a
    prompt that overflows produces a confident answer built from whatever
    survived. A level-46 character got a fourteen-slot loadout containing
    two spells, and nothing anywhere said the spellbook had been cut off.

    Estimated at ~3 chars per token, deliberately rough: this exists to
    catch "the prompt is twice the window", not to be exact.
    """
    try:
        from backend.llm_runtime import context_limit
        limit = int((context_limit() or {}).get("limit") or 0)
    except Exception:
        return
    if not limit:
        return
    est = len(prompt) // 3
    if est <= limit:
        return
    picks = len(data.get("must_have") or []) + len(data.get("should_have") or [])
    logger.warning(
        "prompt ~%d tokens exceeds the %d-token context — the model saw only "
        "part of it (returned %d loadout picks)", est, limit, picks)
    data["note"] = ((data.get("note") or "") + " ").lstrip() + (
        f"NOTE: this prompt is about {est} tokens and the model's context is "
        f"{limit}, so part of it — most likely your spellbook — was cut off "
        f"before the model saw it. Raise the context limit in Settings.")


def _no_json_reason(response: Any, raw: str) -> str:
    """Why there was no JSON, in terms the player can act on.

    "no JSON object in LLM reply (0 chars of text seen)" reads as a parser
    fault. The case actually seen was a reasoning model that spent its whole
    completion budget thinking -- 5,997 reasoning tokens of 6,000,
    finish_reason "length", content empty. It never reached the answer, and
    a complaint about missing JSON sends the reader looking in the wrong
    place entirely.
    """
    meta = getattr(response, "response_metadata", None) or {}
    finish = meta.get("finish_reason") or meta.get("stop_reason")
    usage = (meta.get("token_usage") or meta.get("usage")
             or getattr(response, "usage_metadata", None) or {})
    reasoning = 0
    if isinstance(usage, dict):
        det = usage.get("completion_tokens_details") or {}
        reasoning = (det.get("reasoning_tokens")
                     or usage.get("reasoning_tokens") or 0)
    if finish == "length":
        if reasoning:
            return (f"the model spent its whole reply budget thinking "
                    f"({reasoning} reasoning tokens) and never answered. "
                    "Raise the context limit in Settings, or pick a model "
                    "that does not think out loud.")
        return ("the reply was cut off before it finished — raise the "
                "context limit in Settings.")
    return f"no JSON object in LLM reply ({len(raw)} chars of text seen)"


def _extract_json(text: str) -> Optional[dict]:
    # thinking models (qwen3 family) prefix <think> blocks — cut them out so
    # stray braces inside the reasoning can't confuse the JSON scan
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None


def _clean_list(items: Any, keys: tuple, cap: int = 16, require: str = "name") -> List[dict]:
    out: List[dict] = []
    for it in items or []:
        if not (isinstance(it, dict) and it.get(require)):
            continue
        out.append({k: it.get(k) for k in keys})
        if len(out) >= cap:
            break
    return out


def _fallback_body(ctx: dict, reason: str) -> dict:
    from backend.agent.tools import MOCK_AAS
    playstyle = ctx.get("playstyle") or "balanced"
    aas = MOCK_AAS.get(playstyle, MOCK_AAS["balanced"])
    return {
        "note": (f"Live counsel needs the LLM ({reason}). Start LM Studio's server "
                 f"(or set ANTHROPIC_API_KEY) and press Consult again."),
        "loadout": [], "must_have": [], "should_have": [],
        "nice_to_have": [], "prebuffs": [], "replace": [],
        "aa_now": [{"name": a["name"], "cost": None, "reason": a["desc"]} for a in aas],
        "aa_save": [], "horizon": [], "locations": [], "class_notes": [],
    }


# self-buffs that are NOT persistent states: travel (26/83/88/104), item
# summons (32), pets (33/71), feign death (74), resurrection (81)
_NOT_PERM_SPAS = {26, 32, 33, 71, 74, 81, 83, 88, 104}
_SELF_TARGET = 6
# Effects that are never a pre-buff even when they last a while. 67 is the
# remote eye (Eye of Zomm) -- it summons something that flies off and does
# nothing to the caster, so there is nothing to pre-cast.
# 12 is invisibility and 28 is invisibility-versus-undead. They last a
# long time and land on you, so every structural test for a buff passes --
# but you cast them for a specific pull, not as part of buffing up, and
# they were crowding the real buffs out of the list.
# 99 is root and 22 is charm. Treeform is a self-target 36-minute spell, so
# every structural test for a pre-buff passed -- and it plants you in the
# ground. Befriend Animal and Charm Animals last 20 minutes and are cast on
# something you intend to fight beside, not on yourself.
# 57 is levitate and 13 is see-invisibility. Both are long, both land on
# you, and both pass every structural test for a buff -- but you cast them
# to cross a zone or to find something hiding, not as part of buffing up,
# and in a list bounded by your gem count they push out something you would
# actually fight better for. Same reasoning that already excluded
# invisibility. 10 is charisma: the dataset marks it NOISE (see _BUFF_NOISE)
# because zero-magnitude charisma pads almost every record, so a spell whose
# LEADING effect is charisma is one we can say nothing about -- it rendered
# as "long buff" and no more, which is filler wearing a recommendation.
_NOT_A_BUFF_SPAS = _NOT_PERM_SPAS | {67, 12, 28, 99, 22, 57, 13, 10}

# targetTypeId, read off spells whose purpose is unambiguous rather than
# assumed from the id: 5 is an enemy (Stun, Fear, Lightning Bolt, Ensnare),
# 9 an animal you are charming (Befriend Animal), 14 your pet (Feral
# Spirit). What is left is 6 self (Yaulp, Bramblecoat), 51 a single friendly
# target (Center, Holy Armor, Symbol of Transal) and 41/43 their group
# versions (Protection of Steel, Scale of Wolf).
_BUFFABLE_TARGETS = {6, 41, 43, 51}
# ...of which 41 and 43 are the GROUP forms (Protection of Steel is the group
# twin of Skin like Steel, Scale of Wolf of Spirit of Wolf).
_GROUP_TARGETS = {41, 43}


def _prefers_group(name: str, solo: bool) -> int:
    """Tie-break between a buff and its group twin. Higher wins.

    Skin like Steel and Protection of Steel are the same 50 AC and 50 HP for
    the same 36 minutes; the only difference is who ELSE it lands on. On
    equal magnitudes the shape fallback kept whichever happened to come
    first in the list, which is how a SOLO focus was handed the group
    version of every armour buff. Solo, the group form lands on nobody else
    and is at best equal; grouped, it is the entire point.

    A TIE-BREAK only -- a stronger group buff still beats a weaker single
    one, because that magnitude is a real difference and this is not.
    """
    from backend import builds_data
    grp = (builds_data.spell_entry(name) or {}).get("targetTypeId") in _GROUP_TARGETS
    return int(grp != solo)


def _is_prebuff(e: dict) -> bool:
    """Does this spell leave a lasting effect on YOU or your group?

    Both halves were a bug before they were a check. The TARGET matters
    because Ensnare is a 14-minute effect and nothing asked who it lands on,
    so a snare was offered as something to cast before a pull. The EFFECT
    matters because Treeform is self-target and long and roots you in place.
    Duration and ownership say nothing about either.
    """
    from backend.game_data import _primary_effect
    if e.get("targetTypeId") not in _BUFFABLE_TARGETS:
        return False
    pe = _primary_effect(e)
    return not (pe and pe[0] in _NOT_A_BUFF_SPAS)


# How far ahead the horizon looks. The wiki/builds context already spans
# level+12, so this is a presentation window, not a data limit.
HORIZON_LEVELS = 5


# Effects that are noise in a one-line buff summary: zero-magnitude
# charisma spacers pad almost every record, and the illusion id is a form
# number rather than a stat.
_BUFF_NOISE = {"Charisma", "Illusion", "Evacuate"}


def _buff_effects(name: str) -> str:
    """A one-line "what it actually does", from the spell record.

    The prompt used to hand over bare NAMES, which is why every pre-buff
    came back reasoned as "Permanent buff." -- the model had nothing else
    to say about them. It cannot describe an effect it was never shown.
    """
    from backend import builds_data
    e = builds_data.spell_entry(name)
    if not e:
        return ""
    parts = []
    for eff in (e.get("effects") or []):
        label = (eff.get("name") or "").strip()
        base = eff.get("baseValue")
        if not label or label in _BUFF_NOISE or not base:
            continue
        # damage shields carry a negative base; it is a positive thing
        parts.append(f"{label} {abs(int(base))}")
        if len(parts) >= 3:
            break
    return ", ".join(dict.fromkeys(parts))


def _long_buffs(ctx: dict) -> List[str]:
    """Owned, castable buffs that last long enough to be worth pre-casting.

    Permanent buffs were the only thing the prompt listed, so they were the
    only thing that came back -- five rows of "until death" and nothing a
    player would actually re-cast between pulls. A 27-minute AC buff is the
    other half of a pre-buff routine and was never mentioned.
    """
    from backend import builds_data
    level = ctx.get("level")
    perm = {n.lower() for n in (ctx.get("_permanent") or [])}
    out = []
    for sp in (ctx.get("spellbook") or {}).get("castable", []):
        if level is not None and sp["level"] > level:
            continue
        if sp["name"].lower() in perm:
            continue
        e = builds_data.spell_entry(sp["name"])
        if not e:
            continue
        ticks = e.get("durationTicks") or 0
        if ticks < 100:          # under ~10 minutes: not worth a pre-cast
            continue
        if not _is_prebuff(e):
            continue
        out.append({"name": sp["name"], "level": sp["level"], "_ticks": ticks})
    # Supersession runs BEFORE the cap. The spellbook is ordered low level to
    # high, so truncating it kept Skin like Rock and Center and cut the Skin
    # like Steel and Symbol of Transal that replace them -- the same failure
    # the missing-spells shopping list had, where an ascending cap kept the
    # 25 LOWEST and anyone with a backlog got an empty list.
    kept, _sup = _gate_stacking(out)
    kept.sort(key=lambda b: -(b.get("level") or 0))
    lines = []
    for b in kept[:24]:
        eff = _buff_effects(b["name"])
        lines.append(f"{b['name']} ({round(b['_ticks'] * 6 / 60)}min"
                     + (f", {eff}" if eff else "") + ")")
    return lines


def _permanent_buffs(ctx: dict) -> List[str]:
    """Owned usable spells that are permanent-until-death self-buffs:
    self-target + zero duration ticks in the eqlbuilds snapshot (verified:
    Instrument of Nife, Greater Wolf Form, Bramblecoat all match; timed
    buffs like Spirit of Wolf carry real ticks; enemy utility like Stun is
    excluded by target type). Damage shields have negative bases, so no
    positivity requirement."""
    from backend import builds_data
    from backend.game_data import _primary_effect
    level = ctx.get("level")
    out = []
    for s in (ctx.get("spellbook") or {}).get("castable", []):
        if level is not None and s["level"] > level:
            continue
        e = builds_data.spell_entry(s["name"])
        if (not e or (e.get("durationTicks") or 0) != 0
                or e.get("targetTypeId") != _SELF_TARGET):
            continue
        pe = _primary_effect(e)
        if pe and pe[0] not in _NOT_PERM_SPAS:
            out.append(s["name"])
    return out


# gem-order stack for generated spell sets: direct damage, DoTs, AoE up
# front; heals pinned to gem 8+; utility, then summons and pet utility last
_AE_TARGETS = {4, 8}          # point-blank / targeted AE
_PET_TARGET = 14
_GEM_STACK = ("dd", "dot", "aoe", "heal", "utility", "summon", "summon_util")


def _gem_category(name: str) -> str:
    from backend import builds_data
    from backend.game_data import _primary_effect
    e = builds_data.spell_entry(name)
    if not e:
        return "utility"
    pe = _primary_effect(e)
    tgt = e.get("targetTypeId")
    ticks = e.get("durationTicks") or 0
    spa, basev = (pe[0], pe[1] or 0) if pe else (None, 0)
    if spa in (33, 71):
        return "summon"
    if spa == 32 or tgt == _PET_TARGET:
        return "summon_util"
    if tgt in _AE_TARGETS:
        return "aoe"
    if spa == 0 and basev < 0:
        return "dot" if ticks > 0 else "dd"
    if spa == 0 and basev >= 0 and tgt == 51:
        return "heal"
    return "utility"


def stack_gem_order(names: List[str]) -> List[str]:
    """Order picks for the in-game set: DD, DoT, AoE from gem 1; healing
    starting gem 8 where possible; then utility, summons, summon utility."""
    cats = {n: _gem_category(n) for n in names}

    def bucket(*cs):
        return [n for n in names if cats[n] in cs]

    offense = bucket("dd") + bucket("dot") + bucket("aoe")
    heals = bucket("heal")
    tail = bucket("utility") + bucket("summon") + bucket("summon_util")
    slots = offense[:7]
    spill = offense[7:]
    while len(slots) < 7 and heals and tail:
        slots.append(tail.pop(0))  # keep heals at gem 8 when there is filler
    return (slots + heals + spill + tail)[:14]


async def _extra_alternatives(ctx: dict, exclude: set, want: int) -> List[dict]:
    """Deterministic nice-to-have backfill: highest-level owned usable spells
    not already picked — travel/res/superseded-by-owned dropped. Guarantees
    the player has swap options even when the LLM lists few."""
    level = ctx.get("level")
    solo = (ctx.get("playstyle") or "").startswith("solo")
    book = ctx.get("spellbook") or {}
    usable = [s for s in book.get("castable", [])
              if (level is None or s["level"] <= level)
              and s["name"] not in exclude]
    names = [s["name"] for s in usable]
    out = []
    for s in sorted(usable, key=lambda x: -x["level"]):
        if len(out) >= want:
            break
        n = s["name"]
        try:
            if await is_travel_ritual(n) or (solo and await is_resurrection(n)):
                continue
            if any(await supersedes_for_slots(n, o) for o in names if o != n):
                continue
        except Exception:
            continue
        cat, _ = await _spell_cat(n)
        out.append({"name": n, "cls": "", "level": s["level"],
                    "reason": f"owned {cat} alternative (auto-added)"})
    return out


def _gate_locations(locs: List[dict], hunt: List[dict]) -> List[dict]:
    """Keep only picks present in the in-era hunting table (when we have it).
    The table is authoritative for WHERE; the LLM only supplies the why."""
    if not hunt:
        return locs
    def key(s: str) -> str:
        return re.sub(r"^the\s+", "", (s or "").casefold()).strip()
    allowed = {key(c["zone"]): c for c in hunt}
    kept, used, stretch_used = [], set(), 0
    for loc in locs:
        k = key(loc.get("zone"))
        match = allowed.get(k) or next(
            (c for kk, c in allowed.items() if k and (k in kk or kk in k)), None)
        if not match:
            logger.info("Dropped out-of-table location: %s", loc.get("zone"))
            continue
        if not match.get("at_level"):
            if stretch_used:  # at most one above-band pick survives
                logger.info("Dropped extra stretch location: %s", match["zone"])
                continue
            stretch_used += 1
        loc["zone"] = f"{match['zone']} ({match['band']})"
        used.add(match["zone"])
        kept.append(loc)
    for c in hunt:  # backfill with the best at-level zones from the table
        if len(kept) >= 3:
            break
        if c.get("at_level") and c["zone"] not in used:
            kept.append({"zone": f"{c['zone']} ({c['band']})",
                         "why": "In this level band per the community "
                                "Recommended-Levels table.",
                         "notable": ""})
            used.add(c["zone"])
    return kept


# ------------------------------------------------- deterministic (no-LLM)

BUILTIN_NOTE = ("Deterministic counsel — no LLM configured. Picks are "
                "mechanically derived (owned, level-legal, non-superseded, "
                "categorized by spell effect); priorities are heuristic "
                "rather than tactical. Pick a model in the Counsel selector "
                "for reasoned advice.")


async def _spell_cat(name: str) -> tuple:
    """(category, grounded) from the spell's primary effect."""
    from backend.game_data import spell_record, _primary_effect
    try:
        rec = await spell_record(name)
    except Exception:
        rec = None
    if not rec:
        return "other", False
    pe = _primary_effect(rec)
    if not pe:
        return "other", True
    eid, basev = pe[0], (pe[1] or 0)
    if eid == 0:
        if basev > 0:
            return "heal", True
        if basev < 0:
            return "damage", True
        return "other", True  # zero-base rank-1 records: sign unknowable
    if eid == 100:  # heal/damage over time
        return ("heal" if basev >= 0 else "damage"), True
    if eid == 99 or (eid == 3 and basev < 0):
        return "control", True
    if basev > 0:
        return "buff", True
    return "other", True


async def _builtin_counsel(ctx: dict) -> dict:
    level = ctx.get("level")
    slots = ctx.get("spell_slots") or 8
    solo = (ctx.get("playstyle") or "").startswith("solo")
    book = ctx.get("spellbook") or {}
    usable = [s for s in book.get("castable", [])
              if level is None or s["level"] <= level]
    grounded_any = False
    infos = []
    for s in usable:
        name = s["name"]
        try:
            if await is_travel_ritual(name):
                continue
            if solo and await is_resurrection(name):
                continue
        except Exception:
            pass
        cat, grounded = await _spell_cat(name)
        grounded_any = grounded_any or grounded
        infos.append({"name": name, "level": s["level"], "cat": cat})
    names = [i["name"] for i in infos]
    keep, replaced = [], []
    for i in infos:  # drop spells superseded by another owned usable spell
        sup = None
        for other in names:
            if other != i["name"]:
                try:
                    if await supersedes_for_slots(i["name"], other):
                        sup = other
                        break
                except Exception:
                    pass
        if sup:
            replaced.append({"using": i["name"], "upgrade": sup,
                             "note": "owned upgrade in the same spell line"})
        else:
            keep.append(i)
    return await _compose_builtin(ctx, bycat_of(keep), replaced,
                                  grounded_any, level, slots)


def bycat_of(keep: list) -> dict:
    bycat: dict = {}
    for i in sorted(keep, key=lambda x: -x["level"]):
        bycat.setdefault(i["cat"], []).append(i)
    return bycat


async def _compose_builtin(ctx, bycat, replaced, grounded_any,
                           level, slots) -> dict:
    solo = (ctx.get("playstyle") or "").startswith("solo")
    book = ctx.get("spellbook") or {}

    def take(cat, n):
        out = []
        while n > 0 and bycat.get(cat):
            out.append(bycat[cat].pop(0))
            n -= 1
        return out

    def entry(i, why):
        return {"name": i["name"], "cls": "", "reason": why,
                "level": i["level"]}

    must = [entry(i, f"highest-level owned damage spell (L{i['level']})")
            for i in take("damage", 6 if solo else 4)]
    must += [entry(i, f"strongest owned heal (L{i['level']})")
             for i in take("heal", 1)]
    must += [entry(i, f"owned control spell (L{i['level']})")
             for i in take("control", 1)]
    should = []
    for cat, why in (("heal", "backup heal"), ("control", "extra control"),
                     ("damage", "additional damage option"),
                     ("other", "utility")):
        while len(must) + len(should) < slots and bycat.get(cat):
            should.append(entry(bycat[cat].pop(0), why))
    nice = []
    for cat in ("damage", "heal", "control", "other"):
        for i in (bycat.get(cat) or [])[:3]:
            nice.append(entry(i, f"alternative {cat} spell"))
    # The deterministic path had the same empty-reason problem as the LLM
    # one: "positive-effect buff" on every row says nothing about which to
    # cast. The effects are in the spell record either way.
    prebuffs = [entry(i, (_buff_effects(i["name"]) or "positive-effect buff")
                      + " — cast it, then swap the slot back to combat spells")
                for i in (bycat.get("buff") or [])]
    prebuffs = _cap_prebuffs(prebuffs, ctx)
    horizon = []
    if level is not None:
        for s in book.get("castable", []):
            if level < s["level"] <= level + HORIZON_LEVELS:
                horizon.append({"level": s["level"], "cls": "",
                                "name": s["name"],
                                "reason": "already scribed — usable on level-up"})
        for s in (ctx.get("missing_spells") or []):
            if level < s["level"] <= level + HORIZON_LEVELS:
                horizon.append({"level": s["level"], "cls": "",
                                "name": s["name"],
                                "reason": "missing — vendor purchase"})
    aas = ctx.get("owned_aas") or {}
    avail = ctx.get("aa_available")
    priced = [(n, v) for n, v in sorted(aas.items()) if v.get("cost")]
    afford = sorted((x for x in priced
                     if avail is None or x[1]["cost"] <= avail),
                    key=lambda x: x[1]["cost"])
    aa_now = [{"name": n, "cost": v["cost"],
               "reason": "cheapest affordable next rank (deterministic mode "
                         "ranks by cost, not synergy)"}
              for n, v in afford[:4]]
    aa_save = [{"name": n, "cost": v["cost"],
                "reason": "highest-cost known rank — long-term goal"}
               for n, v in sorted(priced, key=lambda x: -x[1]["cost"])[:2]]
    locations = [{"zone": f"{c['zone']} ({c['band']})",
                  "why": "In this level band per the community "
                         "Recommended-Levels table.", "notable": ""}
                 for c in (ctx.get("_hunting") or [])
                 if c.get("at_level")][:3]
    # same rule as the LLM path: an alternative already sitting in a slot
    # is not an alternative
    _slotted = {str(x.get("name")).lower() for x in must + should}
    nice = [x for x in nice if str(x.get("name")).lower() not in _slotted]
    return {
        "source": "builtin",
        "grounding": "wiki" if grounded_any else "memory",
        "note": BUILTIN_NOTE,
        "loadout": (must + should)[:slots],
        "must_have": must, "should_have": should,
        "nice_to_have": nice[:12], "prebuffs": prebuffs,
        "replace": replaced[:6],
        "aa_now": aa_now, "aa_save": aa_save,
        "horizon": horizon[:8], "locations": locations,
        "class_notes": [{"topic": "Deterministic mode",
                         "advice": "Slots are filled by effect category and "
                                   "spell level. For synergy-aware tactics, "
                                   "pick an LLM in the Counsel selector."}],
    }


_SLOT_TOKENS = {
    "ear": "EAR", "wrist": "WRIST", "fingers": "FINGER", "range": "RANGE",
    "primary": "PRIMARY", "secondary": "SECONDARY", "head": "HEAD",
    "face": "FACE", "neck": "NECK", "shoulders": "SHOULDERS", "arms": "ARMS",
    "back": "BACK", "hands": "HANDS", "chest": "CHEST", "legs": "LEGS",
    "feet": "FEET", "waist": "WAIST", "ammo": "AMMO",
    # HELD is a real slot the client writes, but nothing is known to go in
    # it, so it must NOT be permissive. It used to fall through to the
    # "accepts anything" branch with Any Slot, which put a Secondary-only
    # Parrying Dagger there. Requiring the token means only an item whose
    # own Slot line says HELD can be recommended -- and if no EQL item ever
    # does, the row stays honestly empty instead of collecting whatever
    # happened to be spare.
    "held": "HELD",
}


async def _fits_slot(item: str, slot: str) -> bool:
    """Wiki Slot-line check: a Piercing dagger can't be a Range rec.

    ANY SLOT accepts anything equippable and is the only wildcard. HELD is
    NOT one -- see _SLOT_TOKENS. Items with no slot data still pass here;
    the unknown-stats guard is what keeps those honest, and for an EMPTY
    slot item_facts supplies the slot from a previous wearing."""
    low = slot.lower().strip()
    low = re.sub(r"\s+\d+$", "", low)  # "ear 2" -> "ear"
    token = _SLOT_TOKENS.get(low)
    if token is None:
        return True
    from backend.game_data import item_line
    line = await item_line(item)
    m = re.search(r"Slot: ([A-Z ]+)", line or "")
    if not m:
        return True
    return token in m.group(1).split()


def _item_base(name: str) -> str:
    return re.sub(r"\s*[+]\d+$", "", name or "").strip()


def _item_rank(name: str) -> int:
    m = re.search(r"[+](\d+)$", name or "")
    return int(m.group(1)) if m else 0


def _pareto_beats(a: dict, b: dict) -> bool:
    """True when stat vector `a` is >= `b` on EVERY stat and > on at least
    one (DELAY inverted — lower is better). Missing stats count as 0, so a
    challenger lacking any stat the worn item has always fails."""
    better = False
    for k in set(a) | set(b):
        av, bv = a.get(k, 0.0), b.get(k, 0.0)
        if k == "DELAY":
            av, bv = -av, -bv
        if av < bv:
            return False
        if av > bv:
            better = True
    return better


def _wpn_index(line: str, level) -> Optional[dict]:
    """MH/OH white-DPS indices for a 1H weapon, or None when the swap is
    NOT decidable without judgment: 2H (it empties the secondary slot),
    any Effect (the index excludes procs, so a proccing weapon can beat a
    higher index), or no damage/delay to model."""
    from backend.game_data import weapon_indices
    if not level or "Skill: 2H" in line:
        return None
    if re.search(r"(?<!Focus )Effect: ", line):
        return None
    d = re.search(r"DMG: (\d+)", line)
    dl = re.search(r"Atk Delay: (\d+)", line)
    if not (d and dl):
        return None
    return weapon_indices(int(d.group(1)), int(dl.group(1)), level)


def _weapon_beats(a: dict, b: dict, wa: dict, wb: dict, hand: str) -> bool:
    """A weapon upgrade this path can defend: strictly higher white-DPS
    index for the hand it goes in, and no OTHER stat lower.

    DMG and DELAY are deliberately EXCLUDED from the stat comparison.
    Judging them apart is what made a fast weapon look worse than a slow
    one -- 7/30 loses to 7/42 on delay alone under a naive vector -- and
    combining them correctly is precisely what the index does."""
    if wa[hand] <= wb[hand]:
        return False
    for k in set(a) | set(b):
        if k in ("DMG", "DELAY"):
            continue
        if a.get(k, 0.0) < b.get(k, 0.0):
            return False
    return True


async def _builtin_gear(ctx: dict) -> dict:
    """No-LLM gear counsel: exact same-item rank upgrades, plus cross-item
    swaps when a bag/bank item strictly Pareto-dominates the worn item's
    stat vector with BOTH sides scaled to their owned +N (never worse,
    better somewhere), plus 1H WEAPON swaps decided by the white-DPS
    index. Judgment-shaped trade-offs (procs, 2H, farm targets) still
    need a model."""
    from backend import item_facts
    from backend.game_data import (item_line, item_stat_vector,
                                   scale_item_line, _trio_usable)
    worn = ctx.get("worn") or {}
    items = ctx.get("inventory_items") or []
    classes = [x.strip() for x in (ctx.get("class_str") or "").split("/")
               if x.strip()]
    lvl = ctx.get("level")
    recs, used = [], set()
    # EVERY canonical slot, not just the occupied ones. Iterating
    # worn.items() meant an EMPTY slot was never considered at all, while
    # _full_slot_table backfilled it as "nothing owned equips here" -- a
    # verdict on a comparison that never ran. Reported from live play: an
    # empty off-hand with spare 1H weapons sitting in bags. CANON_SLOTS is
    # ordered Primary before Secondary, which the 2H check below needs.
    # SPECIFIC slots first, the generic "Any Slot" pair LAST. CANON_SLOTS
    # lists Any Slot first for display, and iterating in that order let the
    # wildcard claim an item before its real home was even considered -- a
    # Chest robe was recommended into Any Slot 2, then `used` blocked it
    # from Chest. Any Slot should mop up what is left over, not pre-empt.
    _order = CANON_SLOTS + [k for k in worn if k not in CANON_SLOTS]
    slot_order = ([k for k in _order if not k.startswith("Any Slot")]
                  + [k for k in _order if k.startswith("Any Slot")])
    for slot in slot_order:
        cur = (worn.get(slot) or "").strip()
        cb, cr = (_item_base(cur), _item_rank(cur)) if cur else ("", 0)
        best = None if not cur else None
        for it in (items if cur else []):
            if it.get("where") == "worn":
                continue
            r = _item_rank(it["name"])
            if (_item_base(it["name"]) == cb and r > cr
                    and (best is None or r > _item_rank(best["name"]))):
                best = it
        if best:
            recs.append({"slot": slot, "current": cur,
                         "recommend": best["name"],
                         "why": f"same item at higher rank "
                                f"(+{_item_rank(best['name'])} vs +{cr})",
                         "where": best["where"]})
            used.add(best["name"].lower())
            continue
        # cross-item swap. Weapons used to be skipped wholesale here
        # because ratio-vs-delay is not stat-comparable -- but that was
        # written before weapon_indices(), which answers exactly that
        # question (the MH damage bonus is a FLAT, delay-independent add,
        # so a fast weapon wins past the point ratio suggests). 1H swaps
        # are therefore decidable without a model. RANGE keeps its skip:
        # bows and thrown have mechanics the index does not model.
        base_slot = re.sub(r"\s+\d+$", "", slot.lower())
        # RANGE used to skip the comparison ENTIRELY and report "not
        # compared". That was too broad: only a ranged weapon's DAMAGE needs
        # the white-DPS index (which does not model bows or thrown), while its
        # STATS compare like any other item -- a Dagger of Marnek carries
        # INT 9 and SV VOID 6, and saying nothing about them hides a real
        # comparison behind a disclaimer aimed at a different question.
        # So: compare on stats with the index switched off, drop DMG/DELAY
        # from the vectors (judging those without the index is exactly the
        # error the index exists to prevent), and disclaim only the damage.
        stats_only = base_slot == "range"
        hand = (None if stats_only
                else {"primary": "mh", "secondary": "oh"}.get(base_slot))
        if base_slot == "secondary" and _dual_wields(classes) is False:
            # No Dual Wield: an off-hand WEAPON never swings, so its
            # white-DPS index describes damage that will not be dealt. A
            # shield or stat item in that slot is still perfectly good, so
            # this drops the weapon model rather than the slot.
            hand = None
            no_oh_weapon = True
        else:
            no_oh_weapon = False
        if base_slot == "secondary":
            # a 2H weapon occupies BOTH hands. The LLM path already dropped
            # the secondary row behind a 2H primary; this path never did,
            # and filling an empty off-hand made that gap reachable.
            eff_prim = next((r.get("recommend") for r in recs
                             if r["slot"] == "Primary" and r.get("recommend")),
                            None) or (worn.get("Primary") or "")
            if eff_prim:
                try:
                    pl = await item_line(eff_prim)
                except Exception:
                    pl = None
                if pl and "Skill: 2H" in pl:
                    recs.append({"slot": slot, "current": cur,
                                 "recommend": None, "where": None,
                                 "why": "— occupied by the two-handed "
                                        "primary (it uses both hands)"})
                    continue
        if cur:
            try:
                cur_line = await item_line(cur)
            except Exception:
                cur_line = None
            if not cur_line:
                continue  # STATS UNKNOWN worn item is never replaced
            cur_scaled = scale_item_line(cur_line, cr)
            cur_vec = item_stat_vector(cur_scaled)
            if stats_only and cur_vec:
                # damage is not decidable here; comparing it anyway is worse
                # than not comparing it
                cur_vec = {k: v for k, v in cur_vec.items()
                           if k not in ("DMG", "DELAY")}
            if not cur_vec:
                continue
            cur_wi = _wpn_index(cur_scaled, lvl) if hand else None
            if hand and not cur_wi:
                continue  # worn weapon 2H/proc'd/statless -- not decidable
        else:
            # EMPTY slot: the baseline is nothing, so anything owned that
            # fits and is usable is an improvement. Weapons still need an
            # index (a proc'd or 2H candidate stays a judgment call), it is
            # just measured against zero instead of against a worn weapon.
            cur_line, cur_vec, cur_wi = None, {}, None
        base_idx = (cur_wi or {}).get(hand, 0.0) if hand else 0.0
        champ = None
        # best "wins some, loses some" candidate for this slot
        trade = None
        # Wiki-less items we nonetheless know the SLOT of, because the
        # player has worn them before (item_facts learns Location from the
        # export). Good enough to FILL an empty slot -- that needs no
        # comparison -- and never good enough to REPLACE anything, since
        # with no stats there is nothing to compare. Kept separate so a
        # verified candidate always wins.
        fallback = None
        for it in items:
            nm = it["name"]
            if (it.get("where") == "worn" or nm.lower() in used
                    or _item_base(nm) == cb):
                continue
            try:
                line = await item_line(nm)
            except Exception:
                line = None
            if not line or "Slot:" not in line:
                if not cur and fallback is None:
                    fs = (item_facts.slot_for_id(it.get("id"))
                          or item_facts.slot_for_name(nm))
                    if fs and fs.strip().lower() == base_slot:
                        fallback = (it, "fills an empty slot — you have worn "
                                    "this item before, so its slot is known "
                                    "from your own export. Its STATS are not "
                                    "on the wiki, so this is not a stat "
                                    "comparison")
                continue
            if not await _fits_slot(nm, slot):
                continue
            if no_oh_weapon and _is_weapon(line):
                continue
            if classes and _trio_usable(line, classes) is False:
                continue
            scaled = scale_item_line(line, _item_rank(nm))
            vec = item_stat_vector(scaled)
            if stats_only and vec:
                vec = {k: v for k, v in vec.items()
                       if k not in ("DMG", "DELAY")}
            if not vec:
                # The wiki page EXISTS and names the slot, but carries no
                # numbers -- common on EQL for plain jewellery. Refusing it
                # is right when REPLACING something (there is nothing to
                # compare against the worn item) and wrong when FILLING:
                # an earring in an empty ear slot beats an empty ear slot,
                # whatever its stats turn out to be. Reported live -- a
                # Mithril Earring +4 sat in a bag while the second ear read
                # "nothing owned equips here", a verdict on a comparison
                # that never ran.
                #
                # Weapons stay out: an unmeasurable weapon in an empty hand
                # is a judgement call the index cannot make, and the empty
                # off-hand already has its own reasoned path.
                if not cur and not hand:
                    better = (fallback is None
                              or _item_rank(nm) > _item_rank(fallback[0]["name"]))
                    if better:
                        fallback = (it, "fills an empty slot — the wiki "
                                    "lists its slot but no stats, so this "
                                    "is not a stat comparison. Anything "
                                    "here beats nothing")
                continue
            if hand:
                wi = _wpn_index(scaled, lvl)
                base_wi = cur_wi or {"mh": 0.0, "oh": 0.0}
                if not wi or not _weapon_beats(vec, cur_vec, wi, base_wi, hand):
                    continue
                gain, shown = wi[hand] - base_wi[hand], wi[hand]
            else:
                a_vec, b_vec = _effective_vecs(vec, cur_vec, ctx)
                if base_slot == "any slot":
                    # An Any Slot item is NOT swung: it contributes stats
                    # and nothing else. Leaving DMG/DELAY in the vector let
                    # a weapon win the slot on damage it will never deal --
                    # reported from live play, where a 3.5-index blade was
                    # offered over a femur for a slot that swings neither.
                    a_vec = {k: v for k, v in a_vec.items()
                             if k not in ("DMG", "DELAY")}
                    b_vec = {k: v for k, v in b_vec.items()
                             if k not in ("DMG", "DELAY")}
                if not _pareto_beats(a_vec, b_vec):
                    # Not a clean win -- but "wins some, loses some" is a
                    # real trade the player can judge, and dropping it
                    # silently let a genuinely better boot sit in a bag
                    # while the row read "no better owned option flagged".
                    # That phrasing claims a search found nothing; what
                    # actually happened is a candidate lost a tiebreak we
                    # are not qualified to call. Strict Pareto still gates
                    # the RECOMMENDATION -- weighting AC against AGI needs
                    # class-specific numbers we do not have -- so the trade
                    # is surfaced rather than decided.
                    if cur:
                        gains = {k: a_vec.get(k, 0.0) - b_vec.get(k, 0.0)
                                 for k in set(a_vec) | set(b_vec)
                                 if k != "DELAY"
                                 and a_vec.get(k, 0.0) != b_vec.get(k, 0.0)}
                        up = {k: v for k, v in gains.items() if v > 0}
                        down = {k: -v for k, v in gains.items() if v < 0}
                        if up and down:
                            score = (len(up) - len(down), sum(up.values()))
                            if trade is None or score > trade[0]:
                                trade = (score, it, up, down)
                    continue
                gain = sum(a_vec.get(k, 0.0) - b_vec.get(k, 0.0)
                           for k in set(a_vec) | set(b_vec) if k != "DELAY")
                shown = None
            if champ is None or gain > champ[0]:
                champ = (gain, it, shown)
        if (base_slot == "secondary" and no_oh_weapon and champ is None
                and fallback is None and not cur):
            recs.append({"slot": slot, "current": cur, "recommend": None,
                         "where": None,
                         "why": "— your classes do not train Dual Wield, so "
                                "an off-hand weapon would never swing; only "
                                "a shield or stat item helps here"})
            continue
        if champ is None and trade is not None:
            _sc, ti, up, down = trade
            fmt = lambda d: ", ".join(
                f"{'+' if v > 0 else ''}{v:g} {k.replace('_', ' ')}"
                for k, v in sorted(d.items(), key=lambda kv: -abs(kv[1])))
            recs.append({"slot": slot, "current": cur,
                         "recommend": None, "where": ti["where"],
                         "tradeoff": {"item": ti["name"],
                                      "gains": fmt(up),
                                      "losses": fmt(down),
                                      "where": ti["where"]},
                         "why": f"trade-off — {ti['name']} gives "
                                f"{fmt(up)} but costs {fmt(down)}. Not "
                                f"recommended automatically because judging "
                                f"those against each other needs weights we "
                                f"do not have; your call"
                                + (". Ranged DAMAGE is not part of this "
                                   "comparison" if stats_only else "")})
            continue
        if (stats_only and champ is None and trade is None
                and fallback is None and cur):
            # Distinguish the two halves. Before, this slot claimed nothing
            # had been compared at all, which was wrong about the stats.
            recs.append({"slot": slot, "current": cur, "recommend": cur,
                         "where": "worn",
                         "why": "no owned ranged item beats it on STATS. Its "
                                "damage was not compared — the white-DPS "
                                "index does not model bows or thrown, so a "
                                "higher-damage ranged weapon could still "
                                "exist; pick a model in the Counsel selector "
                                "to have that judged"})
            continue
        if champ is None and fallback is not None:
            fb, fb_why = fallback
            recs.append({"slot": slot, "current": cur,
                         "recommend": fb["name"], "why": fb_why,
                         "where": fb["where"]})
            used.add(fb["name"].lower())
            continue
        if champ:
            it = champ[1]
            if hand and not cur:
                why = (f"fills an empty hand — white-DPS index {champ[2]} "
                       f"({hand.upper()}) from gear you already own. Procs "
                       "are excluded from the index, so a proccing weapon "
                       "can still beat this")
            elif hand:
                why = (f"higher white-DPS index at its owned +N — "
                       f"{champ[2]} vs {base_idx} ({hand.upper()}) with no "
                       "other stat lower. Procs are excluded from the index, "
                       "so a proccing weapon can still beat this")
            elif not cur:
                why = ("fills an empty slot from gear you already own "
                       "(stats shown at its owned +N)")
            else:
                why = ("strictly better at its owned +N — every "
                       "listed stat equal or higher (wiki "
                       "item-level scaling applied to both)")
            if stats_only:
                why += (". STATS only — ranged damage is not modelled by the "
                        "white-DPS index, so check the damage yourself before "
                        "swapping")
            recs.append({"slot": slot, "current": cur,
                         "recommend": it["name"], "why": why,
                         "where": it["where"]})
            used.add(it["name"].lower())
    exalts = [{"name": x["name"], "move_to": "",
               "where": ("in " + x["host"] if x.get("host")
                         else f"loose in {x['where']}"),
               "why": "owned exaltation stone (enable an LLM model for effect "
                      "details)"}
              for x in (ctx.get("exaltations") or [])]
    return {
        "source": "builtin",
        "note": "Deterministic gear check — no LLM. Same-item higher-rank "
                "upgrades plus strictly-better swaps, with stats compared "
                "at each item's owned +N via the wiki's item-level "
                "formula. 1H weapons compare by white-DPS index; procs, "
                "2H and farming targets need a model from the "
                "Counsel selector.",
        "slots": _full_slot_table(recs, worn),
        "farm": [], "exaltations": exalts, "unknown": [],
        # The deterministic pet pass runs here too. This returned [] before,
        # so with LLM_PROVIDER=none the panel said "nothing better in your
        # bags/bank for the pet" unconditionally -- a verdict with no
        # comparison anywhere behind it. Only CLEAR upgrades are emitted:
        # a trade-off is a judgement call and there is no model here to make
        # it, so silence is the honest answer for those.
        "pet_gear": await _builtin_pet_gear(ctx),
    }


async def _builtin_pet_gear(ctx: dict) -> list:
    """Clear pet upgrades, no model required. Mirrors the LLM path's gates."""
    from backend.game_data import _trio_usable, item_line as _il
    from backend.spellbook import RETRIEVABLE
    pet_inv = ctx.get("pet_inventory") or {}
    pet_slots = (ctx.get("pet_slots") or 0) or len(pet_inv)
    if not pet_slots:
        return []
    classes = [c.strip() for c in (ctx.get("class_str") or "").split("/") if c.strip()]
    pet_classes = ["Warrior", ctx.get("pet_second_class") or "Shadow Knight"] + classes
    worn_now = {v.lower() for v in pet_inv.values()}
    exalt_hosts = {(x.get("host") or "").lower() for x in (ctx.get("exaltations") or [])}
    pool = []
    for it in (ctx.get("inventory_items") or []):
        nm = it.get("name") or ""
        if it.get("where") not in RETRIEVABLE or nm.lower() in worn_now:
            continue
        if nm.lower() in exalt_hosts:
            continue
        try:
            line = await _il(nm)
        except Exception:
            line = None
        if not line or _trio_usable(line, pet_classes) is False:
            continue
        if not re.search(r"AC: *[0-9]|DMG: *[0-9]|Skill:", line):
            continue
        if re.search(r"No Drop|NO DROP|NODROP", line):
            continue
        pool.append((nm, line))
    try:
        shortlist = await _pet_shortlist(pool, pet_inv, pet_slots)
    except Exception:
        logger.exception("builtin pet shortlist failed")
        return []
    out, claimed = [], set()
    for e in shortlist:
        if e["verdict"] != "clear upgrade" or len(out) >= pet_slots:
            continue
        cat = e["cat"]
        if cat in claimed:
            continue
        if cat:
            claimed.add(cat)
        gains = ", ".join(f"{k} {v:+g}" for k, v in
                          sorted(e["gain"].items(), key=lambda kv: -abs(kv[1])))
        out.append({"item": e["cand"], "slot": "",
                    "why": (f"beats held {e['vs']} on every stat a pet uses "
                            f"({gains}) and loses nothing" if e["vs"] else
                            f"fills a free pet slot ({gains})")})
    return out


def _aa_meta(classes: List[str]) -> dict:
    """name(lower) -> {maxRank, ladder} from eqlbuilds. `ladder` is the
    per-rank magnitude sequence parsed from descriptions like
    "memorize 1 / 2 / 3 / 4 / 5 / 6 additional spell" — used to recover the
    OWNED rank (the log shows the current value, never a rank number)."""
    from backend import builds_data
    out: dict = {}
    for cls in classes or []:
        for a in builds_data.class_aas(cls) or []:
            nm = a.get("name")
            if not nm:
                continue
            desc = a.get("description") or ""
            m = re.search(r"(\d+(?:\s*/\s*\d+){2,})", desc)
            ladder = ([int(x) for x in re.findall(r"\d+", m.group(1))]
                      if m else [])
            out[nm.lower()] = {"max": a.get("maxRank"), "ladder": ladder}
    return out


def _owned_rank(desc: str, meta: dict) -> Optional[int]:
    """Recover the owned rank: the position in the eqlbuilds ladder whose
    value matches the number in the log's current-rank description."""
    ladder = (meta or {}).get("ladder") or []
    if not ladder or not desc:
        return None
    # numbers in the log desc that aren't themselves a slash-ladder
    nums = [int(x) for x in re.findall(r"\d+", re.sub(r"\d+(\s*/\s*\d+)+", "", desc))]
    for n in nums:
        if n in ladder:
            return ladder.index(n) + 1
    return None


def _gate_stacking(picks: List[dict]) -> tuple:
    """Drop buffs that would overwrite each other.

    EQ buffs occupy effect SLOTS; two spells in the same slot do not add, the
    second simply replaces the first. A loadout holding both Center and
    Bravery (both ac-slot-1) has therefore spent a gem on nothing, and the
    SPA-based supersession check cannot see it — slot occupancy is not in the
    effect data.

    Keeps the STRONGEST spell per slot (curated lines run weakest to
    strongest) regardless of the order the model proposed them, since that is
    what the player would actually end up with. Spells outside the curated
    table are always kept: absence of data is not evidence of a conflict.

    Returns (kept, dropped) where each dropped entry carries the slot and the
    spell that displaced it.
    """
    from backend import spell_lines

    kept: List[dict] = []
    dropped: List[dict] = []
    claimed: dict = {}   # slot -> (position, index into kept)
    for pick in picks:
        name = str(pick.get("name") or "")
        slots = spell_lines.slots_for(name)
        if not slots:
            kept.append(pick)
            continue
        # EVERY claimed slot has to be considered, not the first one found.
        # Skin like Steel occupies both ac-slot-1 and the druid hp/ac line;
        # stopping at the first meant it displaced Center and never looked
        # at the line where Skin like Rock was still sitting, so the pair it
        # was supposed to replace survived alongside it.
        beaten_by = None                 # slot where this pick is the weaker
        displaces = []                   # (slot, index) this pick outranks
        for slot, position in slots.items():
            held = claimed.get(slot)
            if held is None:
                continue
            held_pos, held_idx = held
            if position > held_pos:
                displaces.append((slot, held_idx))
            else:
                beaten_by = slot
                break
        if beaten_by is not None:
            dropped.append({**pick, "conflict_slot": beaten_by,
                            "conflict_with": kept[claimed[beaten_by][1]]["name"]})
            continue
        if displaces:
            # Tombstone rather than remove: `claimed` holds indices into
            # `kept`, and compacting the list mid-loop invalidates them.
            for slot, idx in displaces:
                if kept[idx] is None:
                    continue
                dropped.append({**kept[idx], "conflict_slot": slot,
                                "conflict_with": name})
                kept[idx] = None
            idx = displaces[0][1]
            kept[idx] = pick
            for sl_, pos_ in slots.items():
                claimed[sl_] = (pos_, idx)
            continue
        kept.append(pick)
        for sl_, pos_ in slots.items():
            claimed[sl_] = (pos_, len(kept) - 1)
    return [k for k in kept if k is not None], dropped


def _gate_aas(items: List[dict], owned: dict, meta: dict) -> List[dict]:
    """Drop AA recs the character can't act on. Owned rank is RECOVERED from
    the eqlbuilds ladder (the log's rank counter is unreliable — it just
    counts list-bursts), so maxed AAs (Mnemonic Retention 6/6) and
    already-owned ranks are dropped, and ranks beyond max are dropped."""
    omap = {k.lower(): v for k, v in owned.items()} if owned else {}
    out = []
    for it in items:
        name = str(it.get("name") or "")
        m = re.search(r"^(.*?)[\s(]+ranks?\s*(\d+)\s*[)]?\s*$", name, re.I)
        base = (m.group(1) if m else name).strip().rstrip("(").strip()
        want = int(m.group(2)) if m else None
        # The AA must EXIST. This gate only ever checked RANKS, so an
        # invented name sailed through both here and, before that, via the
        # `if not owned: return items` shortcut that skipped verification
        # entirely for anyone who had never typed /alternateadv list.
        # Observed live: "General - 3 pts" and "Horizon Prep - 12 pts",
        # neither of which is an AA in any class's list -- they read like
        # the model echoing an ability CATEGORY and this prompt's own
        # "horizon" section label back as if they were purchasable.
        # Enforced only when the snapshot is present: with no data we
        # cannot tell an invented name from an unlisted one, and the house
        # rule is that absence of data is not evidence.
        if meta and base.lower() not in meta:
            logger.info("Dropped AA rec — not an AA in the class data: %s",
                        name)
            continue
        o = omap.get(base.lower())
        mt = meta.get(base.lower()) or {}
        cap = mt.get("max")
        have = _owned_rank((o or {}).get("desc", ""), mt) if o else None
        if want is not None and cap and want > cap:
            logger.info("Dropped AA rec — rank beyond max (%s/%s): %s",
                        want, cap, name)
            continue
        if o and have is not None:
            if want is not None and have >= want:
                logger.info("Dropped AA rec — rank %s already owned: %s",
                            want, name)
                continue
            if want is None and cap and have >= cap:
                logger.info("Dropped AA rec — already maxed (%s/%s): %s",
                            have, cap, name)
                continue
        out.append(it)
    return out


_VIABLE_MEMO: dict = {}
WIKI_CAP = 20000


def _trim_wiki(wiki: str, pregated: dict) -> str:
    """Drop wiki rows for spells the pre-gate already removed.

    The wiki block lists every class spell in a level window WITH its effect
    text, which is why it is worth ~5k tokens: that prose is how the model
    explains a pick. But a spell that cannot be chosen -- superseded, a travel
    ritual, a solo-dead resurrection -- is paying for prose nobody will read.

    Rows for spells the character OWNS AND CAN STILL PICK are kept: the
    spellbook section carries only name and level, so removing these would
    blind the model to what its own spells do.
    """
    if not wiki or not pregated:
        return wiki
    dead = {n.lower() for n in pregated}
    out, cut = [], 0
    for line in wiki.splitlines():
        m = re.match(r"^L\d+ ([^\[]+)\[", line)
        if m and m.group(1).strip().lower() in dead:
            cut += len(line) + 1
            continue
        out.append(line)
    if cut:
        logger.info("Trimmed %d chars of wiki prose for %d pre-gated spells",
                    cut, len(dead))
    return "\n".join(out)


def _fit_wiki(wiki: str, budget: int) -> str:
    """Fit the wiki context to `budget` WITHOUT starving whole sections.

    build_wiki_context truncates its tail, and the tail is the AA list. At the
    real 12,000-char budget that sent 0 of 73 AA entries while the prompt still
    asked for aa_now/aa_save "using the per-rank costs in the data" -- advice
    with no data behind it. Two skill-cap sections vanished the same way.

    So share the budget across sections instead of cutting the end off: every
    section keeps a floor, the remainder is split in proportion to what each
    asked for, and anything actually dropped is named in the text so the model
    knows the list is partial rather than complete.
    """
    if not wiki or len(wiki) <= budget:
        return wiki
    parts = re.split(r"\n(?=##+ )", wiki)
    if len(parts) < 2:
        return wiki[:budget]
    FLOOR = 700
    MARK = ("... (%d more entries not shown — this list is PARTIAL, do not "
            "treat it as complete)")
    marker_cost = len(MARK % 0) + 4        # the note itself costs budget too
    total = sum(len(p) for p in parts)
    spare = max(0, budget - (FLOOR + marker_cost) * len(parts))
    out, trimmed = [], []
    for p in parts:
        share = FLOOR + int(spare * len(p) / total)
        if len(p) <= share:
            out.append(p)
            continue
        head, body = (p.split("\n", 1) + [""])[:2]
        keep, used = [head], len(head)
        for line in body.splitlines():
            if used + len(line) + 1 > share:
                break
            keep.append(line)
            used += len(line) + 1
        dropped_n = len(body.splitlines()) - (len(keep) - 1)
        keep.append(MARK % dropped_n)
        trimmed.append(f"{head.strip('# ').split(':')[0][:40]}: {dropped_n}")
        out.append("\n".join(keep))
    res = "\n".join(out)
    if len(res) > budget:                  # belt and braces; never overshoot
        res = res[:budget]
        logger.info("Wiki context hard-clamped to %d chars", budget)
    logger.info("Wiki context fitted to %d chars; partial sections: %s",
                budget, "; ".join(trimmed) or "none")
    return res


async def _viable_candidates(names: List[str], solo: bool) -> tuple:
    """Owned+castable spells that could actually SURVIVE the output gates.

    `_gate_picks` already drops travel rituals, solo-dead resurrection lines
    and anything superseded by another owned spell -- but it runs AFTER the
    model has spent loadout slots on them, so those slots silently vanish
    from the answer. Measured on a real book: 33 of 91 usable spells (36%)
    were dead on arrival.

    Running the same tests BEFORE the prompt means the model only ever sees
    real options. `_gate_picks` stays as the backstop; it should now be quiet.

    Cost is one O(n^2) supersession sweep, 0.56s cold and 0.05s warm because
    the spell records are cached -- paid once, against a multi-second LLM call.
    Returns (live, dropped) where dropped maps name -> why, so nothing is
    filtered silently.
    """
    key = (tuple(sorted(names)), solo)
    if key in _VIABLE_MEMO:
        return _VIABLE_MEMO[key]
    dropped: dict = {}
    for n in names:
        try:
            if await is_travel_ritual(n):
                dropped[n] = "travel ritual (cast from the RITUALS system)"
                continue
        except Exception:
            pass
        if solo:
            try:
                if await is_resurrection(n):
                    dropped[n] = "resurrection line (dead slot when solo)"
                    continue
            except Exception:
                pass
    live_pool = [n for n in names if n not in dropped]
    for a in live_pool:
        for b in live_pool:
            if a == b or a in dropped:
                continue
            try:
                if await supersedes_for_slots(a, b):
                    dropped[a] = f"superseded by owned {b}"
                    break
            except Exception:
                continue
    live = [n for n in names if n not in dropped]
    if dropped:
        logger.info("Pre-gated %d of %d owned spells before prompting: %s",
                    len(dropped), len(names),
                    "; ".join(f"{k} ({v})" for k, v in list(dropped.items())[:12]))
    _VIABLE_MEMO[key] = (live, dropped)
    return live, dropped


async def generate_advice(ctx: dict) -> dict:
    classes = [c.strip() for c in (ctx.get("class_str") or "").split("/") if c.strip()]
    book = ctx.get("spellbook")
    base = {
        "generated": datetime.now().isoformat(timespec="seconds"),
        "context": {
            "classes": ctx.get("class_str"), "level": ctx.get("level"),
            "playstyle": ctx.get("playstyle"), "zone": ctx.get("zone"),
            "aa_available": ctx.get("aa_available"),
            "spell_slots": ctx.get("spell_slots"),
            "spellbook_file": book["file"] if book else None,
            "spellbook_age_hours": book["age_hours"] if book else None,
            "spellbook_count": len(book["castable"]) if book else None,
        },
    }
    wiki = ""
    try:
        # owned-state lines are large; keep the wiki share smaller when present
        try:
            ctx["_hunting"] = (await hunting_candidates(int(ctx["level"]))
                               if ctx.get("level") else [])
        except Exception:
            ctx["_hunting"] = []
        ctx["_permanent"] = _permanent_buffs(ctx)
        ctx["_long_buffs"] = _long_buffs(ctx)
        ctx["_no_pet"] = not _summons_a_pet(classes)
        ctx["_measured"] = _measured_damage(ctx)
        # Deterministic pre-pass: only offer the model spells that can survive
        # its own output gates, so a loadout slot is never spent on a pick
        # that gets dropped afterwards.
        ctx["_viable"], ctx["_pregated"] = [], {}
        if book and ctx.get("level") is not None:
            try:
                _names = [s["name"] for s in book["castable"]
                          if s["level"] <= ctx["level"]]
                ctx["_viable"], ctx["_pregated"] = await _viable_candidates(
                    _names, (ctx.get("playstyle") or "").startswith("solo"))
            except Exception:
                logger.exception("pre-gate failed; prompting with the full book")
                ctx["_viable"], ctx["_pregated"] = [], {}
        if llm_active()["provider"] == "none":
            body = await _builtin_counsel(ctx)
            base["grounding"] = body.pop("grounding", "memory")
            return {**base, **body}
        # Fetch UNTRUNCATED, drop what the pre-gate made unpickable, then fit
        # to budget across sections. Asking build_wiki_context to truncate
        # cuts its tail, and the tail is the AA list -- so aa_now/aa_save were
        # being answered from 0 of 73 AA entries.
        _budget = 12_000 if ctx.get("spellbook") else 20_000
        wiki = await build_wiki_context(classes, ctx.get("level"),
                                        max_chars=100_000)
        wiki = _fit_wiki(_trim_wiki(wiki, ctx.get("_pregated") or {}), _budget)
    except Exception:
        logger.exception("Wiki context failed; advising ungrounded")
    base["grounding"] = "wiki" if wiki else "memory"

    try:
        # Thinking models burn a large reasoning budget BEFORE emitting the
        # answer (gemma ~4-5k reasoning tokens here) and it counts against
        # completion tokens — so size everything to the LOADED context.
        prompt = _build_prompt(ctx, wiki)
        budget = await asyncio.to_thread(_lmstudio_budget, len(prompt))
        if budget and budget < 3000:
            # context too small for the full prompt + thinking: shrink wiki
            wiki = wiki[:5000]
            prompt = _build_prompt(ctx, wiki)
            budget = await asyncio.to_thread(_lmstudio_budget, len(prompt))
        llm = get_llm()
        bound = llm
        if budget:
            try:
                bound = llm.bind(max_tokens=budget)
            except Exception:
                pass
        try:
            response = await bound.ainvoke([HumanMessage(content=prompt)])
        except Exception as first_err:
            # whatever slipped through: retry once, half the prompt + budget
            logger.warning("Advisor first attempt failed (%.80s); retrying "
                           "smaller", str(first_err))
            prompt = _build_prompt(ctx, wiki[:4000])
            if budget:
                try:
                    bound = llm.bind(max_tokens=max(1200, budget // 2))
                except Exception:
                    pass
            response = await bound.ainvoke([HumanMessage(content=prompt)])
        raw = _reply_text(response)
        data = _extract_json(raw)
        if not data:
            raise ValueError(_no_json_reason(response, raw))
        _warn_if_truncated(prompt, data)
        solo = (ctx.get("playstyle") or "").startswith("solo")
        usable = ([s["name"] for s in book["castable"]
                   if s["level"] <= ctx["level"]]
                  if (book and ctx.get("level") is not None) else [])
        allowed = {n.lower() for n in usable} if usable else None

        async def _gate_picks(picks, label):
            """Owned + level-legal, not a travel ritual, and not superseded
            by another owned usable spell. Spell records are cached, so the
            pairwise scan is only slow on the first consult of the day."""
            out = []
            for s in picks:
                name = s["name"]
                if allowed is not None and name.lower() not in allowed:
                    logger.info("Dropped over-level/unowned %s pick: %s",
                                label, name)
                    continue
                try:
                    if await is_travel_ritual(name):
                        logger.info("Dropped travel ritual from %s: %s",
                                    label, name)
                        continue
                except Exception:
                    pass
                if solo:
                    try:
                        if await is_resurrection(name):
                            logger.info("Dropped resurrection spell from solo "
                                        "%s: %s", label, name)
                            continue
                    except Exception:
                        pass
                superseded = None
                for other in usable:
                    if other.lower() == name.lower():
                        continue
                    try:
                        if await supersedes_for_slots(name, other):
                            superseded = other
                            break
                    except Exception:
                        continue
                if superseded:
                    logger.info("Dropped %s pick %s — superseded by owned %s",
                                label, name, superseded)
                    continue
                out.append(s)
            return out

        must_have = _gate_pet_spells(await _gate_picks(
            _clean_list(data.get("must_have"), ("name", "cls", "reason"), cap=10),
            "must_have"), classes)
        should_have = _gate_pet_spells(await _gate_picks(
            _clean_list(data.get("should_have"), ("name", "cls", "reason"), cap=14),
            "should_have"), classes)
        nice_to_have = _gate_pet_spells(await _gate_picks(
            _clean_list(data.get("nice_to_have"), ("name", "cls", "reason"), cap=16),
            "nice_to_have"), classes)
        # Buff SLOTS: drop picks that would overwrite each other. Run across
        # must_have + should_have together (they are one slot fill) and
        # BEFORE the promote step, so a freed gem refills from alternatives.
        from backend import spell_lines as _lines
        _fill, _clashes = _gate_stacking(must_have + should_have)
        for d in _clashes:
            logger.info("Dropped %s — same buff slot (%s) as %s, which would "
                        "overwrite it", d["name"], d["conflict_slot"],
                        d["conflict_with"])
        if _clashes:
            _keep = {str(x["name"]).lower() for x in _fill}
            must_have = [x for x in must_have if str(x["name"]).lower() in _keep]
            should_have = [x for x in should_have
                           if str(x["name"]).lower() in _keep]
            # anything promoted back in must not re-create the same clash
            _promoted = [x for x in _fill
                         if str(x["name"]).lower()
                         not in {str(y["name"]).lower()
                                 for y in must_have + should_have}]
            should_have.extend(_promoted)
        # Top up the alternatives BEFORE promoting from them. The backfill
        # used to run afterwards, so when a gate emptied nice_to_have there
        # was nothing left to promote and the loadout came back a slot
        # short -- 13 of 14, with the shortfall unexplained.
        if len(nice_to_have) < 12:
            _picked = {p.get("name") for p in
                       must_have + should_have + nice_to_have}
            nice_to_have = nice_to_have + await _extra_alternatives(
                ctx, _picked, 12 - len(nice_to_have))
        # auto-promote: gates may have removed picks — refill the slots from
        # the nice-to-have alternatives (they passed the same gates)
        slots_n = ctx.get("spell_slots")
        if slots_n:
            while len(must_have) + len(should_have) < slots_n and nice_to_have:
                promoted = nice_to_have.pop(0)
                if _lines.find_conflicts(
                        [str(x["name"]) for x in must_have + should_have]
                        + [str(promoted.get("name"))]):
                    continue  # would overwrite something already picked
                promoted = {**promoted,
                            "reason": "(promoted alternative) " + str(promoted.get("reason", ""))}
                should_have.append(promoted)
        # An "alternative" you have already been told to memorize is not an
        # alternative. Duplicates arrive two ways: the model lists a spell
        # in both tiers, and the promote step moves one from here into
        # should_have. Filtered once, at the end, after both have happened.
        _slotted = {str(x.get("name")).lower()
                    for x in must_have + should_have}
        nice_to_have = [x for x in nice_to_have
                        if str(x.get("name")).lower() not in _slotted]
        # annotate every pick with its spellbook level (deterministic)
        level_by_name = {s["name"].lower(): s["level"]
                         for s in (book["castable"] if book else [])}
        for lst in (must_have, should_have, nice_to_have):
            for s in lst:
                s["level"] = level_by_name.get(str(s["name"]).lower())
        loadout = must_have + should_have  # combined = the actual slot fill
        prebuffs = _describe_prebuffs(_annotate_stacking(_gate_pet_spells(_backfill_prebuffs(_gate_prebuffs(await _gate_picks(
            _clean_list(data.get("prebuffs"), ("name", "cls", "reason"), cap=8),
            "prebuffs")), ctx), classes), ctx))
        # Long-duration buffs are the worst place to stack two of a slot: the
        # second cast silently wastes the first one's mana and duration.
        prebuffs, _pre_clashes = _gate_stacking(prebuffs)
        for d in _pre_clashes:
            logger.info("Dropped prebuff %s — %s occupies the same slot (%s)",
                        d["name"], d["conflict_with"], d["conflict_slot"])
        prebuffs = _cap_prebuffs(prebuffs, ctx)
        for s in prebuffs:
            s["level"] = level_by_name.get(str(s["name"]).lower())
        replace = _clean_list(data.get("replace"), ("using", "upgrade", "why"),
                              cap=8, require="using")
        verified = []
        for p in replace:
            try:
                if (p.get("upgrade")
                        and not await is_travel_ritual(p["using"])
                        and not await is_travel_ritual(p["upgrade"])
                        and await same_spell_line(p["using"], p["upgrade"])):
                    # Point the pair at the best thing they can cast NOW,
                    # not merely at something better than what they named,
                    # and drop it entirely when they are already on it.
                    path = _upgrade_path(p["using"], ctx)
                    if path:
                        if path["at_best"]:
                            logger.info("Dropped replace pair: already on the "
                                        "best owned %s", p["using"])
                            continue
                        p["upgrade"] = path["best"]
                        p["next"] = path["next"]
                        p["next_level"] = path["next_level"]
                    verified.append(p)
                else:
                    logger.info("Dropped unverified replace pair: %s -> %s",
                                p.get("using"), p.get("upgrade"))
            except Exception:
                pass  # verification unavailable — drop rather than mislead
        if len(nice_to_have) < 12:
            picked = {p.get("name") for p in
                      must_have + should_have + nice_to_have + prebuffs}
            nice_to_have = nice_to_have + await _extra_alternatives(
                ctx, picked, 12 - len(nice_to_have))
        return {
            **base, "source": "llm",
            "note": data.get("note"),
            "loadout": loadout,
            "must_have": must_have,
            "should_have": should_have,
            "nice_to_have": nice_to_have,
            "prebuffs": prebuffs,
            "replace": verified,
            "aa_now": _gate_aas(
                _clean_list(data.get("aa_now"), ("name", "cost", "reason"), cap=6),
                ctx.get("owned_aas") or {}, _aa_meta(classes)),
            "aa_save": _gate_aas(
                _clean_list(data.get("aa_save"), ("name", "cost", "reason"), cap=4),
                ctx.get("owned_aas") or {}, _aa_meta(classes)),
            "horizon": _clean_list(data.get("horizon"), ("level", "cls", "name", "reason"), cap=8),
            "locations": _gate_locations(
                _clean_list(data.get("locations"), ("zone", "why", "notable"),
                            cap=5, require="zone"),
                ctx.get("_hunting") or []),
            "class_notes": _clean_list(data.get("class_notes"), ("topic", "advice"),
                                       cap=6, require="topic"),
        }
    except Exception as e:
        logger.warning("Advisor LLM unavailable, using fallback: %.140s", str(e))
        try:
            body = await _builtin_counsel(ctx)
            base["grounding"] = body.pop("grounding", "memory")
            body["note"] = (f"LLM unavailable ({str(e)[:60]}) — showing "
                            "deterministic counsel instead. " + BUILTIN_NOTE)
            return {**base, **body}
        except Exception:
            return {**base, "source": "builtin", **_fallback_body(ctx, str(e)[:80])}


# --------------------------------------------------------------------- gear

GEAR_PROMPT = """You are the equipment advisor inside an EverQuest Legends companion app. EQL is a reimagined pre-Kunark EverQuest. A character runs THREE classes, and gear is equippable when ANY ONE of those classes can use it — one match is enough, it stays equipped across class swaps. Each item below is pre-marked [USABLE] or [NOT USABLE by this trio]; NEVER re-derive class eligibility yourself and NEVER reject a [USABLE] item because some of the trio cannot use it.
Recommend a TWO-HANDER for Primary ONLY when it beats the current primary AND secondary COMBINED — the off-hand goes empty — and say that comparison in the why.
CRITICAL — upgrade ranks: each item's stats are ALREADY SCALED to the +N in its name, using the wiki's own item-level formula (primary stats gain ~10% of base per level, or +1/level when the base is <=10; DMG gains floor(base*N/10); items with 2+ stats gain an emergent "SV VOID: +N" resist). Compare the printed numbers DIRECTLY — a higher +N does NOT automatically win, and a strong +0 item can honestly beat a worn +2. Unowned drops you suggest in "farm" start at +0, so quote base values for those. Items marked STATS UNKNOWN have no data at all — NEVER invent their stats and NEVER recommend replacing them (you cannot make an honest comparison).

Paired slots: "Ear 1"/"Ear 2", "Wrist 1"/"Wrist 2", "Fingers 1"/"Fingers 2", "Any Slot 1"/"Any Slot 2" hold TWO independent items each — treat each numbered slot separately and remember both currently-worn items of a pair are listed. The two "Any Slot"s are EQL's generic slots: ANY equippable item can sit there (weapons included) and its stats apply, so recommend the best owned items that don't fit elsewhere; also consider "Ammo" and "Held" if something owned is worth parking there.

CHARACTER
__CONTEXT__

OWNED EQUIPMENT (from /outputfile inventory; [worn/bags/bank] shows where each lives; stats and drop sources are from the game's wiki):
__GEAR__

EXALTATIONS (socketable effect-stones extracted from items — for CONTEXT only; the app reports them separately, do NOT recommend moving them). Stones move between owned items at NO cost (within class/slot legality), so when comparing two OWNED items for a slot, IGNORE any socketed stone that could legally move to the challenger — the stone follows the winner. Count a stone toward its host's value only when it could NOT legally move. LEGALITY IS NARROW, and it is NOT "any item with a free socket": a FOCUS, WORN or CLICKY stone may only move to an item that shares an equipment SLOT with the stone's own base item — a Robe stone fits CHEST items and nothing else — while a PROC stone needs a weapon. The app computes the legal destinations for every socketed stone and states them on its host's GEAR LINE as "may ONLY move to: ..." (or "CANNOT be moved"). NEVER claim a stone can be moved without naming a destination from that line, and never write vague permission like "move it into any other open-focus item" — if the gear line lists no destination, the stone stays where it is and its value stays with its host. When you recommend replacing an item whose stone CANNOT move to the replacement, the 'why' must say what is being given up, by name — a swap that strands a focus is NEVER "no loss of other stats", and phrasing it that way is the single worst error you can make here, because the stats are the part the player can already see. PROC stones may only fire from the PRIMARY slot (confirmed for several stones): never count a proc as value on an item you recommend for Secondary or Range, and when a swap strands a proc stone off-primary, say so in the why (e.g. "move its stone into your primary first"). A stone adds value ONLY while usable by the trio AND its level requirement is met; DORMANT/unusable stones are zero. Item Effect lines follow the same rule — "at Level N" effects below the character's level are worth nothing yet. HOW AN ITEM'S EFFECT WORKS: the "Effect:"/"Focus Effect:" line on a gear line is that item's OWN effect and applies on its own — a robe listing "Focus Effect: Spell Haste II" really is giving 15% cast time. That effect is delivered by an exaltation built into the item, and the SOCKET holding it is only exposed once the item has been LEVELLED: an item at +0 has no focus socket at all, so its effect cannot be extracted or moved anywhere. A socketed stone OVERRIDES the item's own effect, so when a gear line also says "HOSTS EXALTATION: ... granting X", X is what that item actually does and its printed Effect line does not apply; the app flags that case for you. REPLACING an item costs you whatever it grants — its own effect, or the stone's if one overrides — so a swap away from an item with an effect is never free, and the 'why' must name what is lost. If the item being replaced is +0, say that the focus cannot be moved at all and that merging the item first is what would preserve it. The replacement's effect, if it has one, is what you get instead; if it has none, say so.
__EXALTS__

__PET_BLOCK__

Reply with ONLY a JSON object (no fences, no prose):
{
  "note": "one-sentence overall read of their gearing, or null",
  "slots": [{"slot": "Chest", "current": "...", "recommend": "...", "why": "..."}],
  "farm": [{"item": "...", "slot": "...", "zone": "...", "source": "...", "why": "..."}],
  "pet_gear": [{"item": "...", "slot": "...", "why": "..."}]
}

Rules:
- slots: go slot by slot; only include a slot when there is something to say — a better OWNED item sitting in bags/bank than what is worn ("recommend" = that owned item, exactly as named above), an empty slot they own a filler for, or a confirmation that the worn item is their best ("recommend" = the worn item). Recommend only [USABLE] items; the tag is authoritative. Race restrictions DO NOT EXIST in EQL. Anything marked [worn] is being worn RIGHT NOW and is proven equippable — never claim a worn item is unusable.
- Stat-delta language: you know the character's totals ONLY when CHARACTER lists them (Max HP / Max mana / recent combat). NEVER label a stat change "huge", "massive", "tiny", "minor" or similar on its own authority — give the numbers. When Max HP is listed, express HP deltas as a rough percentage of it ("+75 HP ≈ +5.6% of your 1342"); when recent-combat numbers are listed, you may translate HP deltas into average incoming hits ("+75 HP ≈ 2 average hits of survival"). With neither, state the delta neutrally and let the numbers speak.
- ANY SLOT gives STATS ONLY. A weapon placed there contributes NO damage, NO delay and NO white-DPS index -- it is not swung. Judge an Any Slot purely on AC, attributes, resists and effects, and NEVER compare white-DPS indices for it; those numbers apply to Primary and Secondary alone. The ONE exception: a Piercing dagger in an Any Slot enables Backstab when the trio contains a class that can backstab (Rogue), so say so if that applies. A weapon can still be the best Any Slot item when its STATS beat the alternatives.
__DUAL_WIELD__- Hands: a weapon with a 2H skill (2H Slash/2H Blunt/2H Piercing) occupies BOTH Primary and Secondary. Never recommend a 2H weapon together with any Secondary item; compare 1H+1H (or 1H+shield) as a package against the 2H alone.
- farm: 3-6 realistic upgrade targets for their level. STRONGLY prefer items whose drop data appears above or that you know drop in zones near their level; give the zone and the mob/vendor in "source". Never invent stats; mark uncertainty briefly in "why" when relying on memory.
- Weapons: consider the classes' usable weapon skills; for a Monk trio prefer fist/blunt options. 1H weapon lines carry deterministic [white-DPS index: MH x / OH y] — USE THEM instead of raw damage/delay ratio: the main-hand damage bonus is a flat, delay-independent add (fast MH weapons carry it more often), the off-hand gets NO bonus and swings only part of the time, so the best MH is often NOT the best OH. Procs are NOT in the index — a strong proc can outweigh a small index gap. Proc rate is a PROCS PER MINUTE budget, NOT a per-swing roll: a faster weapon does not proc more often, so never argue that speed increases procs. What changes is how many hands carry a budget — the main hand gets the full rate and the off-hand HALF, so dual wielding yields about 1.5x the procs of a two-hander. Weapon lines with a combat effect carry [procs/min: ...] when the character's DEX is known; if that annotation is absent, DEX is unknown and you must not state a proc rate. For 2H: compare its DPS against the MH index + OH index SUM plus the stat difference, and against that proc gap.
- exaltations: review where each exaltation is socketed vs what it grants. Recommend moves ONLY when clearly better (an unused bank exaltation with a strong effect, or an effect wasted on unused gear); "move_to" = the item to socket it into. Skip trivial shuffles; note uncertainty about socket compatibility.
"""


# The Inventory export's socket NUMBER is the game-authoritative socket
# type (Slot7..Slot10 child rows on gear — mapping per Velkenn/EQL-
# Effects-Finder). Bag positions reuse small numbers, so the number is
# only trusted when the stone's parent row is GEAR, not a container.
SOCKET_TYPES = {7: "focus", 8: "clicky", 9: "worn", 10: "proc"}
_SOCKET_NUM = {v: k for k, v in SOCKET_TYPES.items()}


def _socket_type_from_export(x: dict) -> Optional[str]:
    """Trust the socket number as a TYPE only when the stone sits in real
    GEAR — loose stones in bags reuse 1-10 as bag POSITIONS (a stone at
    bag position 8 is not a clicky). Gear = worn slot, or a bank/bag row
    that actually holds a host item (never a Backpack)."""
    from backend.spellbook import WORN_SLOTS
    hl = str(x.get("host_loc") or "")
    host = str(x.get("host") or "")
    in_gear = (hl in WORN_SLOTS
               or (host and "backpack" not in host.lower()
                   and not hl.lower().startswith("general")))
    return SOCKET_TYPES.get(x.get("socket")) if in_gear else None


def _exalt_socket_type(effect: Optional[str]) -> str:
    """focus / clicky / worn / proc from the wiki Effect line's wording.
    Socket taxonomy per eqlegendstools.com."""
    if not effect:
        return "unknown"
    low = effect.lower()
    if "combat" in low or "proc" in low:
        return "proc"
    if "worn" in low:
        return "worn"
    if "focus" in low:
        return "focus"
    if "casting time" in low or "must equip" in low or "any slot" in low             or "triggered" in low:
        return "clicky"
    return "unknown"


async def _exalt_effect(base_item: str) -> Optional[str]:
    """The effect line an exaltation grants = its base item's Effect."""
    from backend.game_data import item_line
    line = await item_line(base_item)
    if not line:
        return None
    m = re.search(r"(?:Focus )?Effect: [^;|]+", line)
    return m.group(0) if m else "no listed effect (stat stone?)"


# every equippable slot in the EQL inventory export — the gear table always
# shows all 24, backfilling slots the LLM didn't address. "Any Slot" x2 are
# EQL's generic slots (hold any equippable item); no Charm/Power Source here.
_CAPPED_STATS = ("STR", "STA", "AGI", "DEX", "WIS", "INT", "CHA")


def _stat_headroom(ctx: dict) -> dict:
    """How many points of each attribute are still worth having.

    EQL caps attributes at 510 and the Inventory panel prints "STR 196/510",
    so when the stats OCR is running we know the headroom exactly. A point
    past the cap does nothing, and gear advice that cannot see that will
    happily recommend an item for stats with no effect.

    Empty when there is no reading -- unknown must behave exactly as before,
    never as "no headroom", which would discard every attribute from every
    comparison.
    """
    st = ctx.get("ocr_stats") or {}
    out = {}
    for k in _CAPPED_STATS:
        cur, cap = st.get(k.lower()), st.get("cap_" + k.lower())
        if isinstance(cur, int) and isinstance(cap, int) and cap > 0:
            out[k] = max(0, cap - cur)
    return out


def _effective_vecs(cand: dict, worn: dict, ctx: dict) -> tuple:
    """Rewrite both vectors as what each item would ACTUALLY deliver.

    Naive clamping against the remaining headroom is wrong for a swap: the
    current total already includes the worn item, so taking it off frees
    room the candidate can use. The honest figure is each item's marginal
    contribution over the total WITHOUT it --

        base      = current - worn
        effective = min(cap, base + item) - base

    -- which values a +40 STR piece at 40 when there is room, at whatever
    is left when there is little, and at 0 when the rest of your gear
    already caps the stat. An item offering nothing but capped attributes
    then correctly ties with an empty slot instead of winning.

    Returns the pair unchanged when no reading exists: unknown must behave
    exactly as it did before, never as "no headroom".
    """
    st = ctx.get("ocr_stats") or {}
    if not st:
        return cand, worn
    c, w = dict(cand), dict(worn)
    for key in _CAPPED_STATS:
        cur, cap = st.get(key.lower()), st.get("cap_" + key.lower())
        if not (isinstance(cur, int) and isinstance(cap, int) and cap > 0):
            continue
        worn_v = float(worn.get(key, 0.0))
        base = max(0.0, cur - worn_v)
        for vec, src in ((c, cand), (w, worn)):
            v = float(src.get(key, 0.0))
            if v > 0:
                vec[key] = max(0.0, min(cap, base + v) - base)
    return c, w


def _upgrade_path(using: str, ctx: dict) -> Optional[dict]:
    """Where a spell sits in its line, and what is actually next.

    An upgrade warning is only useful if it points at the best thing you
    can cast TODAY. Reported at level 25: "Minor Healing -> Light Healing",
    while Healing -- two steps further up the same line and long since
    scribed -- sat in the book. The pair was verified as a real same-line
    upgrade and was still nearly useless, because nothing checked whether
    the player was already past BOTH ends of it.

    Returns the best owned-and-castable spell in the line, and the next one
    beyond it with the level it unlocks at, so the warning can say where
    you are and where you are going.
    """
    from backend import spell_lines
    book = ctx.get("spellbook") or {}
    level = ctx.get("level")
    castable = book.get("castable") or []
    if not castable or not spell_lines.known(using):
        return None
    lvl_of = {s["name"].strip().lower(): s.get("level") for s in castable}
    slots = spell_lines.slots_for(using) or {}
    best = best_pos = best_line = None
    nxt = nxt_pos = nxt_level = None
    for line, _pos in slots.items():
        for cand in spell_lines.line_for(using, line):
            key = cand.strip().lower()
            if key not in lvl_of:
                continue  # not owned at all
            cl = lvl_of[key]
            here = spell_lines.slots_for(cand).get(line)
            if here is None:
                continue
            if level is not None and cl is not None and cl > level:
                # owned but not yet castable -- this is the "next" rung
                if nxt_pos is None or here < nxt_pos:
                    nxt, nxt_pos, nxt_level = cand, here, cl
                continue
            if best_pos is None or here > best_pos:
                best, best_pos, best_line = cand, here, line
    if best is None:
        return None
    return {"best": best, "next": nxt, "next_level": nxt_level,
            "at_best": best.strip().lower() == using.strip().lower()}


def _effect_shape(name: str):
    """The set of effects a buff actually applies, with its lead magnitude.

    Used only where the curated line table has no entry. That table is
    partial by design -- Protection of Rock is absent from it entirely --
    and two buffs applying the SAME set of effects to the same target are
    occupying the same slot whether or not anyone wrote it down. Reported
    from the game: casting Skin like Steel overwrites Protection of Rock,
    and both carry exactly effects 1, 69 and 79.

    Requires two or more effects: a single shared effect is common enough
    to be coincidence, and a wrong drop is worse than a missed note.
    """
    from backend import builds_data
    from backend.game_data import _primary_effect
    e = builds_data.spell_entry(name)
    if not e:
        return None
    ids = frozenset(x.get("effectId") for x in (e.get("effects") or [])
                    if x.get("baseValue"))
    if len(ids) < 2:
        return None
    pe = _primary_effect(e)
    return ids, abs((pe[1] if pe else 0) or 0)


def _annotate_stacking(picks: list, ctx: dict) -> list:
    """Say which buffs share a slot, and which of them wins.

    EQ buffs occupy effect slots and two spells in one slot overwrite each
    other -- Courage and Center are the same ac-slot-1, so casting both
    wastes the first. Nothing in game says so; you find out by casting them
    and watching one drop. The stacking data is already vendored and
    already used to GATE the loadout, so the only thing missing was saying
    it out loud.

    Also names the strongest thing in the same slot the player owns, which
    is how a druid buff quietly outranking a paladin one becomes visible.
    """
    from backend import spell_lines
    book = ctx.get("spellbook") or {}
    level = ctx.get("level")
    solo = (ctx.get("playstyle") or "").startswith("solo")
    owned = [b["name"] for b in book.get("castable", [])
             if level is None or b.get("level", 0) <= level]
    for p in picks:
        name = p.get("name") or ""
        slots = spell_lines.slots_for(name) or {}
        if not slots:
            # No curated entry -- but its TWIN may have one. The table knows
            # Skin like Wood and not Protection of Wood, so a solo player was
            # offered the group form of a buff two upgrades out of date:
            # nothing could compare it to anything. An OWNED spell applying
            # the identical effect set at the identical magnitude is the same
            # buff by another delivery, so it inherits that spell's verdict.
            # Paired on effect shape, never on the name -- "Protection of"
            # resembling "Skin like" is the reasoning the no-fuzzy rule
            # exists to prevent.
            sh = _effect_shape(name)
            for twin in (owned if sh else []):
                if twin.lower() == name.lower() or _effect_shape(twin) != sh:
                    continue
                beats = [o for o in owned
                         if o.lower() != twin.lower()
                         and spell_lines.supersedes(o, twin)]
                if beats:
                    p["superseded_by"] = beats[0]
                    p["_drop"] = True
                break
            continue
        beaten_by = [o for o in owned
                     if o.lower() != name.lower() and spell_lines.supersedes(o, name)]
        overwrites = [o for o in owned
                      if o.lower() != name.lower() and spell_lines.supersedes(name, o)]
        if beaten_by:
            p["superseded_by"] = beaten_by[0]
            p["_drop"] = True
        if overwrites:
            p["overwrites"] = sorted(overwrites)[:3]
    # A buff the player ALREADY OWNS a strict upgrade for is not a
    # recommendation, it is a distraction. Showing it dimmed with "skip
    # this one" beside it was reported as the list still carrying a
    # deprecated spell -- which is exactly what it was. The `overwrites`
    # note on the survivor still says what it replaced, so nothing is lost.
    # Fallback for spells the line table does not carry: identical effect
    # sets on two picks means one overwrites the other, and the larger lead
    # magnitude wins. Only among the picks themselves -- this is a note
    # about a list the player is about to cast, not a claim about the game.
    shapes = {}
    for p in picks:
        if p.get("_drop") or p.get("superseded_by"):
            continue
        sh = _effect_shape(p.get("name") or "")
        if not sh:
            continue
        ids, mag = sh
        prev = shapes.get(ids)
        if prev is None:
            shapes[ids] = (mag, p)
            continue
        if mag != prev[0]:
            keep, drop = (prev[1], p) if prev[0] > mag else (p, prev[1])
        else:
            # Same effect, same size: who it lands on is the only thing left
            # to choose by, so ask the focus rather than the list order.
            keep, drop = ((p, prev[1])
                          if _prefers_group(p.get("name") or "", solo)
                             > _prefers_group(prev[1].get("name") or "", solo)
                          else (prev[1], p))
        shapes[ids] = (max(prev[0], mag), keep)
        drop["_drop"] = True
        keep.setdefault("overwrites", []).append(drop.get("name"))
    return [p for p in picks if not p.pop("_drop", False)]


def _backfill_prebuffs(picks: list, ctx: dict) -> list:
    """Make sure the long defensive buffs are actually offered.

    The model was handed the list and still returned five permanents and two
    invisibility spells; Center and Skin like Steel -- 27 and 36 minutes of
    AC and hit points -- never appeared. A pre-buff section that omits the
    buffs you would actually cast before a pull is not doing its job, so the
    strongest few are added deterministically rather than left to chance.

    Ordered by magnitude of the primary effect so an upgrade wins its slot,
    and capped: this supplements the model's picks, it does not replace them.
    """
    from backend import builds_data
    from backend.game_data import _primary_effect
    have = {(p.get("name") or "").lower() for p in picks}
    level = ctx.get("level")
    cands = []
    for sp in (ctx.get("spellbook") or {}).get("castable", []):
        if level is not None and sp["level"] > level:
            continue
        if sp["name"].lower() in have:
            continue
        e = builds_data.spell_entry(sp["name"])
        if not e or (e.get("durationTicks") or 0) < 100:
            continue
        if not _is_prebuff(e):
            continue
        pe = _primary_effect(e)
        if not pe:
            continue
        cands.append({"name": sp["name"], "cls": sp.get("cls") or "",
                      "level": sp["level"], "_mag": abs(pe[1] or 0)})
    # Same ordering trap as _long_buffs: the weaker half of a line would
    # otherwise spend the slots its own upgrade needed.
    cands, _sup = _gate_stacking(cands)
    # Presentation order only. Magnitudes across DIFFERENT effects are not
    # comparable -- "hit points 50" over "armor class 21" over "strength 5"
    # ranks three unrelated numbers -- so this decides the order and must
    # not decide membership. It used to cap at 8, which is how Holy Armor,
    # Strength of Earth and Shield of Brambles went missing: small numbers,
    # real buffs, nothing superseding them. Supersession above has already
    # removed everything genuinely redundant, so what is left is offered.
    cands.sort(key=lambda c: -c["_mag"])
    for sp in cands[:16]:
        picks.append({"name": sp["name"], "cls": sp["cls"],
                      "level": sp["level"],
                      "reason": (_buff_effects(sp["name"]) or "long buff")
                                + " — worth re-casting between pulls"})
    return picks


def _cap_prebuffs(picks: list, ctx: dict) -> list:
    """A pre-buff routine has to fit in the spellbook too.

    You cast these by memorizing one, casting it, and swapping the gem back,
    so the list is bounded by the same gem count as the loadout. Seventeen
    entries against a fourteen-slot book describes something the player
    cannot actually do in one pass, and the overflow was silent.

    PERMANENTS are kept first wherever they were proposed. They are cast
    once and hold until death, so they earn their gem far more cheaply than
    a buff re-cast between every pull -- if anything has to go, it is not
    those.
    """
    slots = ctx.get("spell_slots") or 8
    perm = {n.lower() for n in (ctx.get("_permanent") or [])}
    keep = [p for p in picks if (p.get("name") or "").lower() in perm]
    keep += [p for p in picks if (p.get("name") or "").lower() not in perm]
    if len(keep) > slots:
        logger.info("Pre-buffs trimmed to the %d spell slots (dropped %s)",
                    slots, [p.get("name") for p in keep[slots:]])
    return keep[:slots]


def _describe_prebuffs(picks: list) -> list:
    """Say how long each pre-buff lasts, and whether it ever needs recasting.

    The list was flat and undifferentiated, which is the opposite of useful
    here: a permanent buff is cast once ever and a 27-minute one has to be
    redone before the next pull, and the row gave no way to tell them apart.
    The duration is in the same spell data the gate already reads.
    """
    from backend import builds_data
    for p in picks:
        e = builds_data.spell_entry(p.get("name") or "")
        if not e:
            continue
        ticks = e.get("durationTicks") or 0
        p["permanent"] = ticks == 0
        if ticks:
            # a tick is 6 seconds
            p["duration_min"] = round(ticks * 6 / 60)
    # permanent first, then longest-lasting: the order you actually cast in
    picks.sort(key=lambda x: (not x.get("permanent"),
                              -(x.get("duration_min") or 0)))
    return picks


def _measured_damage(ctx: dict) -> List[str]:
    """What this character's spells and attacks ACTUALLY hit for.

    The advisor was reasoning from spell levels and names alone and made
    Smite the primary nuke while the log showed Careless Lightning hitting
    harder in the same fights. Every encounter already stores per-ability
    hits, total and dps -- the numbers were simply never shown to the thing
    choosing spells.
    """
    agg: dict = {}
    for e in (ctx.get("_encounters") or [])[:8]:
        for a in e.get("abilities") or []:
            n = a.get("name") or ""
            if not n or not (a.get("hits") or 0):
                continue
            r = agg.setdefault(n, {"hits": 0, "total": 0})
            r["hits"] += a["hits"]
            r["total"] += a.get("total") or 0
    rows = sorted(((v["total"], n, v) for n, v in agg.items() if v["total"]),
                  reverse=True)
    return [f"{n} (avg {round(v['total'] / v['hits'])}, {v['total']} total)"
            for _t, n, v in rows[:10]]


def _summons_a_pet(classes: List[str]) -> bool:
    """Does any class in the trio actually summon a pet?

    Pet-support spells target the pet slot (target type 14) and are useless
    without one. A Paladin/Druid/Monk was told to slot Tiny Companion --
    "improves pet mobility" -- with no pet to improve: none of those three
    summons anything. A druid CAN charm an animal, which is a pet of sorts,
    but a charm is a fight-by-fight decision and not a reason to spend two
    of fourteen combat gems on pet utility.
    """
    from backend import builds_data
    for c in classes or []:
        for sp in (builds_data.class_spells(c) or []):
            if any(f.get("effectId") in (33, 71)
                   for f in (sp.get("effects") or [])):
                return True
    return False


def _gate_pet_spells(picks: list, classes: List[str]) -> list:
    """Drop pet-targeted spells when nothing in the trio has a pet."""
    if _summons_a_pet(classes):
        return picks
    from backend import builds_data
    out = []
    for p in picks:
        e = builds_data.spell_entry(p.get("name") or "")
        if e and e.get("targetTypeId") == _PET_TARGET:
            logger.info("Dropped pet spell for a pet-less trio: %s",
                        p.get("name"))
            continue
        out.append(p)
    return out


def _gate_prebuffs(picks: list) -> list:
    """Drop anything in the pre-buff list that is not a buff.

    "Cast it before the fight, then swap the slot back" describes something
    that LEAVES AN EFFECT ON YOU. Eye of Zomm was offered to a wizard trio:
    it is a summoned remote eye, it does nothing to the caster, and there is
    nothing to pre-cast. A summon, a pet, a teleport or a feign is not a
    pre-buff however useful it is elsewhere.

    Kept when the data is missing rather than dropped -- an unrecognised
    spell is not evidence of a bad pick, and the curated line data is
    partial by design.
    """
    from backend import builds_data
    from backend.game_data import _primary_effect
    out = []
    for p in picks:
        e = builds_data.spell_entry(p.get("name") or "")
        if not e:
            out.append(p)
            continue
        if not _is_prebuff(e):
            logger.info("Dropped prebuff (lands on nobody you are buffing, "
                        "or is not a buff effect): %s", p.get("name"))
            continue
        ticks = e.get("durationTicks") or 0
        if ticks > 0:
            out.append(p)          # a timed buff
        elif e.get("targetTypeId") == _SELF_TARGET:
            out.append(p)          # permanent-until-death self-buff
        else:
            # zero duration on a friendly target is a HEAL, not a buff --
            # nothing lingers, so there is nothing to cast in advance.
            logger.info("Dropped prebuff (instant, nothing persists): %s",
                        p.get("name"))
    return out


def _dual_wields(classes: List[str]) -> Optional[bool]:
    """Can this trio swing an off-hand weapon at all?

    Only some classes train Dual Wield -- a Paladin/Necromancer/Wizard
    trains none of it, so a weapon in the off-hand never swings and its
    white-DPS index describes damage that will not be dealt. Reported live:
    an off-hand blade was offered for its "2.7 off-hand index" to exactly
    that trio, the same mistake as valuing an Any Slot item by its DMG.

    None when the builds dataset is absent -- unknown must not read as
    "cannot", or every install without the clone loses off-hand advice.
    """
    try:
        return builds_data.any_has_skill(classes or [], "Dual Wield")
    except Exception:
        return None


def _is_weapon(line: str) -> bool:
    """A thing that SWINGS, as opposed to a shield or a stat item."""
    if not line:
        return False
    if re.search(r"\bSkill:\s*(1H|2H|H2H|Piercing|Archery|Throwing)", line, re.I):
        return True
    return "DMG:" in line.upper() and "DELAY:" in line.upper()


CANON_SLOTS = [
    "Any Slot 1", "Any Slot 2", "Ear 1", "Ear 2", "Head", "Face", "Neck",
    "Shoulders", "Arms", "Back", "Wrist 1", "Wrist 2", "Range", "Hands",
    "Primary", "Secondary", "Fingers 1", "Fingers 2", "Chest", "Legs",
    "Feet", "Waist", "Ammo",
]
# "Held" is deliberately ABSENT. The client writes the location in the
# inventory export, but the in-game UI has no such slot and nothing is
# known to go in it, so a permanently-empty row saying "nothing owned
# equips here" was pure noise in a 24-row table. _fits_slot still requires
# an explicit HELD token, and _full_slot_table appends any worn slot it
# does not know about -- so the day an item turns up in Held, the row
# comes back on its own without anyone re-adding it here.


def _full_slot_table(slots: List[dict], worn: Optional[dict]) -> List[dict]:
    """Merge LLM recommendations onto the canonical roster: unaddressed
    slots keep the worn item, empty slots say so. Slot names outside the
    roster are appended rather than lost -- both from the LLM and from the
    export, so a slot we deliberately do not list (Held) still surfaces the
    moment something is actually in it."""
    def norm(s):
        return "".join(ch for ch in (s or "").casefold() if ch.isalnum())
    by = {}
    for s in slots:
        by.setdefault(norm(s.get("slot")), s)
    # a bare pair name ("Ear") from the LLM lands on the pair's first slot
    out = []
    for slot in CANON_SLOTS:
        cur = (worn or {}).get(slot)
        s = by.pop(norm(slot), None)
        if s is None and slot.endswith(" 1"):
            s = by.pop(norm(slot[:-2]), None)
        if s:
            s["slot"] = slot
            if not s.get("current") and cur:
                s["current"] = cur
            out.append(s)
        else:
            out.append({"slot": slot, "current": cur or "",
                        "recommend": cur or None,
                        "why": "keep — no better owned option flagged"
                               if cur else "empty — nothing owned equips here",
                        "where": "worn" if cur else None})
    out.extend(by.values())
    # anything WORN in a slot outside the roster: never silently dropped
    listed = {norm(r["slot"]) for r in out}
    for slot, cur in (worn or {}).items():
        if cur and norm(slot) not in listed:
            out.append({"slot": slot, "current": cur, "recommend": cur,
                        "why": "keep — not a slot this advisor ranks",
                        "where": "worn"})
    return out


async def _item_meta(name: str) -> Optional[dict]:
    """{classes:set|None(ALL), slots:set, is_weapon, is_2h} from the wiki
    Slot/Skill/Class lines — None if no page."""
    from backend.game_data import item_line as _il
    line = await _il(_item_base(name))
    if not line:
        return None
    cm = re.search(r"Class: ([A-Z ]+)", line)
    classes = None if (cm and "ALL" in cm.group(1).split()) else (
        set(cm.group(1).split()) if cm else set())
    sm = re.search(r"Slot: ([A-Z ]+)", line)
    slots = set(sm.group(1).split()) if sm else set()
    skm = re.search(r"Skill: ([12]H|1H|2H)?", line)
    is_weapon = "Skill:" in line and bool(re.search(r"Skill: [12]H|Skill: H2H", line))
    is_2h = bool(re.search(r"Skill: 2H", line))
    return {"classes": classes, "slots": slots,
            "is_weapon": is_weapon, "is_2h": is_2h}


def _class_overlap(a, b) -> bool:
    if a is None or b is None:   # None == ALL
        return True
    return bool(a & b) if (a and b) else False


async def _exalt_targets(stone_name: str, styp: str,
                         candidates: List[str],
                         sockets_map: Optional[dict] = None) -> List[str]:
    """Owned items this stone can legally socket into (eqlwiki rules):
    proc -> shared class + weapon (2H proc -> Primary only); focus/clicky/
    worn -> shared class + same slot. Source item = the stone's own name.
    When the Inventory export carries socket rows, a target must ALSO
    have an EMPTY socket of the stone's type number (game-authoritative,
    stricter than the wiki heuristics)."""
    src = await _item_meta(re.sub(r"\s*[(]Exaltation[)]$", "", stone_name).strip())
    if not src:
        return []
    need = _SOCKET_NUM.get(styp)
    out = []
    for cand in candidates:
        socket_known = False
        if sockets_map and need:
            empt = sockets_map.get(cand.lower())
            if empt is not None:
                socket_known = True
                if need not in set(empt):
                    continue  # no empty socket of this type on that item
        tgt = await _item_meta(cand)
        if not tgt:
            continue
        if not _class_overlap(src["classes"], tgt["classes"]):
            continue
        if not socket_known:
            # no export socket data — fall back to wiki heuristics. (Real
            # exports show proc sockets on earrings/faces too, so when the
            # game TELLS us a socket exists, it overrides these rules.)
            if styp == "proc":
                if not tgt["is_weapon"]:
                    continue
                if src["is_2h"] and "PRIMARY" not in tgt["slots"]:
                    continue
            else:  # focus / clicky / worn need a shared equipment slot
                if not (src["slots"] & tgt["slots"]):
                    continue
        out.append(cand)
    return out


async def _clickies(items: list) -> list:
    """Owned items with an ACTIVATABLE effect, deterministic.

    Nothing surfaced these before: a clicky is invisible unless you happen
    to remember the item has one, and the wiki line that proves it is
    already fetched for every owned item. Reuses _exalt_socket_type, the same classifier the
    exaltation code uses, so "clicky" means the same thing in both places.

    Worn/focus/proc effects are excluded on purpose -- those fire on their
    own, so listing them would bury the ones that need a keypress.
    """
    from backend.game_data import item_line
    seen: set = set()
    out: list = []
    for it in items:
        name = it.get("name")
        if not name or name.lower() in seen:
            continue
        seen.add(name.lower())
        line = await item_line(name)
        if not line:
            continue
        m = re.search(r"(?<!Focus )Effect: ([^;|]+)", line)
        if not m:
            continue
        effect = m.group(1).strip()
        if _exalt_socket_type(effect) != "clicky":
            continue
        spell = effect.split("(")[0].strip()
        cond = effect[effect.find("(") + 1:effect.rfind(")")] if "(" in effect else ""
        slot_m = re.search(r"Slot: ([^;|]+)", line)
        out.append({
            "item": name,
            "spell": spell,
            # "Any Slot, Casting Time: Instant" -> tells you whether it has
            # to be equipped and how long you stand still for
            "note": cond.strip(),
            "slot": (slot_m.group(1).strip() if slot_m else ""),
            "where": it.get("where") or "",
        })
    out.sort(key=lambda x: (x["where"] != "worn", x["item"].lower()))
    return out


def _pet_category(line: str) -> Optional[str]:
    """What a pet item OCCUPIES. A pet's slots are generic, but the item
    still has a kind: it cannot wear two chests any more than a player can.
    Weapons collapse to one category because the limit is on weapons, not
    on Primary vs Secondary."""
    m = re.search(r"Slot: ([A-Z ]+)", line or "")
    toks = set(m.group(1).split()) if m else set()
    if not toks:
        return None
    if re.search(r"Skill: ", line or "") and (toks & {"PRIMARY", "SECONDARY"}):
        return "WEAPON"
    for t in ("HEAD", "CHEST", "LEGS", "FEET", "ARMS", "HANDS", "WAIST",
              "BACK", "NECK", "SHOULDERS", "FACE", "EAR", "WRIST",
              "FINGER", "FINGERS", "RANGE", "AMMO"):
        if t in toks:
            return t
    return None


def _is_2h(line: str) -> bool:
    return bool(re.search(r"Skill: 2H", line or ""))


# A pet keeps its OWN attack delay, so DELAY carries no information for it --
# comparing on it would make a slower, harder-hitting weapon look worse. This
# is the pet-side analogue of the player path excluding DMG/DELAY from its
# Pareto check, and for the same reason: judging a component apart from the
# thing that gives it meaning produces a confident wrong answer.
def _pet_vec(line: Optional[str], rank: int) -> dict:
    from backend.game_data import item_stat_vector, scale_item_line
    if not line:
        return {}
    v = dict(item_stat_vector(scale_item_line(line, rank)) or {})
    v.pop("DELAY", None)
    return v


def _pet_primary(cat: Optional[str], vec: dict) -> float:
    """The one number that decides a pet item's job: damage for a weapon,
    armour class for everything else (the documented AC-over-HP priority)."""
    return vec.get("DMG", 0.0) if cat == "WEAPON" else vec.get("AC", 0.0)


async def _pet_shortlist(pool: list, pet_inv: dict, pet_slots: int) -> list:
    """Deterministic FIRST pass: which owned items could improve the pet, and
    by exactly what.

    The pet path used to be LLM-proposes / gates-dispose, so "nothing better
    for the pet" was asserted whenever the model happened to propose nothing
    -- a verdict on a comparison that never ran, and unconditionally true with
    no LLM configured. This runs the comparison, and the model's job becomes
    the qualitative half: whether +6 damage is worth -10 STR.

    `pool` is [(name, wiki line)]. Returns entries with the deltas already
    computed, best first. Strictly-dominated candidates are dropped; genuine
    trade-offs are KEPT and labelled, because those are exactly the calls a
    deterministic rule cannot make.
    """
    from backend.game_data import item_line, item_rank
    held, unreadable = [], 0
    for hnm in (pet_inv or {}).values():
        try:
            hl = await item_line(hnm)
        except Exception:
            logger.exception("pet shortlist: no wiki line for held %s", hnm)
            hl = None
        if not hl:
            unreadable += 1
        held.append((hnm, hl, _pet_category(hl), _pet_vec(hl, item_rank(hnm)),
                     bool(re.search(r"Effect:[^;|]*\bCombat\b", hl or ""))))
    free = max(0, int(pet_slots or 0) - len(held))
    # An unreadable held item has an UNKNOWN kind, so a candidate of that kind
    # would look like it fills an empty slot when it would really displace
    # something. Suppress fills rather than guess -- the swap comparisons below
    # are unaffected, since those need a readable rival anyway.
    if unreadable:
        logger.info("pet shortlist: %d held item(s) unreadable — suppressing "
                    "free-slot suggestions", unreadable)
        free = 0
    held_2h = any(_is_2h(hl) for _, hl, c, _, _ in held if c == "WEAPON")
    weapons_held = sum(1 for _, _, c, _, _ in held if c == "WEAPON")

    out = []
    for nm, line in pool:
        cat = _pet_category(line)
        cv = _pet_vec(line, item_rank(nm))
        if not cv:
            continue
        proc = bool(re.search(r"Effect:[^;|]*\bCombat\b", line or ""))
        rivals = [h for h in held if h[2] == cat and cat]
        # NOTE the proc exemption below: a strictly-worse stat line does NOT
        # disqualify a proccing weapon. A pet's damage counts only when it
        # beats its innate hit, while a proc lands either way -- so a
        # low-damage proc is a top pick, not a poor one. Judging it on the
        # stat vector alone drops exactly the item the rule exists to promote.
        if not rivals:
            # nothing of this kind held -- only interesting if there is room,
            # and a weapon still has to obey the two-weapon / 2H rules
            if free <= 0:
                continue
            if cat == "WEAPON" and (held_2h or weapons_held >= 2
                                    or (_is_2h(line) and weapons_held)):
                continue
            out.append({"cand": nm, "vs": None, "verdict": "fills a free slot",
                        "gain": cv, "loss": {}, "proc": proc, "cat": cat,
                        "score": _pet_primary(cat, cv)})
            continue
        for hnm, hl, _hc, hv, hproc in rivals:
            if not hv:
                continue          # STATS UNKNOWN -- never displace it
            if _pareto_beats(hv, cv) and not (proc and not hproc):
                continue          # held strictly better AND brings a proc too
            gain = {k: round(cv.get(k, 0.0) - hv.get(k, 0.0), 1)
                    for k in set(cv) | set(hv)
                    if cv.get(k, 0.0) > hv.get(k, 0.0)}
            loss = {k: round(hv.get(k, 0.0) - cv.get(k, 0.0), 1)
                    for k in set(cv) | set(hv)
                    if hv.get(k, 0.0) > cv.get(k, 0.0)}
            if not gain and not proc:
                continue          # nothing to offer
            out.append({
                "cand": nm, "vs": hnm, "cat": cat, "proc": proc,
                "gain": gain, "loss": loss,
                "verdict": ("clear upgrade" if _pareto_beats(cv, hv)
                            else "trade-off"),
                "score": _pet_primary(cat, cv) - _pet_primary(cat, hv),
            })
    out.sort(key=lambda e: (e["verdict"] != "clear upgrade", -e["score"]))
    return out


def _pet_shortlist_text(sl: list) -> str:
    """Render the shortlist for the prompt -- deltas, not adjectives."""
    if not sl:
        return ""
    fmt = lambda d: ", ".join(f"{k} {v:+g}" for k, v in
                              sorted(d.items(), key=lambda kv: -abs(kv[1])))
    rows = []
    for e in sl[:12]:
        bits = [f"  - {e['cand']}"]
        bits.append(f"vs held {e['vs']}" if e["vs"] else "for a FREE slot")
        bits.append(f"— {e['verdict'].upper()}")
        if e["gain"]:
            bits.append(f"— gains {fmt(e['gain'])}")
        if e["loss"]:
            bits.append(f"— loses {fmt({k: -v for k, v in e['loss'].items()})}")
        if e["proc"]:
            bits.append("— HAS A COMBAT PROC")
        rows.append(" ".join(bits))
    return ("\nA deterministic pass already compared every eligible owned item "
            "against what the pet holds (delay excluded: pets keep their own). "
            "Strictly-worse items are gone; what remains is real:\n"
            + "\n".join(rows)
            + "\nDecide the TRADE-OFFS from this list — that judgement is why "
              "you are here. A 'clear upgrade' needs no defence; for a "
              "'trade-off' say plainly what is given up.\n")


async def _tradeoffs(ctx: dict) -> list:
    """Owned items that beat a worn one on SOME stats and lose on others.

    The recommendation gate is a strict Pareto win, which is right -- it
    never claims an upgrade it cannot prove. But a candidate that fails it
    was silently discarded, and the row then read "keep -- no better owned
    option flagged", which states that a search found nothing. What
    actually happened is that a real trade lost a tiebreak we are not
    qualified to call.

    Reported live: Traveling Sollerets +4 (AC 13, STA 6, SV Cold 9) sat in
    a bag while the worn boots (AC 11, AGI 10) held the slot, and the panel
    said nothing. Weighing AC against AGI needs class-specific numbers we
    do not have, so this surfaces the trade instead of deciding it.

    Runs on EVERY path, like merge notices and clickies -- an LLM consult
    was the one place this mattered most and the deterministic loop it
    lived in does not run there.
    """
    # Imported HERE, matching the rest of this module -- game_data pulls in
    # the wiki client, so advisor.py keeps these calls function-local.
    from backend.game_data import (item_line, item_stat_vector,
                                   scale_item_line, _trio_usable)
    worn = ctx.get("worn") or {}
    items = ctx.get("inventory_items") or []
    classes = [x.strip() for x in (ctx.get("class_str") or "").split("/")
               if x.strip()]
    spares = [i for i in items
              if i.get("where") != "worn" and i.get("name")]
    if not worn or not spares:
        return []
    out = []
    for slot, cur in worn.items():
        cur = (cur or "").strip()
        if not cur:
            continue
        try:
            cur_line = await item_line(cur)
        except (LookupError, OSError, ValueError):
            # NOT a bare Exception. It swallowed a NameError from the
            # imports above being absent and returned an empty list for
            # EVERY slot -- indistinguishable from "no trades found".
            cur_line = None
        if not cur_line:
            continue
        cur_vec = item_stat_vector(scale_item_line(cur_line, _item_rank(cur)))
        if not cur_vec:
            continue
        best = None
        for it in spares:
            nm = it["name"]
            if _item_base(nm) == _item_base(cur):
                continue
            try:
                line = await item_line(nm)
            except Exception:
                line = None
            if not line or "Slot:" not in line:
                continue
            if not await _fits_slot(nm, slot):
                continue
            if classes and _trio_usable(line, classes) is False:
                continue
            base_slot = re.sub(r"\s+\d+$", "", slot.lower())
            if (base_slot == "secondary" and _dual_wields(classes) is False
                    and _is_weapon(line)):
                continue  # no Dual Wield: an off-hand weapon never swings
            vec = item_stat_vector(scale_item_line(line, _item_rank(nm)))
            ref = cur_vec
            if base_slot == "any slot":
                # an Any Slot item is not swung -- same rule the recommender
                # follows, or a weapon "wins" on damage it will never deal
                vec = {k: v for k, v in vec.items()
                       if k not in ("DMG", "DELAY", "HASTE")}
                ref = {k: v for k, v in cur_vec.items()
                       if k not in ("DMG", "DELAY", "HASTE")}
            vec, ref = _effective_vecs(vec, ref, ctx)
            if not vec or _pareto_beats(vec, ref):
                continue  # a clean win is the recommender's business
            diff = {k: vec.get(k, 0.0) - ref.get(k, 0.0)
                    for k in set(vec) | set(ref)
                    if k != "DELAY" and vec.get(k, 0.0) != ref.get(k, 0.0)}
            up = {k: v for k, v in diff.items() if v > 0}
            down = {k: -v for k, v in diff.items() if v < 0}
            if not up or not down:
                continue
            score = (len(up) - len(down), sum(up.values()))
            if best is None or score > best[0]:
                best = (score, it, up, down)
        if best:
            _sc, ti, up, down = best
            fmt = lambda d: ", ".join(
                f"{v:g} {k.replace('_', ' ')}"
                for k, v in sorted(d.items(), key=lambda kv: -abs(kv[1])))
            out.append({"slot": slot, "current": cur, "item": ti["name"],
                        "where": ti.get("where"),
                        "gains": fmt(up), "losses": fmt(down)})
    return out


async def _surplus(items: list, worn: Optional[dict]) -> list:
    """Owned things that will not be worn again, whatever you level next.

    Deliberately CLASS-AGNOSTIC. A trio is a temporary state -- the player
    swaps them and intends to keep swapping -- so "your Necromancer cannot
    use this" is not a reason to sell anything. Only two conditions
    qualify, and both hold no matter what you play:

      1. A strictly lower rank of an item you already own at a higher one.
         An item at +N embodies 2^N copies, so a spare +0 beside your +5 is
         merge fodder at best and clutter otherwise.
      2. The wiki calls it vendor trash outright.

    Everything else is left alone ON PURPOSE. An item with no wiki page
    could be anything; a quest item looks like junk until the quest; a low
    -AC piece is still the best thing a future class has. This list is
    meant to be short and certain rather than long and probably-right,
    because the action it invites cannot be undone.
    """
    from backend.game_data import item_acquisition
    worn_names = {str(v).strip().lower() for v in (worn or {}).values() if v}
    best: dict = {}
    for it in items:
        nm = it.get("name") or ""
        if not nm:
            continue
        b = _item_base(nm)
        r = _item_rank(nm)
        if b not in best or r > best[b][0]:
            best[b] = (r, nm)
    out = []
    for it in items:
        nm = it.get("name") or ""
        if not nm or nm.strip().lower() in worn_names or it.get("where") == "pet":
            continue
        b, r = _item_base(nm), _item_rank(nm)
        top = best.get(b)
        if top and r < top[0]:
            out.append({"name": nm, "where": it.get("where"),
                        "why": f"you also own {top[1]} — merge it in or sell it",
                        "action": "merge or sell"})
            continue
        try:
            acq = await item_acquisition(nm)
        except Exception:
            continue
        blob = " ".join(l.get("text", "") for sec in (acq.get("sections") or [])
                        for l in (sec.get("lines") or []))
        if "vendor trash" in (blob + " " + (acq.get("notes") or "")).lower():
            out.append({"name": nm, "where": it.get("where"),
                        "why": "the wiki calls this vendor trash",
                        "action": "sell"})
    # one row per item, most actionable first
    seen, dedup = set(), []
    for r in out:
        if r["name"].lower() in seen:
            continue
        seen.add(r["name"].lower())
        dedup.append(r)
    return dedup[:20]


async def _merge_opportunities(items: list, exalts: list,
                               loot_filter: Optional[dict] = None) -> list:
    """Duplicate owned EQUIPMENT is an EQL merge opportunity: two copies
    of the same base item combine toward the next +N. Deterministic
    notice only — grouped by base name across worn/bags/bank, filtered
    to real equipment via the wiki gate (no consumable stacks), result
    predicted with the wiki slider's own progression model (an item at
    +N embodies 2^N base copies, so equal ranks merge to exactly +N+1
    and unequal ranks land partway: a +4 and a +0 give "+4 + 1/16").
    When BOTH copies are WORN (paired slots: ears/wrists/fingers/any),
    merging EMPTIES a slot — the notice quantifies the stat loss so the
    user never trades two bracers for one blindly."""
    from backend.game_data import item_line, item_stat_vector, scale_item_line
    groups: dict = {}
    for it in items:
        b = _item_base(it["name"])
        g = groups.setdefault(b.lower(), {"base": b, "copies": []})
        g["copies"].append({"rank": _item_rank(it["name"]),
                            "where": it.get("where") or "?"})
    hosts = {_item_base(x.get("host") or "").lower()
             for x in exalts if x.get("host")}
    out = []
    for key, g in groups.items():
        if len(g["copies"]) < 2:
            continue
        try:
            line = await item_line(g["base"])
        except Exception:
            line = None
        if not line:  # not equipment — merging is a gear mechanic
            continue
        total = sum(2 ** c["rank"] for c in g["copies"])
        full = total.bit_length() - 1
        remainder = total - (1 << full)
        result = f"+{full}" + (f" + {remainder}/{1 << full}" if remainder else "")
        copies = sorted(g["copies"], key=lambda c: -c["rank"])
        worn = [c for c in copies if c["where"] == "worn"]
        compare = None
        if len(worn) >= 2:
            # paired-slot pair worn: merging empties a slot — quantify it
            va = item_stat_vector(scale_item_line(line, worn[0]["rank"]))
            vb = item_stat_vector(scale_item_line(line, worn[1]["rank"]))
            vm = item_stat_vector(scale_item_line(line, full))
            keys = [k for k in va if k != "DELAY"][:5]

            def _fmtv(v):
                return ", ".join(
                    f"{k.replace('_', ' ')} {int(v.get(k, 0))}"
                    for k in keys if v.get(k))
            pair_total = {k: va.get(k, 0) + vb.get(k, 0) for k in keys}
            compare = (f"BOTH copies are worn — merging empties a slot: "
                       f"wearing both = {_fmtv(pair_total)}; merged "
                       f"+{full} alone = {_fmtv(vm)}. Keep both unless a "
                       "better filler exists for the freed slot")
        out.append({
            "item": g["base"],
            "copies": [f"+{c['rank']} ({c['where']})" for c in copies],
            "result": result,
            "hosts_exalt": key in hosts,
            "worn_pair": len(worn) >= 2,
            "compare": compare,
            # the game auto-merges/sells/stores per the loot filter — a
            # "merge" action means new drops combine on pickup already
            "filter_action": (loot_filter or {}).get(key),
        })
        if len(out) >= 12:
            break
    out.sort(key=lambda m: m["item"].lower())
    return out


async def generate_gear_advice(ctx: dict) -> dict:
    from backend.game_data import build_gear_context

    items = ctx.get("inventory_items") or []
    base = {
        "generated": datetime.now().isoformat(timespec="seconds"),
        "context": {"classes": ctx.get("class_str"), "level": ctx.get("level"),
                    "race": ctx.get("race"),
                    "items": len(items)},
        # deterministic duplicate-item merge notices — every return path
        # (LLM, builtin, fallback) carries them
        "merges": await _merge_opportunities(items,
                                             ctx.get("exaltations") or [],
                                             ctx.get("loot_filter")),
        "clickies": await _clickies(items),
        # things that will not be worn again whatever you level next
        "surplus": await _surplus(items, ctx.get("worn")),
        # candidates that win some stats and lose others: real
        # trades the strict-Pareto recommender must not claim
        "tradeoffs": await _tradeoffs(ctx),
    }
    if not items:
        return {**base, "source": "builtin", "note":
                "No inventory export found — type /outputfile inventory "
                "in-game, then press check exports.",
                "slots": [], "farm": [], "exaltations": [], "pet_gear": [], "unknown": []}
    if llm_active()["provider"] == "none":
        return {**base, **(await _builtin_gear(ctx))}
    classes = [x.strip() for x in (ctx.get("class_str") or "").split("/")
               if x.strip()]
    # DEX drives the proc-per-minute budget, and it only exists when the
    # stats OCR is running -- without it proccing weapons carry no rate and
    # the prompt below says nothing about procs rather than guessing one.
    _dex = (ctx.get("ocr_stats") or {}).get("dex")
    gear = await build_gear_context(items, classes, dex=_dex,
                                    level=ctx.get("level"))
    exalts = ctx.get("exaltations") or []
    exalt_lines = []
    exalt_info = []
    unusable_exalts = set()
    # distinct owned items a stone might socket into (worn + owned, deduped)
    _cand_seen = set()
    exalt_targets = []
    for _nm in (list((ctx.get("worn") or {}).values())
                + [it["name"] for it in (ctx.get("inventory_items") or [])]):
        k = _item_base(_nm).lower()
        if k and k not in _cand_seen:
            _cand_seen.add(k)
            exalt_targets.append(_nm)
    from backend.game_data import _trio_usable, item_line as _gd_item_line
    for x in exalts:
        bname = re.sub(r"\s*[(]Exaltation[)]$", "", x["name"]).strip()
        eff = None
        usable = None
        try:
            full_line = await _gd_item_line(bname)
            if full_line:
                m2 = re.search(r"(?:Focus )?Effect: [^;|]+", full_line)
                eff = m2.group(0) if m2 else "no listed effect (stat stone?)"
                usable = _trio_usable(full_line, classes)
        except Exception:
            pass
        host = (f"socketed in {x['host']} ({x['host_loc']})" if x.get("host")
                else f"loose in the {x['where']}")
        styp = _socket_type_from_export(x) or _exalt_socket_type(eff)
        fits = ("weapon sockets only (Primary/Secondary/Range)"
                if styp == "proc" else f"{styp} sockets"
                if styp != "unknown" else "unknown socket type")
        if usable is False:
            # the stone keeps its base item's class restriction — no one in
            # this trio can use its effect at all
            unusable_exalts.add(x["name"].lower())
            cls_tag = " — [NOT USABLE by this trio: base item's class list excludes all three — bank fodder, never recommend moving it]"
        else:
            cls_tag = ""
        lvl_tag = ""
        lm = re.search(r"at Level (\d+)", eff or "")
        if lm:
            req = int(lm.group(1))
            have = ctx.get("level")
            if have is not None:
                lvl_tag = (f" — ACTIVE (needs L{req}, they are L{have})"
                           if have >= req else
                           f" — DORMANT until L{req} (they are L{have}: "
                           "worth ZERO right now)")
        exalt_lines.append(f"{x['name']} — {host}"
                           + (f" — grants {eff}" if eff else "")
                           + f" — type: {styp} (fits {fits}){lvl_tag}{cls_tag}")
        # deterministic, informational (NOT a move prescription — socketing
        # compatibility rules are not reliably derivable from our data)
        eff_txt = re.sub(r"^(?:Focus )?Effect:\s*", "", eff or "").strip() if eff else ""
        if usable is False:
            status = "not usable by your classes"
        elif lm and ctx.get("level") is not None and ctx["level"] < int(lm.group(1)):
            status = f"dormant until L{lm.group(1)}"
        elif eff and "no listed effect" in eff:
            status = "stat stone"
        else:
            status = "active"
        elig = []
        # "no legal target" and "we never looked" are DIFFERENT answers, and
        # only the first may be reported as a restriction. Stat stones and
        # trio-unusable stones skip the lookup entirely, so an empty list
        # there proves nothing -- same rule as the RANGE row in the weapon
        # comparison, which says it was not compared rather than claiming
        # nothing better exists.
        targets_checked = False
        if usable is not False and status != "stat stone":
            try:
                cur_host = _item_base(x.get("host") or "").lower()
                elig = [t for t in await _exalt_targets(
                            x["name"], styp, exalt_targets,
                            ctx.get("item_sockets"))
                        if _item_base(t).lower() != cur_host]
                targets_checked = True
            except Exception:
                elig = []
                targets_checked = False
        move = ", ".join(sorted({t for t in elig})[:6])
        exalt_info.append({
            "name": re.sub(r"\s*[(]Exaltation[)]$", "", x["name"]).strip(),
            "move_to": move,
            # carry the type that was resolved ABOVE from the export socket
            # number or the full Effect line. It used to be re-derived from
            # the `why` text, which has "Focus Effect:"/"Combat Effect:"
            # stripped off -- the exact words the classifier keys on -- so
            # every stone came back "unknown" and the proc warning below
            # never fired.
            "type": styp,
            "targets_checked": targets_checked,
            # what this stone ACTUALLY grants, kept raw. An item's own wiki
            # "Effect:" line describes the stone it DROPS with, not the item
            # as worn -- effects in EQL come only from the socketed stone.
            "effect": eff_txt,
            "where": ("in " + x["host"] if x.get("host")
                      else f"loose in {x['where']}"),
            "why": (eff_txt + (f" — {status}" if status else "")).strip(" —")
                   or status,
        })
    # decorate gear lines with hosted stones — the model compares ITEMS
    # from these lines, so the stone must be visible at the decision
    # point, not only in the separate exaltations block
    host_notes: dict = {}
    for x in exalts:
        if not x.get("host"):
            continue
        snm = re.sub(r"\s*[(]Exaltation[)]$", "", x["name"]).strip()
        rec = next((i for i in exalt_info
                    if i["name"].lower() == snm.lower()), None) or {}
        styp2 = rec.get("type")
        moves = rec.get("move_to") or ""
        # Where a stone may legally GO belongs on the gear line, not only in
        # the separate exaltations block: this line is the decision point, and
        # the prompt asks the model to write "move its stone first" prose. Told
        # only the stone's name, it invented targets -- a Robe focus stone was
        # described as movable into "any other open-focus item" when
        # _exalt_targets restricts focus/worn/clicky to items sharing an
        # equipment SLOT with the stone's base item (Robe -> Chest only).
        grants = (rec.get("effect") or "").strip()
        head = f"{snm}" + (f" granting {grants}" if grants else "")
        if styp2 == "proc":
            tagtxt = f"{head} (proc — may only fire from PRIMARY)"
        elif moves:
            tagtxt = f"{head} ({styp2} stone — may ONLY move to: {moves})"
        elif rec.get("targets_checked"):
            tagtxt = (f"{head} ({styp2} stone — CANNOT be moved: no other owned "
                      f"item has a free {styp2} socket in a slot it fits)")
        else:
            tagtxt = head          # not checked — assert nothing
        host_notes.setdefault(_item_base(x["host"]).lower(), []).append(tagtxt)
    # An item's wiki "Effect:" line describes the stone it DROPS with, NOT the
    # item as worn -- in EQL the effect comes only from the socketed stone. So
    # the line is wrong in BOTH directions once stones are moved: a Gossamer
    # Robe hosting a Smoldering Robe stone reads "Summoning Efficiency I" while
    # actually granting "Minor Improved Damage I", and four other worn items
    # showed no Effect at all while carrying real transplanted ones. Correct
    # the claim wherever the socket contradicts it, so the model is not
    # reasoning from an effect the player does not have.
    if host_notes:
        for i, ln in enumerate(gear["lines"]):
            nm = ln.split(" [", 1)[0]
            notes = host_notes.get(_item_base(nm).lower())
            if not notes:
                continue
            own = re.search(r"(?:Focus )?Effect: [^;|]+", ln)
            granted = "; ".join(n for n in notes)
            correction = ""
            if own:
                claimed_eff = re.sub(r"^(?:Focus )?Effect:\s*", "",
                                     own.group(0)).strip().lower()
                if claimed_eff and claimed_eff not in granted.lower():
                    correction = (f" | NOTE: this item's listed \"{own.group(0)}\" "
                                  "is the effect of its OWN stone, which is NOT "
                                  "socketed here — ignore it; the item grants "
                                  "only what is listed under HOSTS EXALTATION")
            gear["lines"][i] = (ln + " | HOSTS EXALTATION: " + granted
                                + correction)
    # An item's Effect line is its NATIVE effect and applies on its own; a
    # socketed focus stone OVERRIDES it. Both observations fit that and only
    # that: a Gossamer Robe (native Summoning Efficiency I) wearing a
    # Smoldering Robe stone reports Minor Improved Damage I, while Shining
    # Metallic Robes reports its native Spell Haste II with an EMPTY socket.
    #
    # An earlier version of this block asserted the opposite -- that an item
    # with no stone grants nothing -- which would have told the model a robe
    # the player is actively using for 15% cast time does nothing at all.
    # Nothing is annotated here now: the unmodified Effect line is correct
    # whenever no stone overrides it, and the override case is handled above.
    base["context"]["with_stats"] = len(gear["lines"])
    base["context"]["unknown"] = len(gear["unknown"])

    combat = ctx.get("combat")
    combat_line = (
        f"- Recent combat (last {combat['fights']} fights): avg incoming "
        f"hit {combat['avg_incoming_hit'] or '?'}, avg "
        f"{combat['avg_taken_per_fight']} damage taken per fight"
        if combat else "- Recent combat: no data this session")
    lines = [
        f"- Classes: {ctx.get('class_str') or 'unknown'}",
        f"- Level: {ctx.get('level') or 'unknown'}",
        f"- Race: {ctx.get('race') or 'unknown'}",
        f"- Focus: {ctx.get('playstyle') or 'balanced'}",
        f"- Max HP: {ctx.get('max_hp') or 'unknown (user has not set it)'}"
        + (f" · Max mana: {ctx.get('max_mana')}" if ctx.get('max_mana')
           else " · Max mana: unknown"),
        combat_line,
        f"- Currently worn: "
        + "; ".join(f"{k}: {v}" for k, v in sorted((ctx.get('worn') or {}).items())),
    ]
    from backend.game_data import class_guide_text
    guides = class_guide_text(classes, max_chars_per=1500)
    if guides:
        lines.append("- Community class guides (playstyle + pet-gear "
                     "wisdom, curated in class_guides/*.md; may lag "
                     "patches):\n" + guides)
    pet_inv = ctx.get("pet_inventory") or {}
    player_classes = [c.strip() for c in (ctx.get("class_str") or "").split("/")
                      if c.strip()]
    # every pet is base Warrior + a secondary by pet type (Water = ROG, Fire
    # = WIZ, Beastlord = BER). The user sets only that secondary.
    pet_2nd = (ctx.get("pet_classes") or "").strip()
    pet_base = ["Warrior"] + [
        c.strip() for c in re.split(r"[/,]", pet_2nd)
        if c.strip() and c.strip().lower() not in ("warrior", "war")]
    pet_class_str = "/".join(pet_base)
    # a pet equips gear usable by its TWO base classes PLUS the player's
    # trio — up to five classes' worth of items
    pet_classes = []
    for c in pet_base + player_classes:
        if c not in pet_classes:
            pet_classes.append(c)
    # pet window: 4 base slots + a per-class modifier for each relevant
    # class in the combo. Only classes that SUMMON a pet grant one.
    PET_SLOT_MOD = {"Beastlord": 3, "Magician": 3, "Necromancer": 2,
                    "Enchanter": 1, "Druid": 1, "Shaman": 1}
    PET_SUMMONS = {"Magician", "Necromancer", "Beastlord", "Enchanter",
                   "Shadow Knight"}
    has_pet = any(c in PET_SUMMONS for c in player_classes)
    auto_slots = (4 + sum(PET_SLOT_MOD.get(c, 0) for c in player_classes)
                  ) if has_pet else 0
    pet_slots = (ctx.get("pet_slots") or 0) or auto_slots or len(pet_inv)
    # deterministic pass output; stays empty when there is no pet, so the
    # backfill below can tell "compared, found nothing" from "never ran"
    pet_shortlist: list = []
    if pet_slots > 0:
        # deterministic pool: owned bags/bank gear the PET's class can equip
        # (not the player's), with stats, not the player's worn gear, not
        # exaltation hosts, not already on the pet
        from backend.game_data import _trio_usable, item_line as _il
        exalt_hosts_p = {(x.get("host") or "").lower()
                         for x in (ctx.get("exaltations") or [])}
        pet_now = {v.lower() for v in pet_inv.values()}
        pool = []
        for it in items:
            if it.get("where") not in RETRIEVABLE:
                continue
            nm = it["name"]
            if nm.lower() in pet_now or nm.lower() in exalt_hosts_p:
                continue
            line = await _il(nm)
            if not line or _trio_usable(line, pet_classes) is False:
                continue
            if not re.search(r"AC: *[0-9]|DMG: *[0-9]|Skill:", line):
                continue  # only real gear (armor/weapons)
            if re.search(r"No Drop|NO DROP|NODROP", line):
                continue  # pets accept Attunable items only, not No-Drop
            pool.append((nm, line))
        # Rank by what a pet actually cares about before capping. This was
        # sorted ALPHABETICALLY and cut at 40, so on a real inventory the
        # model never saw anything past "S" -- 20 items including three
        # weapons (Short Sword of the Ykesha, Stiletto of the Bloodclaw,
        # Verishe Mal Greataxe) were dropped in silence, and the panel still
        # said "nothing better". Same shape as the missing_spells cap that
        # kept the 25 LOWEST levels.
        from backend.game_data import (item_rank as _irk0,
                                       scale_item_line as _scl0,
                                       item_stat_vector as _vec0)

        def _pet_worth(nm_line):
            nm, ln = nm_line
            try:
                v = _vec0(_scl0(ln, _irk0(nm))) or {}
            except Exception:
                v = {}
            # AC for armour, DMG for weapons -- the two things the pet uses.
            # Everything else breaks ties so a stat-rich item outranks a bare
            # one of equal AC.
            return (-(v.get("AC", 0.0) + 2.0 * v.get("DMG", 0.0)),
                    -len(v), nm.lower())

        uniq = {nm: ln for nm, ln in pool}
        ranked = sorted(uniq.items(), key=_pet_worth)
        POOL_CAP = 40
        shown, dropped = ranked[:POOL_CAP], ranked[POOL_CAP:]
        pool_txt = "; ".join(n for n, _ in shown) or "none"
        if dropped:
            # never truncate in silence -- say so in the prompt AND the log
            logger.info("Pet-gear pool truncated: %d of %d candidates shown "
                        "(dropped: %s)", len(shown), len(ranked),
                        ", ".join(n for n, _ in dropped))
            pool_txt += (f" — (list capped at {POOL_CAP}; {len(dropped)} "
                         "lower-AC/DMG candidates omitted)")
        # Deterministic FIRST pass over the WHOLE ranked pool, not just the
        # 40 shown -- the comparison is cheap and must not inherit the cap.
        try:
            pet_shortlist = await _pet_shortlist(ranked, pet_inv, pet_slots)
        except Exception:
            logger.exception("pet shortlist failed")
            pet_shortlist = []
        if pet_inv:
            # held items live on the PET, not in the inventory export - mine
            # their stat lines here (scaled to each +N) or the model would
            # compare candidates against bare names
            from backend.game_data import (item_rank as _irk,
                                           scale_item_line as _scl)
            held = []
            for nm in sorted(pet_inv.values()):
                try:
                    hl = await _il(nm)
                except Exception:
                    hl = None
                held.append("  - " + nm + " - "
                            + (_scl(hl, _irk(nm)) if hl else
                               "STATS UNKNOWN (never displace this item)"))
            free = max(0, pet_slots - len(pet_inv))
            cur = ("The pet CURRENTLY holds (stats shown at each item's "
                   "+N):\n" + "\n".join(held) + "\nFree pet slots: "
                   f"{free}. Recommend a hand-over ONLY when it clearly "
                   "BEATS one of the held items above (name the item it "
                   "replaces in the why) or fills a free slot. ")
        else:
            cur = "The pet CURRENTLY holds: nothing. "
        pet_block = (
            f"PET LOADOUT — the pet's base classes are {pet_class_str}, and "
            "it can ALSO wear the player's classes' gear (up to five classes "
            "total; already filtered for you). The pet has "
            f"{pet_slots} GENERIC slots — a bag of up to that many items, NO "
            "named slots (no Head/Arms/Chest structure): do NOT organize by "
            "slot. " + cur +
            "Recommend the BEST loadout of up to "
            f"{pet_slots} items total, following the pet auto-equip rules: "
            "(0) a pet cannot wear two of the same KIND any more than a "
            "player can: one chest, one head, one back, one waist. A robe "
            "is a CHEST — do not offer it as a replacement for a cloak or "
            "a belt. And a TWO-HANDED weapon fills both hands, so if the "
            "pet holds one, do not add a second weapon at all; "
            "(1) up to TWO weapons — the pet keeps its OWN attack "
            "delay, so weapon delay and damage/delay RATIO are irrelevant "
            "to it; a weapon's damage counts only when it BEATS the pet's "
            "innate hit, while procs and damage type apply either way — "
            "so PROCCING weapons (lifetap/damage) are the top picks even "
            "when their listed damage is low; (2) a "
            "HASTE belt (haste stacks with spell haste — a top pick); (3) "
            "armor prioritizing AC over HP, plus cleave/ferocity/attack "
            "gear; the two 'any' slots can hold a shield (big AC), rings, "
            "earrings, or a cloak. Do NOT recommend two items of the same "
            "category (duplicates don't stack), and note total gear stats "
            "cap at 510. OWNED items the PET CAN EQUIP (bags/bank, already "
            "class-checked): " + pool_txt +
            _pet_shortlist_text(pet_shortlist) +
            ". From THIS LIST ONLY, list in 'pet_gear' each recommended item "
            "as {item, why} (no slot needed), best first, at most "
            f"{pet_slots} items. Pet gear PERSISTS through death/re-summon. "
            "THE PLAYER KEEPS STAT PRIORITY: never hand the pet something "
            "better than the player's own worn gear. Every candidate above "
            "is SPARE gear sitting in bags/bank -- it is NOT gear the "
            "player is unable to equip, and much of it they CAN equip. "
            "Class usability was computed deterministically for you (the "
            "[USABLE] tags); do NOT assert or infer any class restriction "
            "on the player in 'why'. Justify a hand-over by what it does "
            "for the PET.")
    else:
        pet_block = ("PET LOADOUT: none — pet_gear must be []. (The player "
                     "sets their pet's slot count + class in the Advisor "
                     "tab, or the app reads slots from /pet inventory check.)")
    # Only some classes train Dual Wield. Without it an off-hand weapon
    # never swings, and the model WILL reason from the white-DPS index
    # annotations otherwise -- it offered an off-hand blade for its "2.7
    # off-hand index" to a Paladin/Necromancer/Wizard. The deterministic
    # gate drops such picks; saying it here stops the prose being written
    # in the first place.
    # Capped attributes, so the model stops offering stats with no effect.
    _hr = _stat_headroom(ctx)
    if _hr:
        full = [k for k, v in _hr.items() if v <= 0]
        near = [f"{k} ({v} left)" for k, v in _hr.items() if 0 < v <= 20]
        bits = []
        if full:
            bits.append("AT THE 510 CAP (further points do NOTHING): "
                        + ", ".join(full))
        if near:
            bits.append("nearly capped: " + ", ".join(near))
        if bits:
            lines.append("- " + "; ".join(bits)
                         + ". Never recommend an item FOR a capped stat.")
    _dw = _dual_wields(classes)
    dw_rule = ""
    if _dw is False:
        dw_rule = ("- This trio does NOT train Dual Wield. An off-hand WEAPON "
                   "would never swing, so NEVER recommend one for Secondary "
                   "and never cite an off-hand white-DPS index. A shield or "
                   "a stat item in Secondary is still worth recommending." + chr(10))
    elif _dw is True:
        dw_rule = ("- This trio trains Dual Wield, so an off-hand weapon does "
                   "swing and its off-hand index counts." + chr(10))
    prompt = (GEAR_PROMPT
              .replace("__PET_BLOCK__", pet_block)
              .replace("__CONTEXT__", chr(10).join(lines))
              .replace("__GEAR__", chr(10).join(gear["lines"]))
              .replace("__EXALTS__", chr(10).join(exalt_lines) or "none owned")
              .replace("__DUAL_WIELD__", dw_rule))
    budget = await asyncio.to_thread(_lmstudio_budget, len(prompt))
    llm = get_llm()
    bound = llm
    if budget:
        try:
            bound = llm.bind(max_tokens=budget)
        except Exception:
            pass
    try:
        response = await bound.ainvoke([HumanMessage(content=prompt)])
        raw = _reply_text(response)
        data = _extract_json(raw)
        if not data:
            raise ValueError(_no_json_reason(response, raw))
        _warn_if_truncated(prompt, data)
    except Exception as e:
        logger.warning("Gear advisor failed: %.140s", str(e))
        try:
            body = await _builtin_gear(ctx)
            body["note"] = (f"LLM unavailable ({str(e)[:60]}) — showing the "
                            "deterministic gear check instead. " + body["note"])
            return {**base, **body}
        except Exception:
            pass
        return {**base, "source": "builtin",
                "note": f"Live gear counsel needs the LLM ({str(e)[:60]}).",
                "slots": [], "farm": [], "exaltations": [], "pet_gear": [],
                "unknown": gear["unknown"][:10]}

    from backend.game_data import item_line as _item_line
    owned = {s["name"].lower() for s in items}
    owned_base = {re.sub(r"\s*[+]\d+$", "", n) for n in owned}
    where_by_base: dict = {}
    for it in items:
        b = re.sub(r"\s*[+]\d+$", "", it["name"].lower())
        where_by_base.setdefault(b, set()).add(it["where"])
    slots = []
    for s in _clean_list(data.get("slots"), ("slot", "current", "recommend", "why"),
                         cap=20, require="slot"):
        rec = str(s.get("recommend") or "").lower()
        rec_base = re.sub(r"\s*[+]\d+$", "", rec)
        cur = str(s.get("current") or "").lower()
        cur_base = re.sub(r"\s*[+]\d+$", "", cur)

        def _rank(n):
            m = re.search(r"[+](\d+)$", n)
            return int(m.group(1)) if m else 0

        unknown_bases = {re.sub(r"\s*[+]\d+$", "", u.lower())
                         for u in gear["unknown"]}
        if (cur_base and cur_base in unknown_bases and rec_base != cur_base):
            logger.info("Dropped %s rec — current item '%s' has no stat data "
                        "to compare against", s.get("slot"), s.get("current"))
            continue
        if rec_base == cur_base and rec != cur and _rank(rec) <= _rank(cur):
            logger.info("Dropped %s rec — same item at equal/lower rank", s.get("slot"))
            continue
        if rec and not await _fits_slot(rec, str(s.get("slot") or "")):
            logger.info("Dropped %s rec — %s does not fit that slot",
                        s.get("slot"), rec)
            continue
        if rec:
            from backend.game_data import _trio_usable, item_line as _il
            rline = await _il(rec)
            if rline and _trio_usable(rline, classes) is False:
                logger.info("Dropped %s rec — %s not usable by the trio",
                            s.get("slot"), rec)
                continue
        # A swap can STRAND a stone, and the stat vector cannot see it.
        # Reported live: replacing a Gossamer Robe (AC 12) with a Ringmail
        # Coat (AC 19) was offered as "+7 AC and no loss of other stats" --
        # true of stats, silent about the Minor Improved Damage I focus that
        # goes with it. The stone is a caster-robe stone and the coat is
        # plate, so they share no class and it CANNOT follow; its only legal
        # homes were two robes the player would no longer be wearing.
        #
        # Not dropped -- 7 AC may still be the better trade. But the cost is
        # stated, because "no loss" was the part that was wrong.
        if rec and cur_base and rec_base != cur_base:
            stranded = []
            for _x in exalts:
                if _item_base(_x.get("host") or "").lower() != cur_base:
                    continue
                _snm = re.sub(r"\s*[(]Exaltation[)]$", "", _x["name"]).strip()
                _rec_i = next((i for i in exalt_info
                               if i["name"].lower() == _snm.lower()), None) or {}
                if not _rec_i.get("targets_checked"):
                    continue          # never compared — assert nothing
                _dests = {d.strip().lower()
                          for d in (_rec_i.get("move_to") or "").split(",")
                          if d.strip()}
                if not any(_item_base(d) == rec_base or d == rec
                           for d in _dests):
                    stranded.append((_snm, _rec_i.get("effect") or "",
                                     _rec_i.get("move_to") or ""))
            bits = []
            for _snm, _eff, _dest in stranded:
                bits.append(
                    f"loses {_eff or _snm}: the {_snm} stone CANNOT move to "
                    f"{s.get('recommend')}"
                    + (f" (its only legal homes are {_dest})" if _dest
                       else " (no owned item can take it)"))
            # A stone is not the only way to lose an effect. An item's NATIVE
            # Effect line goes with the item, and no stone has to be involved:
            # Shining Metallic Robes grants Spell Haste II (15% cast time) from
            # an EMPTY socket, and a swap to a studded tunic was described as
            # costing only INT and two saves. The stat vector cannot see an
            # effect, so this has to be checked explicitly.
            if not stranded:
                try:
                    _cur_ln = await _item_line(str(s.get("current") or ""))
                    _rec_ln = await _item_line(str(s.get("recommend") or ""))
                except Exception:
                    _cur_ln = _rec_ln = None
                _eff_of = lambda l: (m.group(0) if l and
                                     (m := re.search(r"(?:Focus )?Effect: [^;|]+", l))
                                     else None)
                _cur_eff, _rec_eff = _eff_of(_cur_ln), _eff_of(_rec_ln)
                # only when we could READ both -- an unreadable line is not
                # evidence that an effect is absent
                if _cur_ln and _rec_ln and _cur_eff and _cur_eff != _rec_eff:
                    # A focus SOCKET is exposed by levelling the item: across
                    # 23 worn items, all 20 at +1 or more had one and none of
                    # the 3 at +0 did. So a +0 item's focus cannot be
                    # extracted at all -- replacing it loses the effect
                    # permanently, and the fix is to merge the item first,
                    # which is advice worth giving rather than a warning.
                    _stuck = _item_rank(str(s.get("current") or "")) == 0
                    bits.append(
                        f"loses the worn item's {_cur_eff}"
                        + (" — it is +0, so that focus has no socket yet and "
                           "CANNOT be moved; merge the item first if you want "
                           "to keep the effect" if _stuck else "")
                        + (f", replaced by {_rec_eff}" if _rec_eff
                           else "" if _stuck
                           else " — the replacement has no effect of its own"))
            if bits:
                s["why"] = (str(s.get("why") or "").rstrip(". ")
                            + ". COST — " + "; ".join(bits) + ".")
                logger.info("Slot rec %s costs an effect: %s",
                            s.get("slot"), "; ".join(bits)[:160])
        if rec and (rec in owned or rec_base in owned_base):
            wset = where_by_base.get(rec_base, set())
            # Nearest to hand first, then the rest of the storage the parser
            # can now name, then worn. Spelling out only bags and bank left an
            # item in the Hoard or the Equipment tab reporting no location.
            s["where"] = next((w for w in ("bags", "bank", "stash", "hoard",
                                           "depot", "worn") if w in wset), None)
            slots.append(s)
        else:
            logger.info("Dropped gear recommendation not in inventory: %s",
                        s.get("recommend"))
    # hands consistency: a 2H primary recommendation empties the secondary
    primary = next((s for s in slots
                    if str(s.get("slot", "")).lower() == "primary"
                    and s.get("recommend")), None)
    if primary:
        try:
            line = await _item_line(primary["recommend"])
        except Exception:
            line = None
        if line and "Skill: 2H" in line:
            before = len(slots)
            slots = [s for s in slots
                     if str(s.get("slot", "")).lower() != "secondary"]
            if len(slots) != before:
                logger.info("Dropped secondary slot rec — 2H primary "
                            "recommendation occupies both hands")
    pet_gear = []
    exalt_hosts = {(x.get("host") or "").lower()
                   for x in (ctx.get("exaltations") or [])}
    owned_locs = {}
    for it in items:
        owned_locs.setdefault(it["name"].lower(), it.get("where"))
    pet_worn = {v.lower() for v in (ctx.get("pet_inventory") or {}).values()}
    from backend.game_data import (_trio_usable as _tu, item_line as _il2,
                                   item_rank as _ir2,
                                   item_stat_vector as _vec2,
                                   scale_item_line as _scl2)
    # a FULL pet means every hand-over displaces something - precompute the
    # held items' scaled stat vectors so strictly-worse recs never show
    pet_full = pet_slots > 0 and len(pet_worn) >= pet_slots
    held_vecs = []
    if pet_full:
        for hnm in (ctx.get("pet_inventory") or {}).values():
            try:
                hline = await _il2(hnm)
            except Exception:
                hline = None
            if hline:
                hv = _vec2(_scl2(hline, _ir2(hnm)))
                if hv:
                    held_vecs.append((hnm, hv))
    # What the pet ALREADY occupies. A pet is a bag of generic slots, but
    # the items in it are not generic: two chests is as impossible for a
    # pet as for a player, and a two-hander leaves no hand for a second
    # weapon. Both rules were in the PROMPT only, and the model broke both
    # in one reply -- two robes, plus a 1H sword offered to a pet already
    # holding a 2H.
    held_2h = False
    held_weapons = 0
    for _hnm in list(pet_inv.values()):
        try:
            _hl = await _il2(_hnm)
        except Exception:
            _hl = None
        if _pet_category(_hl) == "WEAPON":
            held_weapons += 1
            if _is_2h(_hl):
                held_2h = True
    claimed: set = set()
    for ph in _clean_list(data.get("pet_gear"), ("item", "slot", "why"),
                          cap=max(0, int(pet_slots)),
                          require="item"):
        low = ph["item"].lower()
        if low in pet_worn:
            continue  # already on the pet
        where = owned_locs.get(low)
        if where not in RETRIEVABLE or low in exalt_hosts:
            logger.info("Dropped pet-gear rec (not spare): %s (%s)", ph["item"], where)
            continue
        try:
            rline = await _il2(ph["item"])
            usable = _tu(rline, pet_classes)
        except Exception:
            rline, usable = None, None
        if usable is False:
            logger.info("Dropped pet-gear rec — pet class can't use: %s", ph["item"])
            continue
        if held_vecs and rline:
            rvec = _vec2(_scl2(rline, _ir2(ph["item"])))
            dominated_by = next((hnm for hnm, hv in held_vecs
                                 if rvec and _pareto_beats(hv, rvec)), None)
            if dominated_by:
                logger.info("Dropped pet-gear rec - %s is strictly worse "
                            "than held %s", ph["item"], dominated_by)
                continue
        cat = _pet_category(rline)
        if cat == "WEAPON":
            # A held 2H occupies both hands; nothing else can be added.
            if held_2h:
                logger.info("Dropped pet-gear rec — pet holds a 2H, no room "
                            "for %s", ph["item"])
                continue
            if _is_2h(rline) and (held_weapons or "WEAPON" in claimed):
                logger.info("Dropped pet-gear rec — 2H %s cannot join "
                            "another weapon", ph["item"])
                continue
            if held_weapons + sum(1 for c in claimed if c == "WEAPON") >= 2:
                logger.info("Dropped pet-gear rec — pet already has two "
                            "weapons: %s", ph["item"])
                continue
            claimed.add("WEAPON")
            held_weapons += 1
            if _is_2h(rline):
                held_2h = True
        elif cat:
            # a SWAP for a held item of the same kind is fine; a second
            # recommendation of that kind is not
            if cat in claimed:
                logger.info("Dropped pet-gear rec — %s is a second %s",
                            ph["item"], cat)
                continue
            claimed.add(cat)
        ph["where"] = where
        pet_gear.append(ph)
    # Deterministic BACKFILL. A clear upgrade -- one that wins on every stat
    # the pet cares about and loses on none -- needs no judgement, so it is
    # not allowed to depend on the model having mentioned it. Trade-offs are
    # deliberately NOT backfilled: choosing between +6 damage and -10 STR is
    # the qualitative call, and silence is a better answer than a coin flip.
    already = {p["item"].lower() for p in pet_gear} | pet_worn
    for e in pet_shortlist:
        if len(pet_gear) >= pet_slots:
            break
        if e["verdict"] != "clear upgrade" or e["cand"].lower() in already:
            continue
        where = owned_locs.get(e["cand"].lower())
        if where not in RETRIEVABLE or e["cand"].lower() in exalt_hosts:
            continue
        cat = e["cat"]
        if cat == "WEAPON":
            if held_2h or held_weapons >= 2:
                continue
            claimed.add("WEAPON")
            held_weapons += 1
        elif cat:
            if cat in claimed:
                continue
            claimed.add(cat)
        gains = ", ".join(f"{k} {v:+g}" for k, v in
                          sorted(e["gain"].items(), key=lambda kv: -abs(kv[1])))
        pet_gear.append({
            "item": e["cand"], "slot": "", "where": where,
            "why": (f"beats held {e['vs']} on every stat that matters to a pet "
                    f"({gains}) and loses nothing" if e["vs"] else
                    f"fills a free pet slot ({gains})"),
        })
        already.add(e["cand"].lower())
        logger.info("Pet-gear backfill: %s (clear upgrade over %s)",
                    e["cand"], e["vs"] or "an empty slot")
    table = _full_slot_table(slots, ctx.get("worn"))
    prim = next((r for r in table if r["slot"] == "Primary"
                 and r.get("recommend")), None)
    if prim:
        try:
            pl = await _item_line(prim["recommend"])
        except Exception:
            pl = None
        if pl and "Skill: 2H" in pl:
            for r in table:
                if r["slot"] == "Secondary":
                    r["recommend"] = None
                    r["where"] = None
                    r["why"] = ("— freed by the recommended 2H primary "
                                "(occupies both hands)")
    return {**base, "source": "llm",
            "note": data.get("note"),
            "pet_gear": pet_gear,
            "slots": table,
            "farm": _clean_list(data.get("farm"),
                                ("item", "slot", "zone", "source", "why"),
                                cap=8, require="item"),
            "exaltations": exalt_info,
            "unknown": gear["unknown"][:10]}
