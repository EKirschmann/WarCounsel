"""A correct game folder has to be savable BEFORE the first log exists.

Reported live (#12, Linux/CachyOS via Faugus Launcher): "I can not get the
path to work." The panel required Logs/eqlog_*.txt to be present and the
save endpoint rejected anything short of that with a 400 -- but that file
only appears after /log on, which the player cannot reach through an app
that will not accept where the game is. A fresh install has no Logs folder
at all.

So `ok` answers only "is this the EQL install folder", which is knowable
immediately, and "nothing to tail yet" became a `warn` that still saves.
Rejection is reserved for a folder that is not an install.
"""
import pytest

from backend.main import _describe_game_dir


@pytest.fixture
def install(tmp_path):
    """A real install the moment the launcher finishes: no logging yet."""
    d = tmp_path / "EverQuest Legends"
    d.mkdir()
    (d / "eqgame.exe").write_bytes(b"")
    return d


def test_missing_folder_is_rejected(tmp_path):
    v = _describe_game_dir(str(tmp_path / "nope"))
    assert (v["ok"], v["warn"]) == (False, False)


def test_folder_that_is_not_an_install_is_rejected(tmp_path):
    (tmp_path / "elsewhere").mkdir()
    v = _describe_game_dir(str(tmp_path / "elsewhere"))
    assert (v["ok"], v["warn"]) == (False, False)
    assert "EverQuest Legends" in v["reason"]


def test_install_without_a_logs_folder_saves_with_a_warning(install):
    """The reported case: nothing has ever been logged."""
    v = _describe_game_dir(str(install))
    assert (v["ok"], v["warn"]) == (True, True)
    assert v["log_count"] == 0
    assert "/log on" in v["reason"]


def test_install_with_an_empty_logs_folder_saves_with_a_warning(install):
    (install / "Logs").mkdir()
    v = _describe_game_dir(str(install))
    assert (v["ok"], v["warn"]) == (True, True)
    assert "/log on" in v["reason"]


def test_eqclient_ini_alone_identifies_an_install(tmp_path):
    """Detection accepts any of the three markers, not eqgame.exe only."""
    d = tmp_path / "EQL"
    d.mkdir()
    (d / "eqclient.ini").write_text("x", encoding="utf-8")
    assert _describe_game_dir(str(d))["ok"] is True


def test_logs_present_is_the_only_unqualified_pass(install):
    logs = install / "Logs"
    logs.mkdir()
    (logs / "eqlog_Someone_test.txt").write_text("x", encoding="utf-8")
    v = _describe_game_dir(str(install))
    assert (v["ok"], v["warn"]) == (True, False)
    assert v["log_count"] == 1
