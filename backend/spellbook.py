"""Owned-state ingestion: /outputfile spellbook + /alternateadv list.

`/outputfile spellbook` (in-game) writes <Name>_<server>-<CLS>-Spellbook.txt
into the game folder: "<level>\t<spell name>" per line. Real levels are
spells castable by the CURRENT class trio; level 255 entries are spells
owned via other loadouts.

`/alternateadv list` (in-game) prints owned AAs into the LOG; the parser for
that lives in log_system once a real sample exists (format TBD).
"""
import logging
import re
from datetime import datetime
import time
from pathlib import Path
from typing import Optional

from backend.config import settings

logger = logging.getLogger(__name__)

_cache: dict = {}


_find_cache: dict = {}


def find_spellbook(name: str, server: str) -> Optional[Path]:
    """Newest export for the character; the glob is memoized for 10s
    because snapshot() polls this every second."""
    key = (name.lower(), server.lower())
    hit = _find_cache.get(key)
    if hit and time.time() - hit[1] < 10:
        return hit[0]
    game = Path(settings.eql_game_dir)
    matches = sorted(game.glob(f"{name}_{server}-*-Spellbook.txt"),
                     key=lambda p: p.stat().st_mtime, reverse=True)
    path = matches[0] if matches else None
    _find_cache[key] = (path, time.time())
    return path


def load_spellbook(name: Optional[str], server: Optional[str]) -> Optional[dict]:
    """Parsed spellbook export, cached by file mtime. None when absent."""
    if not name or not server:
        return None
    path = find_spellbook(name, server)
    if not path:
        return None
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return None
    key = (str(path), mtime)
    if _cache.get("key") == key:
        return _cache["value"]
    castable, other = [], []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        parts = line.split("\t")
        if len(parts) != 2:
            continue
        try:
            lvl = int(parts[0])
        except ValueError:
            continue
        spell = parts[1].strip()
        if not spell:
            continue
        if lvl >= 255:
            other.append(spell)          # owned via another loadout
        else:
            castable.append({"level": lvl, "name": spell})
    castable.sort(key=lambda s: (s["level"], s["name"]))
    value = {
        "file": path.name,
        "updated": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(mtime)),
        "age_hours": round((time.time() - mtime) / 3600.0, 1),
        "pre_launch": _pre_launch(mtime),
        "castable": castable,
        "other_loadouts": sorted(set(other)),
    }
    _cache["key"] = key
    _cache["value"] = value
    return value


# ------------------------------------------------------------- other exports

EXPORT_KINDS = ("Spellbook", "MissingSpells", "Inventory", "Achievements")

# The slots that actually appear in the EQL inventory export (verified
# against a live file): no Charm / Power Source in this game — instead two
# generic "Any Slot"s (can hold any equippable item) plus Ammo and Held.
WORN_SLOTS = {
    "Any Slot", "Ear", "Head", "Face", "Neck", "Shoulders", "Arms", "Back",
    "Wrist", "Range", "Hands", "Primary", "Secondary", "Fingers", "Chest",
    "Legs", "Feet", "Waist", "Ammo", "Held",
}

_BANK_LOCATION_RE = re.compile(r"(?:bank|sharedbank)[1-9]\d*", re.IGNORECASE)
_HOARD_LOCATION_RE = re.compile(r"hoard [1-9]\d*", re.IGNORECASE)
_DEPOT_LOCATION_RE = re.compile(r"personal-depot[1-9]\d*", re.IGNORECASE)


# Storage you OWN and can go and fetch, as opposed to what is on your body.
# Lives beside the classifier that produces these values, because the two have
# to move together: #9 taught the parser to tell Equipment overflow, the
# Dragon's Hoard and the Personal Depot apart from bags, and three gates in
# generate_gear_advice were still spelling the answer out as ("bags", "bank").
# On a real export that silently dropped 21 items -- Ghoulbane +4 and the rest
# of an Equipment tab -- out of the pet-gear pool, purely because they had
# stopped being mislabelled. `bank` being on the old list is the giveaway that
# the rule was never "in your bags", it was "owned, not worn, go and get it".
RETRIEVABLE = frozenset({"bags", "bank", "stash", "hoard", "depot"})


