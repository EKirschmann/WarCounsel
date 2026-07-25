"""Read the game's own eqclient.ini to see whether logging is enabled.

READ ONLY, deliberately. Other companions flip `Log=1` themselves so the
user never types `/log on`; this one will not write to a game file it was
not asked to write to. Reading it is enough to tell the difference between
the two cases that look identical from outside:

  * logging was never switched on -> nothing will ever appear, and the user
    needs to type /log on
  * logging is on but the character has not zoned/fought yet -> just wait

Without this the app can only say "no log file found", which is the same
message in both cases and sends people hunting for a problem that is not
there.

Both lookups are cached: _sync_hints() runs on every snapshot (~6/s) and
neither a file read nor a process scan belongs on that path.
"""
import logging
import time
from pathlib import Path
from typing import Optional

from backend.config import settings

logger = logging.getLogger(__name__)

GAME_PROCESS = "eqgame.exe"
_INI_NAME = "eqclient.ini"

_ini_cache: dict = {"path": None, "mtime": None, "value": None}
_proc_cache: dict = {"checked": 0.0, "running": False}


def ini_path() -> Path:
    return Path(settings.eql_game_dir) / _INI_NAME


def logging_enabled() -> Optional[bool]:
    """True/False from eqclient.ini's `Log=` setting, or None when the file
    is missing or has no such key (older clients wrote it only once toggled).
    Cached by mtime — the game rewrites this file when it exits."""
    path = ini_path()
    try:
        mtime = path.stat().st_mtime
    except OSError:
        _ini_cache.update(path=str(path), mtime=None, value=None)
        return None
    if _ini_cache["path"] == str(path) and _ini_cache["mtime"] == mtime:
        return _ini_cache["value"]
    value = None
    try:
        # cp1252 to match the rest of the client's files; the key sits under
        # [Defaults] but a plain scan is enough and survives section drift
        for line in path.read_text(encoding="cp1252",
                                   errors="replace").splitlines():
            bare = line.strip()
            if bare.lower().startswith("log="):
                value = bare.split("=", 1)[1].strip() == "1"
                break
    except OSError:
        value = None
    _ini_cache.update(path=str(path), mtime=mtime, value=value)
    return value


def game_running() -> bool:
    """Is eqgame.exe alive? Cached 5s — process scans are not free."""
    now = time.monotonic()
    if now - _proc_cache["checked"] <= 5.0:
        return _proc_cache["running"]
    _proc_cache["checked"] = now
    running = False
    try:
        import psutil
        running = any(
            p.info["name"] and p.info["name"].lower() == GAME_PROCESS
            for p in psutil.process_iter(["name"]))
    except Exception:
        running = False
    _proc_cache["running"] = running
    return running


def logging_off_in_game() -> bool:
    """The case worth interrupting someone for: they are playing RIGHT NOW
    and the client is not writing a log, so nothing they do will register."""
    return game_running() and logging_enabled() is False


def status() -> dict:
    return {
        "ini": str(ini_path()),
        "ini_found": ini_path().is_file(),
        "logging_enabled": logging_enabled(),
        "game_running": game_running(),
    }
