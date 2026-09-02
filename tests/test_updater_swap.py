"""The self-update's file swap, and the gates in front of it.

Everything here is filesystem-only and offline. The swap is the one piece
that can leave a user with no working install, so the rollback is tested
before the happy path.
"""
import os
import sys
import zipfile
from pathlib import Path

import pytest

from backend import updater


# --------------------------------------------------------------------------
# the swap
# --------------------------------------------------------------------------

def test_swap_replaces_and_hands_back_the_old_file(tmp_path):
    live = tmp_path / "WarCounsel.exe"
    live.write_bytes(b"OLD BUILD")
    new = tmp_path / "staged" / "WarCounsel.exe"
    new.parent.mkdir()
    new.write_bytes(b"NEW BUILD")

    swept = updater._swap(new, live)

    assert live.read_bytes() == b"NEW BUILD"
    assert swept == [live.with_name("WarCounsel.exe.old")]
    assert swept[0].read_bytes() == b"OLD BUILD", "the old build must survive for rollback"
    assert not live.with_name("WarCounsel.exe.new").exists(), "no staging file left behind"


def test_swap_rolls_back_when_the_final_rename_fails(tmp_path, monkeypatch):
    """The one moment the install is not the old version or the new one is
    between the two renames. If the second fails, the first is undone."""
    live = tmp_path / "WarCounsel.exe"
    live.write_bytes(b"OLD BUILD")
    new = tmp_path / "staged.exe"
    new.write_bytes(b"NEW BUILD")

    real_replace = os.replace
    calls = {"n": 0}

    def flaky(src, dst):
        calls["n"] += 1
        if calls["n"] == 2:          # .new -> live, the step that must be undone
            raise OSError(5, "Access is denied")
        return real_replace(src, dst)

    monkeypatch.setattr(updater.os, "replace", flaky)

    with pytest.raises(OSError):
        updater._swap(new, live)

    assert live.exists(), "the install must never be left with no executable"
    assert live.read_bytes() == b"OLD BUILD"
    assert not live.with_name("WarCounsel.exe.old").exists()


def test_swap_refuses_a_copy_that_did_not_land_intact(tmp_path, monkeypatch):
    """A short write (a full disk) must not be renamed into place. The
    check is a re-hash of what actually reached the filesystem, not of the
    bytes we meant to write."""
    live = tmp_path / "WarCounsel.exe"
    live.write_bytes(b"OLD BUILD")
    new = tmp_path / "staged.exe"
    new.write_bytes(b"NEW BUILD, ALL OF IT")

    def truncating_copy(src, dst):
        Path(dst).write_bytes(Path(src).read_bytes()[:4])

    monkeypatch.setattr(updater.shutil, "copy2", truncating_copy)

    with pytest.raises(RuntimeError, match="copied badly"):
        updater._swap(new, live)

    assert live.read_bytes() == b"OLD BUILD"
    assert not live.with_name("WarCounsel.exe.new").exists()


def test_onedir_swap_leaves_the_data_folder_alone(tmp_path):
    """data/ lives INSIDE a onedir install, so only the entries the build
    ships may be touched. Replacing the folder wholesale would delete the
    user's sessions, settings and mined geometry."""
    install = tmp_path / "WarCounsel"
    (install / "_internal").mkdir(parents=True)
    (install / "_internal" / "base_library.zip").write_bytes(b"old lib")
    (install / "WarCounsel.exe").write_bytes(b"OLD BUILD")
    (install / "data").mkdir()
    (install / "data" / "companion.db").write_bytes(b"a whole season of play")
    (install / "notes.txt").write_text("mine")

    staged = tmp_path / "staged"
    (staged / "_internal").mkdir(parents=True)
    (staged / "_internal" / "base_library.zip").write_bytes(b"new lib")
    (staged / "WarCounsel.exe").write_bytes(b"NEW BUILD")

    for name in updater.ONEDIR_ENTRIES:
        updater._swap(staged / name, install / name)

    assert (install / "WarCounsel.exe").read_bytes() == b"NEW BUILD"
    assert (install / "_internal" / "base_library.zip").read_bytes() == b"new lib"
    assert (install / "data" / "companion.db").read_bytes() == b"a whole season of play"
    assert (install / "notes.txt").read_text() == "mine"


# --------------------------------------------------------------------------
# the gates in front of it
# --------------------------------------------------------------------------

