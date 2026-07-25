"""Where things live — the one place that knows about being frozen.

Running from source, everything is relative to the repo root exactly as it
always was. Running as the packaged executable, two different roots apply
and conflating them is the classic PyInstaller bug:

  * BUNDLED assets (the built UI, class guides, the eqlbuilds snapshot) are
    read-only and live inside the one-file extraction dir (sys._MEIPASS),
    which is a fresh temp directory on every launch.
  * WRITABLE state (the database, caches, mined geometry, user configs)
    must OUTLIVE the process, so it can never go in _MEIPASS. It goes
    beside the .exe when that is writable — keeping a portable install
    self-contained on a USB stick — and falls back to %LOCALAPPDATA% when
    it is not (Program Files, or a read-only share).

Import-time side effects are deliberate: data_dir() is created on first use
so sqlite, which cannot create its own directory, always has one.
"""
import os
import sys
from pathlib import Path

APP_NAME = "EQLCompanion"


def is_frozen() -> bool:
    """True inside the PyInstaller bundle."""
    return getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS")


def bundle_root() -> Path:
    """Root for READ-ONLY assets shipped with the app."""
    if is_frozen():
        return Path(sys._MEIPASS)  # type: ignore[attr-defined]
    return Path(__file__).resolve().parent.parent


def bundle_path(*parts: str) -> Path:
    """A read-only asset shipped with the app (UI, guides, data snapshots)."""
    return bundle_root().joinpath(*parts)


def _exe_dir() -> Path:
    """The directory the executable itself sits in (frozen only)."""
    return Path(sys.executable).resolve().parent


def _writable(directory: Path) -> bool:
    try:
        directory.mkdir(parents=True, exist_ok=True)
        probe = directory / ".write-probe"
        probe.write_bytes(b"")
        probe.unlink()
        return True
    except OSError:
        return False


_DATA_DIR: Path | None = None


def data_dir() -> Path:
    """Writable state root. Resolved once, created if missing.

    Source runs keep using ./data so existing installs and every relative
    path in the docs stay correct. EQL_DATA_DIR overrides both modes.
    """
    global _DATA_DIR
    if _DATA_DIR is not None:
        return _DATA_DIR
    override = os.environ.get("EQL_DATA_DIR")
    if override:
        candidate = Path(override).expanduser()
    elif is_frozen():
        beside = _exe_dir() / "data"
        if _writable(beside):
            candidate = beside
        else:
            base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
            candidate = Path(base) / APP_NAME / "data"
    else:
        candidate = Path("data")
    candidate.mkdir(parents=True, exist_ok=True)
    _DATA_DIR = candidate
    return candidate


def data_path(*parts: str) -> Path:
    """A file or directory inside the writable state root."""
    return data_dir().joinpath(*parts)

def child_command(module: str, flag: str) -> list:
    """Argv for re-launching ourselves as a helper window (the combat
    overlay, the OCR calibrator).

    From source that is just `python -m backend.overlay`. Frozen, there is
    no interpreter to hand — sys.executable IS the app, and passing it
    `-m` would simply boot a second copy of the server — so the packaged
    entrypoint dispatches on a flag instead.
    """
    if is_frozen():
        return [sys.executable, flag]
    return [sys.executable, "-m", module]


def child_cwd() -> Path:
    """Working directory for those helper processes."""
    return _exe_dir() if is_frozen() else bundle_root()
