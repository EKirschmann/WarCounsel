"""Self-update for the packaged build — download, verify, swap, relaunch.

A running .exe cannot be OVERWRITTEN on Windows, which is why this app has
always pointed at the releases page and asked people to replace the file by
hand. But a running .exe CAN be RENAMED: the loader holds the file object,
not the directory entry, so moving the old binary aside frees its name
without fighting a lock that cannot be won. That rename is the whole
mechanism, and everything below is arranged so the rename is the only step
that has to succeed atomically.

**The helper that performs the swap is the NEWLY DOWNLOADED BUILD**, run
with ``--apply-update``. Two reasons, both inherited from the helper windows
in ``backend.paths.child_command``:

  * A frozen build has no interpreter to hand, so re-invoking ourselves
    behind a flag is already how this codebase spawns helpers.
  * The swap logic then SHIPS WITH THE VERSION BEING INSTALLED. A .cmd
    script written by the OLD build would carry the old build's bugs
    forever, and the one mechanism that must never need a manual fix is the
    one that delivers fixes.

**Nothing is executed before its SHA256 matches the .sha256 published beside
it.** That check aborts; it does not warn. This is the only code path in the
app that runs a file fetched off the network, so the gate is authoritative
in the same way the advisor's verifiers are — a missing hash asset is a
refusal, never a shrug.

Two build variants ship, and they are swapped differently:

  * ``onefile`` — ``WarCounsel.exe``. One file replaces one file.
  * ``onedir`` — ``WarCounsel-OCR.zip``, which unpacks to ``WarCounsel.exe``
    plus ``_internal/``. **``data/`` lives INSIDE that folder**, so the
    directory is never replaced wholesale; only the two entries the build
    actually ships are moved aside. Anything the user put there survives,
    which a recursive replace would have deleted along with their sessions.
"""
from __future__ import annotations

import ctypes
import hashlib
import logging
import os
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
import zipfile
from pathlib import Path
from typing import Callable, Optional

from backend.paths import data_path, is_frozen

log = logging.getLogger(__name__)

REPO = "EKirschmann/WarCounsel"
RELEASES_URL = f"https://github.com/{REPO}/releases/latest"

# (payload, its published checksum) per build variant. The checksum file is
# one line: "<lowercase hex>  <payload name>", written by release.yml.
ASSETS = {
    "onefile": ("WarCounsel.exe", "WarCounsel.exe.sha256"),
    "onedir": ("WarCounsel-OCR.zip", "WarCounsel-OCR.zip.sha256"),
}

# The entries a onedir build actually ships. Everything else in the folder
# — data/, a user's notes, a shortcut — is left exactly where it is.
ONEDIR_ENTRIES = ("WarCounsel.exe", "_internal")

# How long the helper waits for the app to go away before giving up. Long
# enough for a slow shutdown (the lifespan handler snapshots the session),
# short enough that a wedged process does not leave a helper resident for
# the rest of the day.
EXIT_WAIT_S = 300.0

# Set by run_companion._serve() when a native window is running, so the
# update can close the app the same way the user does. Absent (browser
# fallback, or source runs) the user is asked to close it themselves —
# which still works, because the helper waits.
QUIT_HOOK: Optional[Callable[[], None]] = None


# --------------------------------------------------------------------------
# which build am I
# --------------------------------------------------------------------------

def variant() -> str:
    """``onedir`` when the PyInstaller payload sits beside the executable.

    A one-file build extracts to a temp dir that is nowhere near the .exe;
    a one-dir build's ``_MEIPASS`` IS ``_internal`` next to it. Comparing
    the two parents is exact and needs no build-time flag to be threaded
    through — one less thing that can disagree with reality.
    """
    if not is_frozen():
        return "source"
    meipass = Path(getattr(sys, "_MEIPASS")).resolve()
    exe_dir = Path(sys.executable).resolve().parent
    return "onedir" if meipass.parent == exe_dir else "onefile"


def target_exe() -> Path:
    """The executable this install launches from — what gets replaced."""
    return Path(sys.executable).resolve()


# --------------------------------------------------------------------------
# progress, for the UI to poll
# --------------------------------------------------------------------------

_LOCK = threading.Lock()
_STATE: dict = {"phase": "idle", "detail": "", "pct": None,
                "tag": None, "error": None, "staged": False}


def status() -> dict:
    with _LOCK:
        return dict(_STATE)


