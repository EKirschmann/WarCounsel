"""The measured-duration store: what it will and will not claim."""
import pytest

from backend import learned_durations as ld


@pytest.fixture(autouse=True)
def _scratch(tmp_path, monkeypatch):
    monkeypatch.setattr(ld, "FILE", tmp_path / "learned_durations.json")
    ld._reset_for_tests()
    yield
    ld._reset_for_tests()


CH = ld.char_key("Kenkyo", "freeport")


def test_one_or_two_cycles_are_measuring_not_known():
    assert ld.observe(CH, "Skin like Wood III", 1080)["usable"] is False
    assert ld.observe(CH, "Skin like Wood III", 1090)["usable"] is False
    assert ld.estimate(CH, "Skin like Wood III") is None
    assert ld.progress(CH, "skin like wood iii")["n"] == 2


def test_three_agreeing_cycles_become_a_usable_median_rounded_down():
    for s in (1080, 1095, 1088):
        ld.observe(CH, "Skin like Wood III", s)
    est = ld.estimate(CH, "Skin like Wood III")
    assert est and est["seconds"] == 1088 and est["agree"] == 3


def test_an_outlier_cycle_does_not_count_toward_agreement():
    """Two mobs sharing a spell measure the wrong cast; a refresh shortens
    the gap. Neither agrees with the true length, so neither votes."""
    for s in (300, 900, 60):
        ld.observe(CH, "Tangling Weeds", s)
    assert ld.estimate(CH, "Tangling Weeds") is None, "three samples, no three agree"
    for s in (905, 895):
        ld.observe(CH, "Tangling Weeds", s)
    est = ld.estimate(CH, "Tangling Weeds")
    assert est and est["seconds"] == 900 and est["agree"] == 3
    assert est["n"] == 5, "the outliers are kept on record, just outvoted"


def test_gaps_outside_the_cycle_band_are_refused():
    assert ld.observe(CH, "Root", 2) is None
    assert ld.observe(CH, "Root", 4 * 3600) is None
    assert ld.progress(CH, "Root") is None


def test_only_the_newest_samples_are_kept():
    for s in range(100, 100 + ld.MAX_SAMPLES + 4):
        ld.observe(CH, "Clarity", s)
    assert ld.progress(CH, "Clarity")["n"] == ld.MAX_SAMPLES
    assert ld.progress(CH, "Clarity")["seconds"] is not None


def test_characters_and_tiers_do_not_share_measurements():
    for s in (600, 600, 600):
        ld.observe(CH, "Haste II", s)
    assert ld.estimate(CH, "Haste II")["seconds"] == 600
    assert ld.estimate(CH, "Haste III") is None, "a tier is a different length"
    assert ld.estimate(ld.char_key("Someone", "freeport"), "Haste II") is None


def test_it_survives_a_reload():
    for s in (600, 600, 600):
        ld.observe(CH, "Haste II", s)
    ld._reset_for_tests()
    assert ld.estimate(CH, "Haste II")["seconds"] == 600
