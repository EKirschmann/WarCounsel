"""A slot swap can STRAND an exaltation stone, and stats cannot see it.

Reported live: replacing a Gossamer Robe (AC 12) with a Ringmail Coat (AC 19)
was offered as "+7 AC in a free-choice slot and no loss of other stats". True
of stats; silent about the Minor Improved Damage I focus that went with it.

    Smoldering Robe stone   classes NEC WIZ MAG ENC
    Ringmail Coat           classes WAR CLR PAL RNG SHD BRD ROG SHM BER
    shared class -> FALSE, so the stone cannot follow the swap

The stat vector has no term for a socketed effect, so a Pareto comparison
approves the trade every time. The gate does not block the swap -- 7 AC may
still be worth it -- it states the cost, because "no loss" was the wrong part.
"""
import inspect
import re

from backend.agent import advisor

SRC = inspect.getsource(advisor)


def test_gate_exists_and_runs_on_a_different_item():
    i = SRC.index("stranded = []")
    window = SRC[max(0, i - 600):i]
    assert "rec_base != cur_base" in window, (
        "the stranding check must only run when the swap changes the item")


def test_cost_is_appended_to_why_not_silently_dropped():
    """A costly swap may still be correct -- say the cost, keep the rec."""
    i = SRC.index("stranded = []")
    window = SRC[i:i + 5200]
    assert 'COST' in window
    assert 's["why"]' in window, "the cost belongs in the why the user reads"
    assert "continue" not in window.split('s["why"]')[0][-300:], (
        "the recommendation must not be dropped, only annotated")


def test_a_native_effect_loss_is_also_costed():
    """A stone is not the only way to lose an effect.

    Shining Metallic Robes grants Spell Haste II (15% cast time) from an
    EMPTY socket. A swap to a studded tunic was described as costing only
    INT and two saves, because the stat vector cannot see an effect and the
    gate only looked at socketed stones.
    """
    i = SRC.index("stranded = []")
    window = SRC[i:i + 5200]
    assert "loses the worn item's" in window
    assert "no effect of its own" in window, (
        "say explicitly when the replacement brings nothing back")


def test_effect_loss_needs_both_lines_readable():
    """An unreadable line is not evidence that an effect is absent."""
    i = SRC.index("loses the worn item's")
    window = SRC[max(0, i - 900):i]
    assert "_cur_ln and _rec_ln" in window, (
        "only claim an effect is lost when BOTH item lines were readable")


def test_unchecked_stones_assert_nothing():
    """Same rule as everywhere else: not compared is not 'cannot move'."""
    i = SRC.index("stranded = []")
    window = SRC[i:i + 1200]
    assert "targets_checked" in window, (
        "a stone whose destinations were never computed must be skipped, not "
        "reported as stranded")


def test_named_destinations_are_quoted_back():
    i = SRC.index("stranded = []")
    window = SRC[i:i + 2200]
    assert "only legal homes are" in window, (
        "telling the player where the stone COULD go is what makes the cost "
        "actionable")


def test_prompt_forbids_the_no_loss_phrasing():
    assert "is NEVER \"no loss of other stats\"" in SRC, (
        "the model must be told explicitly not to call a stranding swap "
        "lossless -- that was the exact wording that misled")