def _inventory_where(location: str) -> str:
    """Classify an exact top-level location label from an inventory export."""
    if location in WORN_SLOTS:
        return "worn"
    if location.casefold() == "equipment":
        return "stash"
    if _BANK_LOCATION_RE.fullmatch(location):
        return "bank"
    if _HOARD_LOCATION_RE.fullmatch(location):
        return "hoard"
    if _DEPOT_LOCATION_RE.fullmatch(location):
        return "depot"
    return "bags"


_export_cache: dict = {}


def clear_find_cache() -> None:
    """Force fresh directory scans (the 'check exports' button)."""
    _find_cache.clear()


def _find_export(name: str, server: str, kind: str) -> Optional[Path]:
    """Newest '<name>_<server>*<Kind>.txt' (EQL inserts the class code)."""
    key = (name.lower(), server.lower(), kind.lower())
    hit = _find_cache.get(key)
    if hit and time.time() - hit[1] < 10:
        return hit[0]
    game = Path(settings.eql_game_dir)
    prefix = f"{name}_{server}".lower()
    suffix = f"{kind.lower()}.txt"
    best = None
    for p in game.glob(f"{name}_{server}*.txt"):
        low = p.name.lower()
        if low.startswith(prefix) and low.endswith(suffix):
            if best is None or p.stat().st_mtime > best.stat().st_mtime:
                best = p
    _find_cache[key] = (best, time.time())
    return best


def _parse_level_rows(text: str):
    castable, other = [], []
    for line in text.splitlines():
        parts = line.split("\t")
        if len(parts) != 2:
            continue
        try:
            lvl = int(parts[0])
        except ValueError:
            continue
        entry = parts[1].strip()
        if not entry:
            continue
        (other if lvl >= 255 else castable).append(
            entry if lvl >= 255 else {"level": lvl, "name": entry})
    castable.sort(key=lambda s: (s["level"], s["name"]))
    return castable, sorted(set(other))


def _is_ach_note(text: str) -> bool:
    """Is this criterion boilerplate rather than something to go and do?

    99 of 1,322 rows in a real export are one of four sentences about
    autocompleting or being bypassed with an unlock token. They carry a
    C/I marker like any other criterion, so counting them makes a class
    unlock look 6/8 when it is 6/6 — and it would skew a "closest to
    completion" sort, which is the whole point of showing progress.

    Matched on the PREFIX, deliberately: the game ships both "can be
    bypassed" and "can by bypassed", and a set of exact strings would
    silently miss the typo.
    """
    return text.strip().startswith("This achievement")


