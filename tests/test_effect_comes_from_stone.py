"""An item's Effect line describes its STONE, not the item as worn.

Confirmed in game 2026-08-15: a Gossamer Robe's "Focus Effect: Summoning
Efficiency I" is not organic to the robe -- it is what the robe's own
exaltation grants. Socket a different stone and the robe grants that instead.

On one real character this made the wiki line wrong in BOTH directions:

    Gossamer Robe +4        wiki: Summoning Efficiency I  real: Minor Improved Damage I
    The Baron's Blade +5    wiki: (none)                  real: Burn proc + a clicky
    Signet Ring of the...   wiki: (none)                  real: Extended Enhancement II

So an Effect line may never be credited to an item on its own strength. These
tests pin the corrections the advisor writes onto the gear lines, because the
model reasons from those lines and cannot infer this rule.
"""
import inspect
import re

from backend.agent import advisor


SRC = inspect.getsource(advisor)


def test_rank_gates_socket_exposure():
    """A focus socket is exposed by LEVELLING the item.

    Measured on one character's worn gear: all 20 items at +1 or more had a
    focus socket, and none of the 3 at +0 did -- 23/23, no counter-examples.
    So a +0 item's focus cannot be extracted, and replacing that item loses
    the effect permanently unless the item is merged first.
    """
    assert "at +0 has no focus socket" in SRC, (
        "the prompt must state that levelling exposes the socket")
    assert "merge the item first" in SRC, (
        "say what WOULD preserve the effect, not just that it is lost")


def test_prompt_states_the_native_and_override_model():
    """The prompt must describe how an effect is actually obtained.

    It previously stated the opposite -- that effects are never organic and
    come only from a socketed stone -- which would have had the model treat
    an unsocketed robe granting Spell Haste II as granting nothing.
    """
    assert "effects are NOT organic to the item" not in SRC, (
        "that model is wrong: an item's Effect line applies on its own")
    assert "OVERRIDES the item's own effect" in SRC, (
        "the prompt must say a stone overrides the native effect")
    assert "a swap away from an item with an effect is never free" in SRC, (
        "the prompt must tie the model to the decision it affects")


def test_gear_line_carries_what_the_stone_actually_grants():
    """HOSTS EXALTATION must name the effect, not only the stone."""
    assert "granting" in SRC
    i = SRC.index("HOSTS EXALTATION: ")
    window = SRC[max(0, i - 3000):i + 500]
    assert "grants" in window or "granting" in window


def test_contradicted_effect_line_is_corrected():
    """A transplanted stone must annul the host's own Effect claim."""
    assert "is the effect of its OWN stone, which is NOT" in SRC, (
        "when the socket contradicts the item's Effect line, the line must be "
        "marked as not applying")


def test_an_unsocketed_item_keeps_its_native_effect():
    """CORRECTION to an earlier reading of this system.

    An item's Effect line is its NATIVE effect and applies on its own; a
    socketed focus stone OVERRIDES it. Evidence, from one character:

        Gossamer Robe          native Summoning Efficiency I
                               + Smoldering stone -> reports Minor Improved
                               Damage I                      (override)
        Shining Metallic Robes native Spell Haste II
                               + EMPTY socket -> reports Spell Haste II
                                                             (native applies)

    A previous version of this file asserted the opposite and the code
    annotated every unsocketed item as granting nothing -- which would have
    told the model that a robe the player wears for 15% cast time does
    nothing at all.
    """
    assert "NO STONE SOCKETED" not in SRC, (
        "an item with no stone keeps its NATIVE effect; annotating it as "
        "granting nothing is wrong")
    assert "socketed focus stone OVERRIDES it" in SRC, (
        "the native-vs-override model must be recorded where the next "
        "reader will find it")


def test_exalt_info_keeps_the_raw_effect():
    assert '"effect": eff_txt' in SRC, (
        "the granted effect must be carried, not re-derived from `why` -- the "
        "same mistake that broke the socket-type classifier")


def test_correction_only_fires_on_a_real_mismatch():
    """Guard against annotating an item whose own stone IS socketed.

    Black Tome with Silver Runes wears its own stone; its Effect line is
    correct and must not be contradicted.
    """
    i = SRC.index("is the effect of its OWN stone, which is NOT")
    window = SRC[max(0, i - 800):i]
    assert "claimed_eff" in window and "not in granted.lower()" in window, (
        "the correction must be conditional on the socketed stone NOT "
        "matching the item's own Effect line")
