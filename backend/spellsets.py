"""Read + write the game's saved spell sets (LO*.ini [SpellLoadouts]).

The game stores named 14-slot spell sets in <Name>_<server>_LO<N>.ini and
memorizes them in one command: /memspellset <name>. The companion writes its
recommended loadout as a set (default name "companion") so the whole
Memorize-now list lands on the spell bar with one command. Writes are
surgical — only the target set's lines change, everything else is preserved
byte-for-byte, and a one-time .companion-backup copy of the original is
kept beside the file.
"""
import logging
import re
import shutil
from pathlib import Path
from typing import Optional

from backend.config import settings

logger = logging.getLogger(__name__)

MAX_SLOTS = 14
_ENTRY = re.compile(r"^SpellLoadout(\d+)\.(inuse|name|slot\d+)=(.*)$")


def find_loadout_ini(name: str, server: str) -> Optional[Path]:
    game = Path(settings.eql_game_dir)
    cands = sorted(game.glob(f"{name}_{server}_LO*.ini"),
                   key=lambda p: p.stat().st_mtime, reverse=True)
    return cands[0] if cands else None


def _section_span(lines: list) -> tuple:
    start = next((i for i, l in enumerate(lines)
                  if l.strip().lower() == "[spellloadouts]"), None)
    if start is None:
        return None, None
    end = len(lines)
    for i in range(start + 1, len(lines)):
        if lines[i].startswith("["):
            end = i
            break
    return start, end


def read_spell_sets(path: Path) -> list:
    text = path.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    start, end = _section_span(lines)
    sets: dict = {}
    if start is None:
        return []
    for l in lines[start + 1:end]:
        m = _ENTRY.match(l.strip())
        if not m:
            continue
        idx, key, val = int(m.group(1)), m.group(2), m.group(3)
        s = sets.setdefault(idx, {"index": idx, "inuse": False,
                                  "name": None, "slots": {}})
        if key == "inuse":
            s["inuse"] = val.strip() == "1"
        elif key == "name":
            s["name"] = val.strip()
        else:
            s["slots"][int(key[4:])] = val.strip()
    out = []
    for idx in sorted(sets):
        s = sets[idx]
        if s["inuse"]:
            out.append({"index": idx, "name": s["name"],
                        "spell_ids": [int(v) for _, v in sorted(s["slots"].items())
                                      if v.lstrip("-").isdigit()]})
    return out


class GameRunning(RuntimeError):
    """The client owns this file right now; writing it would lose data."""


def write_spell_set(path: Path, set_name: str, spell_ids: list,
                    allow_while_running: bool = False) -> dict:
    """Create/overwrite the named set with up to 14 spell ids, first free
    slot if the name is new. Only that set's lines are touched.

    REFUSES while the game is running. Our write is surgical against the
    file, but the client holds the whole [SpellLoadouts] section in MEMORY
    and rewrites it wholesale when it flushes -- so a write during a session
    loses data in both directions:

      * the set we just wrote is erased by the client's next flush, and
      * a set the player saved in game, still only in memory, is not in the
        file we read, so it is absent from the copy we write back.

    Reported live: spell sets saved in game kept vanishing, and switching
    this feature off fixed it. Camping to desktop first makes the write
    safe, because the client has flushed and will not write again.
    """
    from backend.eqclient import game_running
    if not allow_while_running:
        try:
            running = game_running()
        except Exception:      # never block on a failed process probe
            running = False
        if running:
            raise GameRunning(
                "EverQuest Legends is running. It keeps saved spell sets in "
                "memory and rewrites them when it exits, so writing now "
                "would either be undone or would drop sets you saved in "
                "game. Camp to desktop, then write the set.")
    raw = path.read_bytes()
    nl = "\r\n" if b"\r\n" in raw else "\n"
    text = raw.decode("utf-8", errors="replace")
    lines = text.splitlines()
    start, end = _section_span(lines)
    if start is None:
        # The game writes [SpellLoadouts] LAZILY: it appears only after
        # you save a spell set in-game, so a fresh character's LO*.ini
        # has every other section and not this one. Refusing there fails
        # exactly the person this feature exists for -- someone with no
        # sets yet -- so create the section instead. The .companion-backup
        # below is still taken from the ORIGINAL file first, and no other
        # section is touched.
        while lines and not lines[-1].strip():
            lines.pop()
        lines.append("[SpellLoadouts]")
        start, end = len(lines) - 1, len(lines)

    existing = read_spell_sets(path)
    target = next((s["index"] for s in existing
                   if (s["name"] or "").lower() == set_name.lower()), None)
    if target is None:
        used = {s["index"] for s in existing}
        # inuse=0 lines exist for 1..60 — pick the lowest not in use
        target = next((i for i in range(1, 61) if i not in used), None)
        if target is None:
            raise ValueError("all 60 spell-set slots are in use")

    prefix = f"SpellLoadout{target}."
    body = [l for l in lines[start + 1:end]
            if not l.strip().startswith(prefix)]
    body.append(f"{prefix}inuse=1")
    body.append(f"{prefix}name={set_name}")
    for i, sid in enumerate(spell_ids[:MAX_SLOTS], 1):
        body.append(f"{prefix}slot{i}={sid}")

    backup = path.with_suffix(path.suffix + ".companion-backup")
    if not backup.exists():
        shutil.copy2(path, backup)

    new_lines = lines[:start + 1] + body + lines[end:]
    path.write_bytes((nl.join(new_lines) + nl).encode("utf-8"))
    logger.info("Wrote spell set %r (index %d, %d spells) to %s",
                set_name, target, len(spell_ids[:MAX_SLOTS]), path.name)
    return {"index": target, "name": set_name,
            "count": len(spell_ids[:MAX_SLOTS]), "file": path.name}