def _parse_achievements(text: str) -> dict:
    """The /outputfile achievements dump: a three-level tab outline.

    ```
    Untapped Potential: Classes          <- section, no tab
    C	Primary Class Unlock - Monk       <- achievement, one tab
    C		Obtain Sandals of Alacrity.     <- criterion, two tabs
    ```

    `C` is complete and `I` is incomplete, and the marker appears on BOTH
    levels — so this is per-criterion progress straight from the game, not
    inferred from what is sitting in your bags. That distinction is the
    whole reason to read this file: an item already turned in has left the
    inventory but its criterion stays `C`, and a class confirmed at
    creation autocompletes without the player ever holding the items.

    The file was unparsed until 2026-08-13 — the stub said "structure
    unknown until a real export exists" while a 1,841-line sample sat in
    the game folder.

    `EverQuest: Keys` and `General: Keys` are byte-identical duplicates in
    the real export, so sections are keyed by name and a repeat is merged
    rather than appended twice.
    """
    sections: dict = {}
    order: list = []
    cur = None
    for raw in text.splitlines():
        if not raw.strip():
            continue
        if "	" not in raw:                      # section heading
            cur = raw.strip()
            if cur not in sections:
                sections[cur] = []
                order.append(cur)
            continue
        if cur is None:
            continue
        # The marker leads the line and the tabs follow it -- "C	Name" is an
        # achievement, "C		Criterion" one of its criteria -- so depth is
        # counted AFTER the marker, not from the start of the line.
        mark, _, rest = raw.partition("	")
        done = mark.strip().upper() == "C"
        depth = 1 + (len(rest) - len(rest.lstrip("	")))
        text_ = rest.strip()
        if not text_:
            continue
        if depth == 1:                            # achievement
            entry = {"name": text_, "done": done, "criteria": []}
            # a duplicated section must not double the rows
            if not any(a["name"] == text_ for a in sections[cur]):
                sections[cur].append(entry)
        elif sections[cur]:                       # criterion
            crit = {"text": text_, "done": done, "note": _is_ach_note(text_)}
            last = sections[cur][-1]
            if not any(c["text"] == text_ for c in last["criteria"]):
                last["criteria"].append(crit)
    for name in order:
        for a in sections[name]:
            real = [c for c in a["criteria"] if not c["note"]]
            a["steps"] = len(real)
            a["steps_done"] = sum(1 for c in real if c["done"])
    out = [{"section": n,
            "achievements": sections[n],
            "done": sum(1 for a in sections[n] if a["done"]),
            "total": len(sections[n])} for n in order]
    return {"sections": out,
            "count": sum(len(s["achievements"]) for s in out),
            "done": sum(s["done"] for s in out)}


