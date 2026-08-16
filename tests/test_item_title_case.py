"""Wiki titles are case-sensitive; the retry guard was not.

`item_line` fetches the exact title, and on a miss fuzzy-resolves and refetches
-- but the guard was `alt.lower() != base.lower()`. MediaWiki titles are
case-sensitive past the first letter, so the game's Title Case
"Skull-Shaped Barbute" and the wiki's sentence case "Skull-shaped Barbute" are
DIFFERENT pages that the guard called identical. The retry was skipped, the
item resolved to nothing, and it became STATS UNKNOWN -- silently excluded
from every slot comparison.

Reported live: a Skull-shaped Barbute +3 (AC 13, HP +35, SV MAGIC +10) was
never offered for Head against a Bronze Helm +3 it strictly beats.
"""
import inspect
import re

import backend.game_data as gd


SRC = inspect.getsource(gd.item_line)


def test_retry_guard_compares_exactly():
    assert "alt != base" in SRC, (
        "the refetch guard must compare titles EXACTLY -- a case-folded "
        "comparison skips the retry for a case-only title difference, which "
        "is the most common drift between export names and wiki titles")
    assert "alt.lower() != base.lower()" not in SRC


def test_the_reason_is_recorded():
    """The next person to 'simplify' this needs to know why."""
    assert "case-sensitive" in SRC


def test_case_only_difference_would_now_refetch():
    """Model the guard's decision directly, without touching the network."""
    def would_refetch(base, alt):
        return bool(alt and alt != base)

    # the bug: identical when case-folded, different as page titles
    assert would_refetch("Skull-Shaped Barbute", "Skull-shaped Barbute")
    # a true no-op must still be skipped -- refetching the same title is waste
    assert not would_refetch("Bronze Helm", "Bronze Helm")
    # unrelated resolutions still refetch
    assert would_refetch("Skull Shaped Barbute", "Skull-shaped Barbute")
    assert not would_refetch("Bronze Helm", None)
