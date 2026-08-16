"""The socket-type classifier keys on words that get stripped downstream.

`_exalt_socket_type` decides focus/worn/clicky/proc from the wiki Effect
line's WORDING. The exaltation block later builds a `why` string with
`^(?:Focus )?Effect:\\s*` removed -- which deletes the exact words the
classifier needs. Re-deriving the type from that string returned "unknown"
for every stone, so the "proc -- may only fire from PRIMARY" warning never
fired even though the prompt depends on it.

These tests pin the asymmetry so the shortcut is not reintroduced: the type
must be carried from where it is resolved, never recomputed from `why`.
"""
import re

from backend.agent.advisor import _exalt_socket_type


def _why_text(effect: str) -> str:
    """Reproduce how the exaltation block builds `why` from an Effect line."""
    return re.sub(r"^(?:Focus )?Effect:\s*", "", effect).strip()


def test_classifier_needs_the_prefix():
    assert _exalt_socket_type("Focus Effect: Improved Damage") == "focus"
    assert _exalt_socket_type("Combat Effect: Flametongue") == "proc"


def test_stripped_why_no_longer_classifies():
    """The regression: `why` loses the word the classifier keys on."""
    assert _exalt_socket_type(_why_text("Focus Effect: Improved Damage")) \
        == "unknown", (
        "re-deriving the socket type from `why` must stay broken-looking: if "
        "this ever passes, the stripping regex changed and the comment "
        "explaining why the type is carried forward needs revisiting")


def test_effect_extraction_already_drops_combat():
    """A proc stone loses "Combat" one step EARLIER than `why`.

    The block extracts the effect with `(?:Focus )?Effect: [^;|]+`, which
    matches the "Effect: ..." SUBSTRING of "Combat Effect: ...", so `eff` is
    already missing the qualifier before any stripping happens. This is why
    `styp` prefers the export socket NUMBER (10 = proc) and only falls back
    to the wording -- the wording cannot be trusted for procs at all.
    """
    line = "Combat Effect: Flametongue"
    eff = re.search(r"(?:Focus )?Effect: [^;|]+", line).group(0)
    assert eff == "Effect: Flametongue"
    assert _exalt_socket_type(eff) == "unknown"


def test_missing_effect_is_unknown_not_a_guess():
    assert _exalt_socket_type(None) == "unknown"
    assert _exalt_socket_type("") == "unknown"


def test_advisor_carries_the_type_instead_of_recomputing():
    """The host-note tag must not call the classifier on `why`."""
    import inspect
    from backend.agent import advisor
    src = inspect.getsource(advisor)
    assert '_exalt_socket_type(info.get("why"))' not in src, (
        "socket type must be carried from where it was resolved (export "
        "socket number or the full Effect line), not recomputed from `why`")
    assert '"type": styp' in src, "exalt_info must carry the resolved type"


def test_pet_pool_is_ranked_not_alphabetical():
    """The pet candidate pool must be capped by WORTH, and say so.

    It was `sorted(set(pool))[:40]` -- alphabetical -- which on a real
    inventory hid 20 items past "S", including the highest-DMG weapon owned
    (Verishe Mal Greataxe +2, DMG 31, against the pet's held DMG 25) and a
    proccing short sword. The panel still reported "nothing better".
    """
    import inspect
    from backend.agent import advisor
    src = inspect.getsource(advisor)
    assert 'sorted(set(pool))[:40]' not in src, (
        "pet pool must not be capped alphabetically")
    assert "_pet_worth" in src, "pet pool must be ranked by AC/DMG worth"
    i = src.index("_pet_worth")
    window = src[i:i + 2500]
    assert "logger.info" in window and "truncated" in window, (
        "a bounded pool must announce what it dropped, in the log")
    assert "capped at" in window, (
        "the prompt must say the list was capped so the model does not read "
        "it as the complete inventory")


def test_move_claims_require_a_checked_lookup():
    """An unchecked stone must not be reported as immovable.

    Stat stones and trio-unusable stones skip the target lookup entirely, so
    an empty list there is 'not compared', not 'nothing fits' -- the same
    distinction the RANGE row makes in the weapon comparison.
    """
    import inspect
    from backend.agent import advisor
    src = inspect.getsource(advisor)
    assert "targets_checked" in src
    # anchor on the CODE branch, not the prompt text that also says
    # "CANNOT be moved" when telling the model what the gear line looks like
    i_cannot = src.index("CANNOT be moved: no other owned")
    window = src[max(0, i_cannot - 400):i_cannot]
    assert "targets_checked" in window, (
        "the 'CANNOT be moved' branch must be guarded by targets_checked")
