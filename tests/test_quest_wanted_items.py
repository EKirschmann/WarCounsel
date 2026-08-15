"""An item page's "Related quests" is a BACKLINK list, not a shopping list.

It names a quest whether that quest takes the item, hands it out, or merely
mentions it. Read straight, the tab told a player their 78 water flasks were
the turn-in for five quests and that two more wanted a Backpack.
"""
from backend.quests import _wanted_items


def test_reward_block_items_are_not_requirements():
    """Crush the Undead lists {{:Water Flask}} under == Reward ==."""
    page = {"rewards": ["Water Flask"], "walkthrough": "kill the undead."}
    assert _wanted_items(["Water Flask"], page) == []


def test_the_reward_is_not_the_requirement_even_when_you_own_one():
    """Journeyman's Boots are the REWARD of the Journeyman's Boots Quest."""
    page = {"rewards": ["Journeyman's Boots"], "walkthrough": "a long errand."}
    assert _wanted_items(["Journeyman's Boots +2"], page) == []


def test_a_genuine_turn_in_survives():
    """Quench Lasen's Thirst: 'Bring him a Water Flask'. Reward is Coin."""
    page = {"rewards": ["Coin"],
            "walkthrough": "even when it rains, guard lasen is thirsty. "
                           "bring him a water flask and he'll give you coin."}
    assert _wanted_items(["Water Flask"], page) == ["Water Flask"]


def test_prose_rewards_are_caught_too():
    """Pages say it outside the Reward block: 'You receive a Water Flask.'"""
    page = {"rewards": [], "walkthrough": "hand over the note. "
                                          "you receive a water flask."}
    assert _wanted_items(["Water Flask"], page) == []


def test_a_page_with_prose_that_never_names_it_does_not_want_it():
    """The Backpack quests never mention a backpack anywhere."""
    page = {"rewards": ["Minor Items"],
            "walkthrough": "collect the illusion cards and return them."}
    assert _wanted_items(["Backpack"], page) == []


def test_ranks_come_off_before_matching():
    """'Ghoulbane +4' must match the 'Ghoulbane' the prose names."""
    page = {"rewards": [], "walkthrough": "you will need a ghoulbane."}
    assert _wanted_items(["Ghoulbane +4"], page) == ["Ghoulbane +4"]


def test_no_walkthrough_means_no_evidence_either_way():
    """Absence of prose is not evidence against — the item is kept."""
    page = {"rewards": [], "walkthrough": ""}
    assert _wanted_items(["Bone Chips"], page) == ["Bone Chips"]


def test_prose_pluralises_and_the_match_must_follow():
    """The Runescale Cloak Quest asks for "the three runes of scale".

    The item is a "Rune of Scale". An exact substring test dropped a real
    turn-in the player was actively farming — the false-negative mode this
    filter was shipped knowing it had.
    """
    page = {"rewards": ["Runescale Cloak"],
            "walkthrough": "you will need a lizardscale cloak from the "
                           "feerrott and the three runes of scale."}
    assert _wanted_items(["Rune of Scale"], page) == ["Rune of Scale"]


def test_plurals_do_not_rescue_a_reward():
    """Pluralising must not undo the reward test, which is the real filter."""
    page = {"rewards": ["Water Flask"], "walkthrough": "you receive water flasks."}
    assert _wanted_items(["Water Flask"], page) == []