def _set(**kw) -> None:
    with _LOCK:
        _STATE.update(kw)


def _reset(tag: str) -> None:
    with _LOCK:
        _STATE.clear()
        _STATE.update({"phase": "starting", "detail": "", "pct": 0,
                       "tag": tag, "error": None, "staged": False})


def busy() -> bool:
    return status()["phase"] not in ("idle", "done", "failed")


# --------------------------------------------------------------------------
# fetching
# --------------------------------------------------------------------------

def _ssl_ctx():
    """certifi's bundle where available — the same reasoning as
    update_companion.py: some Windows Pythons, and antivirus HTTPS
    scanning, cannot validate GitHub against the system store.
    Verification is NEVER disabled; this downloads an executable."""
    from backend.wiki_http import _ssl_ctx as ctx
    return ctx()


def _request(url: str):
    """Plain releases/download URLs, never the API: unauthenticated API
    calls are capped at 60/hour PER IP, which guildmates behind one address
    hit, and the website imposes no such limit — the same reason
    /api/update-check carries a no-API fallback."""
    return urllib.request.Request(url, headers={"User-Agent": "warcounsel-updater"})


def _download_text(url: str, timeout: int = 60) -> str:
    with urllib.request.urlopen(_request(url), timeout=timeout,
                                context=_ssl_ctx()) as r:
        return r.read().decode("utf-8", "replace")


def _download_to(url: str, dest: Path, timeout: int = 600,
                 on_bytes: Optional[Callable[[int, int], None]] = None) -> str:
    """Stream an asset to ``dest`` and return its SHA256.

    Streamed rather than buffered because the OCR build's archive is ~200MB
    — holding that in memory ON TOP of a running app is how an update would
    come to work for everyone except the users of the larger build, which is
    the sort of failure nobody would reproduce. Hashing on the way past also
    means the digest describes THE BYTES THAT REACHED DISK, not the bytes we
    believed we received.
    """
    digest = hashlib.sha256()
    got = 0
    with urllib.request.urlopen(_request(url), timeout=timeout,
                                context=_ssl_ctx()) as r:
        total = int(r.headers.get("Content-Length") or 0)
        with open(dest, "wb") as out:
            while True:
                chunk = r.read(262144)
                if not chunk:
                    break
                out.write(chunk)
                digest.update(chunk)
                got += len(chunk)
                if on_bytes:
                    on_bytes(got, total)
    return digest.hexdigest()


def _asset_url(tag: str, name: str) -> str:
    return f"https://github.com/{REPO}/releases/download/{tag}/{name}"


def _expected_hash(text: str, payload: str) -> str:
    """Read the hash out of a ``<hex>  <name>`` checksum file.

    The name is checked, not just the hex: a checksum file that describes a
    DIFFERENT artifact would otherwise be accepted and then fail the
    comparison with a confusing message, or — worse, if the two ever shared
    a hash format — pass while describing something else.
    """
    for line in text.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[1].lstrip("*") == payload:
            return parts[0].lower()
    # a bare hash with no filename is still usable and some tools emit it
    stripped = text.strip()
    if len(stripped) == 64 and all(c in "0123456789abcdefABCDEF" for c in stripped):
        return stripped.lower()
    raise ValueError(f"no SHA256 for {payload} in the published checksum file")


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


# --------------------------------------------------------------------------
# staging
# --------------------------------------------------------------------------

def staging_root() -> Path:
    return data_path("update")


def _clean_staging() -> None:
    """Old attempts are removed before a new one, not after. A failed run
    that leaves 44MB behind would otherwise accumulate silently, and
    cleaning on the way IN means the evidence from the last failure is
    still on disk while anybody is looking at it."""
    root = staging_root()
    if not root.is_dir():
        return
    for child in root.iterdir():
        try:
            shutil.rmtree(child) if child.is_dir() else child.unlink()
        except OSError as e:
            log.info("could not clear staging entry %s: %s", child, e)