def load_export(name: Optional[str], server: Optional[str],
                kind: str) -> Optional[dict]:
    """Parsed export of the given kind, cached by mtime. None when absent.
    Formats: Spellbook/MissingSpells = 'level<TAB>name' rows; Inventory =
    TSV with a Location/Name header; Achievements = tab-depth outline (see
    _parse_achievements)."""
    if not name or not server:
        return None
    path = _find_export(name, server, kind)
    if not path:
        return None
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return None
    key = (str(path), mtime, kind, 6)  # bump on parser changes
    hit = _export_cache.get(key)
    if hit is not None:
        return hit
    text = path.read_text(encoding="utf-8", errors="replace")
    value = {
        "kind": kind,
        "file": path.name,
        "updated": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(mtime)),
        "age_hours": round((time.time() - mtime) / 3600.0, 1),
        "pre_launch": _pre_launch(mtime),
    }
    if kind in ("Spellbook", "MissingSpells"):
        castable, other = _parse_level_rows(text)
        value["castable"] = castable
        value["other_loadouts"] = other
        value["count"] = len(castable)
    elif kind == "Inventory":
        # Ear/Wrist/Fingers are PAIRED: the export emits two identical
        # location labels — number them or the second overwrites the first.
        # "<Loc>-SlotN" sub-rows are either bag contents (under General/Bank
        # containers) or ITEM SOCKETS: "(Exaltation)" entries live there.
        paired = {"Ear", "Wrist", "Fingers", "Any Slot"}
        worn, items, exalts, count, seen_slots = {}, [], [], 0, {}
        last_item_at = {}
        sub_re = re.compile(r"^(.+?)-Slot(\d+)$")
        current = None  # most-recent top-level item, to attach its sockets
        for line in text.splitlines():
            parts = line.split("\t")
            # The export has MORE than one header: a "KeyRing" section
            # carries its own "KeyRing<TAB>Name<TAB>ID" row, which passed the
            # location check and landed a phantom bag item called "Name" in
            # the inventory (and in the item count the advisor reports).
            if (len(parts) < 2 or parts[0].lower() == "location"
                    or parts[1].strip().lower() == "name"):
                continue
            count += 1
            loc, item = parts[0].strip(), parts[1].strip()
            # column 3 is the item ID. It is STABLE across +N merges (a
            # base item and its +2 share one id), which makes it the right
            # key for anything we learn and want to keep -- see item_facts.
            try:
                item_id = int(parts[2].strip()) if len(parts) > 2 else 0
                # Column 4 is the STACK SIZE and was being discarded, so 27
                # gnoll fangs and 42 phosphorous powder both read as one.
                # That is the number the quest tab is counting, and the
                # difference between "you have started this" and "you are
                # a third of the way through it".
                try:
                    stack = int(parts[3].strip()) if len(parts) > 3 else 1
                except ValueError:
                    stack = 1
                stack = max(1, stack)
            except ValueError:
                item_id = 0
                stack = 1
            empty = not item or item.lower() == "empty"
            m = sub_re.match(loc)
            if m:
                parent = m.group(1)
                slot_n = int(m.group(2))
                parent_where = _inventory_where(parent)
                # socket NUMBER encodes socket TYPE: a stone only fits a host
                # socket of the same number. Record every socket (empty too).
                if current is not None and current["loc"] == parent:
                    current.setdefault("sockets", {})[slot_n] = (
                        None if empty else item)
                if empty:
                    continue
                if "(exaltation)" in item.lower():
                    exalts.append({
                        "name": item, "socket": slot_n,
                        "host_loc": parent,
                        "host": last_item_at.get(parent),
                        "where": parent_where,
                    })
                    continue
                if parent_where in ("worn", "hoard"):
                    continue  # socket metadata is not a separate owned item
                items.append({"loc": loc,
                              "where": parent_where,
                              "name": item, "id": item_id, "count": stack})
                continue
            if empty:
                current = None
                continue
            last_item_at[loc] = item
            if loc in WORN_SLOTS:
                seen_slots[loc] = seen_slots.get(loc, 0) + 1
                key = (f"{loc} {seen_slots[loc]}" if loc in paired else loc)
                worn[key] = item
            where = _inventory_where(loc)
            entry = {"loc": loc, "where": where, "name": item,
                     "id": item_id, "count": stack, "sockets": {}}
            items.append(entry)
            current = entry
        value["worn"] = worn
        value["items"] = items
        # item name -> empty socket numbers (for exaltation move validation)
        socket_avail: dict = {}
        for it in items:
            socks = it.get("sockets") or {}
            if socks:
                socket_avail[it["name"].lower()] = {
                    n for n, v in socks.items() if v is None}
        value["item_sockets"] = socket_avail
        value["exaltations"] = exalts
        value["count"] = count
        # WORN position is authoritative slot data and costs nothing: the
        # Location column IS the slot. Learning it means a wiki-less item
        # can still be placed once it has been equipped even once, on any
        # character. Fails soft -- a cache write must never break an export.
        try:
            from backend import item_facts
            item_facts.learn(items)
        except Exception:
            logger.debug("item_facts learn skipped", exc_info=True)
    else:  # Achievements
        value.update(_parse_achievements(text))
    _export_cache[key] = value
    if len(_export_cache) > 64:
        _export_cache.clear()
    return value


def _pre_launch(mtime: float) -> bool:
    """Was this file written before the game launched?

    An export from beta is not merely stale: characters do not necessarily
    survive a launch, so its spells and gear may describe someone who no
    longer exists. "146h old" reads as slightly out of date; "from before
    launch" tells the user to re-export before trusting any counsel.
    """
    from backend.config import settings
    try:
        launch = datetime.fromisoformat(settings.eql_launch_iso)
    except (TypeError, ValueError):
        return False
    return datetime.fromtimestamp(mtime) < launch


def exports_status(name: Optional[str], server: Optional[str]) -> dict:
    """Presence + freshness of every export kind (for the sync chips)."""
    out = {}
    for kind in EXPORT_KINDS:
        e = load_export(name, server, kind)
        out[kind.lower()] = (
            {"found": True, "file": e["file"], "updated": e["updated"],
             "age_hours": e["age_hours"],
             "pre_launch": e.get("pre_launch", False),
             "count": e.get("count")}
            if e else {"found": False})
    return out