def test_checksum_file_must_describe_the_artifact_we_downloaded():
    """A checksum file naming a different asset is refused rather than
    compared. The OCR zip and the one-file exe are published side by side,
    so picking up the wrong one is a real mistake, not a hypothetical."""
    published = ("d1e8...  WarCounsel-OCR.zip\n")
    with pytest.raises(ValueError, match="no SHA256 for WarCounsel.exe"):
        updater._expected_hash(published, "WarCounsel.exe")


def test_checksum_file_is_read_by_name_not_by_position():
    published = ("aaaa  WarCounsel-OCR.zip\n"
                 "bbbb  WarCounsel.exe\n")
    assert updater._expected_hash(published, "WarCounsel.exe") == "bbbb"


def test_bare_hash_is_accepted():
    assert updater._expected_hash("A" * 64 + "\n", "WarCounsel.exe") == "a" * 64


def test_extract_refuses_a_member_that_escapes_the_target(tmp_path):
    """The archive is our own CI's and its hash is already checked, so this
    is belt and braces — but a verified archive is exactly the one nobody
    would re-examine, and the cost of being wrong is an arbitrary write."""
    archive = tmp_path / "evil.zip"
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr("WarCounsel.exe", "fine")
        z.writestr("../../escaped.txt", "not fine")

    dest = tmp_path / "out"
    dest.mkdir()
    with zipfile.ZipFile(archive) as z:
        with pytest.raises(RuntimeError, match="escapes the target dir"):
            updater._safe_extract(z, dest)


# --------------------------------------------------------------------------
# which build am I — this decides which asset gets downloaded
# --------------------------------------------------------------------------

def test_variant_reads_the_layout_rather_than_a_build_flag(tmp_path, monkeypatch):
    """A one-file build extracts to a temp dir far from the .exe; a one-dir
    build's payload IS _internal beside it. Comparing the two parents needs
    no flag threaded through the build, so there is nothing to fall out of
    step with reality."""
    install = tmp_path / "WarCounsel"
    install.mkdir()
    exe = install / "WarCounsel.exe"
    exe.write_bytes(b"")

    monkeypatch.setattr(updater.sys, "executable", str(exe))
    monkeypatch.setattr(updater, "is_frozen", lambda: True)

    monkeypatch.setattr(updater.sys, "_MEIPASS", str(install / "_internal"),
                        raising=False)
    assert updater.variant() == "onedir"

    unpacked = tmp_path / "Temp" / "_MEI123456"
    unpacked.mkdir(parents=True)
    monkeypatch.setattr(updater.sys, "_MEIPASS", str(unpacked), raising=False)
    assert updater.variant() == "onefile"


def test_source_runs_have_no_variant_and_cannot_stage():
    """Running from a checkout there is no .exe to replace, and the source
    updater (update_companion.py) is the right tool. stage() says so rather
    than downloading something it could not install."""
    assert updater.variant() == "source"
    with pytest.raises(RuntimeError, match="packaged build only"):
        updater.stage("v9.9.9")


def test_wait_for_exit_against_real_processes():
    """The one ctypes call in the module. A handle that cannot be opened
    means the process has already gone — the normal race, since the app can
    exit before the installer gets this far — and must not read as a
    timeout, which would abandon the update."""
    import subprocess
    import time

    live = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(1.0)"])
    start = time.time()
    assert updater._wait_for_exit(live.pid, 20) is True
    assert 0.5 < time.time() - start < 10, "returned without actually waiting"

    live.wait()
    assert updater._wait_for_exit(live.pid, 5) is True, "an exited pid is 'gone', not a timeout"

    stubborn = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        assert updater._wait_for_exit(stubborn.pid, 0.5) is False
    finally:
        stubborn.kill()


def test_sweep_removes_a_leftover_old_binary(tmp_path, monkeypatch):
    """The installer cannot always delete the previous binary — it may
    still be mapped for a few seconds after the relaunch. Startup finishes
    the job, where it is certainly free."""
    exe = tmp_path / "WarCounsel.exe"
    exe.write_bytes(b"current")
    stale = tmp_path / "WarCounsel.exe.old"
    stale.write_bytes(b"previous")

    monkeypatch.setattr(updater, "variant", lambda: "onefile")
    updater.sweep_leftovers(exe)

    assert not stale.exists()
    assert exe.read_bytes() == b"current", "the live binary is not the sweep's business"