def stage(tag: str) -> Path:
    """Download and verify the release, unpack it, and return the executable
    that will act as the helper. Raises on any failure — a staged artifact
    that did not verify is never returned and never run."""
    kind = variant()
    if kind not in ASSETS:
        raise RuntimeError("self-update applies to the packaged build only")
    payload, checksum = ASSETS[kind]

    _clean_staging()
    work = staging_root() / tag
    work.mkdir(parents=True, exist_ok=True)

    _set(phase="checksum", detail=f"fetching {checksum}", pct=0)
    want = _expected_hash(_download_text(_asset_url(tag, checksum)), payload)

    _set(phase="downloading", detail=payload, pct=0)

    def progress(got: int, total: int) -> None:
        _set(pct=int(got * 100 / total) if total else None,
             detail=f"{payload} — {got // 1048576} MB"
                    + (f" of {total // 1048576} MB" if total else ""))

    archive = work / payload
    got = _download_to(_asset_url(tag, payload), archive, on_bytes=progress)

    _set(phase="verifying", detail="checking the signature of the download",
         pct=100)
    if got != want:
        # Do not keep it. A verified-bad artifact sitting in the staging
        # folder is one mistaken double-click away from being the thing
        # this whole gate exists to prevent.
        _rm(archive)
        raise RuntimeError(
            f"{payload} does not match its published SHA256 "
            f"(expected {want[:12]}…, got {got[:12]}…). Nothing was installed.")

    if kind == "onefile":
        exe = work / "WarCounsel.exe"
        os.replace(archive, exe)
        return exe

    _set(phase="unpacking", detail=payload)
    tree = work / "new"
    tree.mkdir(exist_ok=True)
    with zipfile.ZipFile(archive) as z:
        _safe_extract(z, tree)
    archive.unlink(missing_ok=True)
    exe = tree / "WarCounsel.exe"
    if not exe.is_file():
        raise RuntimeError(f"{payload} does not contain WarCounsel.exe")
    return exe


def _safe_extract(z: zipfile.ZipFile, dest: Path) -> None:
    """Extract, refusing any member that would land outside ``dest``.

    The archive is our own CI's and its hash has already been checked, so
    this is belt and braces — but the cost of being wrong here is writing
    an attacker-named path with the user's privileges, and a verified
    archive is exactly the one nobody would think to re-examine.
    """
    root = dest.resolve()
    for member in z.infolist():
        out = (root / member.filename).resolve()
        if not str(out).startswith(str(root) + os.sep) and out != root:
            raise RuntimeError(f"archive member escapes the target dir: {member.filename}")
    z.extractall(root)


# --------------------------------------------------------------------------
# handing off
# --------------------------------------------------------------------------

def helper_command(helper: Path, target: Path) -> list:
    """Argv for the downloaded build, asked to install itself over us."""
    return [str(helper), "--apply-update",
            "--target", str(target),
            "--wait-pid", str(os.getpid()),
            "--log", str(data_path("update.log"))]


def spawn_helper(helper: Path, target: Path) -> int:
    """Start the helper detached, so it outlives the process it is waiting
    for. DETACHED_PROCESS rather than a console: the packaged build is
    windowed and a console flashing up on exit reads as a crash."""
    flags = 0
    if os.name == "nt":
        flags = getattr(subprocess, "DETACHED_PROCESS", 0x00000008) | \
                getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200)
    proc = subprocess.Popen(helper_command(helper, target), close_fds=True,
                            cwd=str(helper.parent), creationflags=flags)
    return proc.pid


def run(tag: str, quit_after: bool = True) -> None:
    """Stage the release and hand off to the helper. Runs on a worker
    thread; progress is readable through ``status()``."""
    _reset(tag)
    target = target_exe()
    try:
        helper = stage(tag)
        _set(phase="handing off", detail="starting the installer")
        spawn_helper(helper, target)
        _set(phase="done", staged=True,
             detail="Downloaded and verified. WarCounsel will close, swap "
                    "itself for the new build, and reopen.")
    except Exception as e:
        log.exception("self-update failed")
        _set(phase="failed", error=f"{type(e).__name__}: {e}",
             detail="Nothing was installed — the app you are running is "
                    "untouched.")
        return
    if quit_after and QUIT_HOOK is not None:
        # Give the browser one poll to see "done" before the window goes.
        threading.Timer(1.5, _quit).start()


def _quit() -> None:
    try:
        if QUIT_HOOK is not None:
            QUIT_HOOK()
    except Exception:
        log.exception("could not close the window for the update")


# --------------------------------------------------------------------------
# the helper side — this runs inside the NEW build
# --------------------------------------------------------------------------

