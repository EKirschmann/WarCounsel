"""A coordinate can arrive SPLIT across OCR boxes.

RapidOCR returns one box per detected text run and `_capture_and_ocr` joins
them with newlines, so a four-digit reading can land as "X: 1" + "540".
`(-?\\d+)` then captured just the 1 -- reported live as an X of 1540 reading
as 1 "every so often".

The parse now lets a number continue over whitespace in 1-3 digit groups,
bounded by a plausible coordinate magnitude. These tests pin both halves:
splits must rejoin, and separate coordinates must NOT be glued together.
"""
import pytest

from backend.ocr_system import parse_loc_text, _coord


def test_normal_reading():
    r = parse_loc_text("X: 1540\nY: -220\nZ: 4")
    assert (r["x"], r["y"], r["z"]) == (1540, -220, 4)


def test_split_across_boxes_rejoins():
    """The reported bug."""
    r = parse_loc_text("X: 1\n540\nY: -220\nZ: 4")
    assert r["x"] == 1540, "a split coordinate must rejoin, not truncate"


def test_split_on_one_line_rejoins():
    assert parse_loc_text("X: 1 540 Y: -220 Z: 4")["x"] == 1540


def test_thousands_separator():
    assert parse_loc_text("X: 1,540\nY: -220\nZ: 4")["x"] == 1540


def test_negatives_survive():
    r = parse_loc_text("X: -1540\nY: 220\nZ: -4")
    assert (r["x"], r["y"], r["z"]) == (-1540, 220, -4)


def test_separate_coordinates_do_not_merge():
    """The risk the fix has to avoid: 15 and 40 must not become 1540."""
    r = parse_loc_text("X: 15\nY: 40\nZ: 4")
    assert (r["x"], r["y"], r["z"]) == (15, 40, 4)


def test_letter_digit_confusion_still_repaired():
    r = parse_loc_text("X: 1O2\nY: 2S\nZ: 4")
    assert (r["x"], r["y"]) == (102, 25)


def test_zone_text_still_extracted():
    assert parse_loc_text("X: 1540 Y: -220 Z: 4 Befallen")["zone_text"] == "Befallen"


def test_no_coordinates_returns_none():
    assert parse_loc_text("nothing here") is None


@pytest.mark.parametrize("raw,expect", [
    ("1540", 1540.0),
    ("1 540", 1540.0),
    ("-1 540", -1540.0),
    ("1,540", 1540.0),
    ("", None),
    ("-", None),
])
def test_coord_helper(raw, expect):
    assert _coord(raw) == expect


def test_implausible_join_falls_back_to_the_first_fragment():
    """A merge that produces a nonsense magnitude is worse than a short read.

    EQ zones run to roughly +/-5000, so 15 400 000 is a bad join. Keeping the
    first fragment loses precision but stays in the right part of the map.
    """
    assert _coord("15 400 000") == 15.0