def _wait_for_exit(pid: int, timeout_s: float) -> bool:
    """Block until ``pid`` exits. True if it is gone.

    ``WaitForSingleObject`` on a SYNCHRONIZE handle rather than a poll
    loop: it is exact, and it costs nothing while waiting. A handle that
    cannot be opened means the process has already gone, which is the
    normal race — the app can exit before the helper gets this far.
    """
    if os.name != "nt":
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            try:
                os.kill(pid, 0)
            except OSError:
                return True
            time.sleep(0.25)
        return False
    SYNCHRONIZE = 0x00100000
    k32 = ctypes.windll.kernel32
    handle = k32.OpenProcess(SYNCHRONIZE, False, int(pid))
    if not handle:
        return True
    try:
        return k32.WaitForSingleObject(handle, int(timeout_s * 1000)) == 0
    finally:
        k32.CloseHandle(handle)


def _swap(new: Path, live: Path) -> list:
    """Put ``new`` where ``live`` is, atomically enough to be recoverable.

    Three steps, in this order, because each one is individually reversible
    and only the middle pair must not be interrupted:

      1. copy the new content to ``<name>.new`` — slow, and touches nothing
         anybody is using
      2. rename ``<name>`` to ``<name>.old`` — frees the name even though
         the file may still be mapped by a process that has not finished
         dying
      3. rename ``<name>.new`` to ``<name>``

    A failure at 3 renames ``.old`` straight back, so the install is either
    the old version or the new one and never a mixture. Returns the
    ``.old`` paths for the caller to sweep once the new build is running.
    """
    staged = live.with_name(live.name + ".new")
    if staged.exists():
        _rm(staged)
    if new.is_dir():
        shutil.copytree(new, staged)
    else:
        shutil.copy2(new, staged)
        if _sha256_file(staged) != _sha256_file(new):
            _rm(staged)
            raise RuntimeError(f"{live.name} copied badly (disk full?) — not installed")

    old = live.with_name(live.name + ".old")
    if old.exists():
        _rm(old)
    had_live = live.exists()
    if had_live:
        os.replace(live, old)
    try:
        os.replace(staged, live)
    except OSError:
        if had_live:
            os.replace(old, live)   # put it back exactly as it was
        raise
    return [old] if had_live else []


def _rm(path: Path) -> None:
    try:
        shutil.rmtree(path) if path.is_dir() else path.unlink(missing_ok=True)
    except OSError as e:
        log.info("could not remove %s: %s", path, e)


def apply_update(target: Path, wait_pid: int) -> int:
    """Install this build over ``target`` and relaunch it. Runs inside the
    downloaded build, after the app it replaces has exited."""
    log.info("installer starting: target=%s wait_pid=%s variant=%s",
             target, wait_pid, variant())

    if not _wait_for_exit(wait_pid, EXIT_WAIT_S):
        log.error("WarCounsel (pid %s) is still running after %.0fs — "
                  "nothing was changed", wait_pid, EXIT_WAIT_S)
        return 2

    # The image is unmapped a moment after the process object goes.
    time.sleep(0.6)

    me = Path(sys.executable).resolve()
    kind = variant()
    swept: list = []
    try:
        if kind == "onedir":
            src = me.parent
            for name in ONEDIR_ENTRIES:
                item = src / name
                if not item.exists():
                    raise RuntimeError(f"the downloaded build has no {name}")
                swept += _swap(item, target.parent / name)
        else:
            swept += _swap(me, target)
    except Exception:
        log.exception("install failed — the previous version is still in place")
        return 1

    log.info("installed; relaunching %s", target)
    try:
        subprocess.Popen([str(target)], cwd=str(target.parent), close_fds=True)
    except OSError:
        log.exception("installed, but could not relaunch")

    # Best effort, and deliberately last: the old binary may still be
    # mapped for a few seconds. A leftover .old is cosmetic — the next
    # update sweeps it — where deleting it before the relaunch is not.
    for path in swept:
        for _ in range(10):
            time.sleep(0.5)
            _rm(path)
            if not path.exists():
                break
    return 0


def sweep_leftovers(target: Path) -> None:
    """Remove ``.old`` files a previous install could not delete while they
    were still mapped. Called at startup, where they are certainly free."""
    names = ONEDIR_ENTRIES if variant() == "onedir" else (target.name,)
    for name in names:
        stale = target.parent / (name + ".old")
        if stale.exists():
            log.info("clearing %s left by a previous update", stale.name)
            _rm(stale)
