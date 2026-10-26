"""Finding a photographed card around its own print, on drawn scenes."""

import cv2
import numpy as np
import pytest
from conftest import drawn_photo as scene
from conftest import tilted_line

from card_ocr.imaging import skew_angle
from card_ocr.locate import card_view, locate_card, on_card, quarter_turn, runs_off, text_direction
from card_ocr.schemas import Span

PAPER = (240, 242, 244)
SKIN = (120, 150, 190)
CARD = [[200, 300], [1000, 280], [1010, 760], [190, 770]]


def line(x, y, width=300, height=34, angle=-1.4, **fields):
    """A line of the drawn card, which is turned by -1.4 degrees."""
    return tilted_line(x, y, width, height, angle, **fields)


def card_lines(left=260, top=340):
    return [line(left, top + 70 * row, width=260 + 60 * (row % 3)) for row in range(6)]


def close(outline, corners, tolerance=10):
    return outline is not None and np.allclose(outline.corners, corners, atol=tolerance)


def test_print_direction_follows_the_card_in_front_not_the_most_lines():
    front = [line(300, 300 + 80 * row, width=500, height=50, angle=1.0) for row in range(3)]
    behind = [line(40, 40 + 30 * row, width=220, height=22, angle=-25.0) for row in range(6)]
    assert text_direction(front + behind) == pytest.approx(1.0, abs=0.1)
    # The page median follows whatever there is most of.
    assert skew_angle(front + behind) == pytest.approx(-25.0, abs=0.1)
    assert text_direction(front[:2]) is None


def test_a_held_card_among_other_things_is_outlined():
    other = [[20, 60], [520, 250], [450, 430], [-50, 240]]
    thumb = cv2.ellipse2Poly((1010, 640), (120, 80), 20, 0, 360, 8)
    image = scene((other, PAPER), (CARD, PAPER), (thumb, SKIN))
    behind = [line(60, 120 + 34 * row, width=200, height=24, angle=21.0, text="OTHER CARD") for row in range(4)]
    outline = locate_card(image, card_lines() + behind)
    assert close(outline, CARD)
    assert outline.angle == pytest.approx(-1.4, abs=0.2)
    assert 0.3 < outline.area < 0.4
    # The print of the card behind is not on the card.
    assert all(on_card(span.box, outline.corners) for span in card_lines())
    assert not any(on_card(span.box, outline.corners) for span in behind)


def test_a_printed_divider_does_not_cut_the_card_in_two():
    half = [[600, 290], [1000, 280], [1010, 760], [600, 765]]
    image = scene((CARD, PAPER), (half, (150, 60, 70)))
    spans = [line(240, 520, width=300, text="PT CONTOH MAKMUR")] + card_lines(left=640)
    assert close(locate_card(image, spans), CARD)


def test_a_footer_band_belongs_to_the_card():
    band = [[192, 700], [1009, 690], [1010, 760], [190, 770]]
    image = scene((CARD, PAPER), (band, (60, 160, 90)))
    spans = card_lines(top=330)[:5] + [line(420, 712, width=400, height=30, text="www.contoh.co.id")]
    assert close(locate_card(image, spans), CARD)


def test_a_card_lying_on_a_larger_rectangle_is_the_one_outlined():
    laptop = [[60, 120], [1140, 120], [1140, 850], [60, 850]]
    image = scene((laptop, (170, 172, 176)), (CARD, PAPER))
    assert close(locate_card(image, card_lines()), CARD)


def test_two_cards_in_one_picture_are_left_alone():
    left = [[60, 300], [560, 300], [560, 600], [60, 600]]
    right = [[640, 300], [1140, 300], [1140, 600], [640, 600]]
    image = scene((left, PAPER), (right, PAPER))
    spans = ([line(100, 340 + 50 * row, width=300, height=30, angle=0.0) for row in range(4)]
             + [line(680, 340 + 50 * row, width=300, height=30, angle=0.0) for row in range(4)])
    assert locate_card(image, spans) is None
    # One card alone in the same picture is found.
    assert close(locate_card(scene((left, PAPER)), spans[:4]), left)


def test_nothing_is_outlined_without_edges_or_without_print():
    flat = np.full((900, 1200, 3), 245, np.uint8)
    assert locate_card(flat, card_lines()) is None
    assert locate_card(scene((CARD, PAPER)), card_lines()[:1]) is None
    # A square object is not card-shaped.
    square = [[350, 200], [850, 200], [850, 700], [350, 700]]
    assert locate_card(scene((square, PAPER)), card_lines(left=400, top=260)) is None


def test_the_card_view_keeps_the_detail_of_the_full_size_upload():
    source = cv2.resize(scene((CARD, PAPER)), None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC)
    corners = np.float32(CARD) * 3
    frame, matrix = card_view(source, corners, 2000)
    assert max(frame.shape[:2]) == 2000
    assert 1.5 < frame.shape[1] / frame.shape[0] < 1.8
    mapped = cv2.perspectiveTransform(corners[None], matrix)[0]
    pad_x, pad_y = frame.shape[1] * 0.02 / 1.04, frame.shape[0] * 0.02 / 1.04
    expected = [[pad_x, pad_y], [frame.shape[1] - pad_x, pad_y],
                [frame.shape[1] - pad_x, frame.shape[0] - pad_y], [pad_x, frame.shape[0] - pad_y]]
    assert np.allclose(mapped, expected, atol=3)
    # The card itself is paper from edge to edge of that rectangle.
    assert frame[frame.shape[0] // 2, frame.shape[1] // 2].min() > 220
    # A small upload is magnified at most twice.
    small, _ = card_view(scene((CARD, PAPER)), np.float32(CARD) / 1, 5000)
    assert max(small.shape[:2]) < 2 * 830 * 1.05


def test_a_line_is_cut_off_only_where_its_end_meets_the_frame():
    assert runs_off(line(0, 400, angle=0.0).box, 1200, 900)  # starts at the left edge
    assert runs_off(line(900, 400, angle=0.0).box, 1200, 900)  # ends at the right edge
    assert runs_off(line(900, 200, width=450, angle=-26.0).box, 1200, 900)  # heads into the top
    assert not runs_off(line(300, 400, angle=0.0).box, 1200, 900)
    # The detector's padding touching the frame along the line is not a cut.
    assert not runs_off(line(300, 866, angle=0.0).box, 1200, 900)
    assert not runs_off(line(300, 0, angle=0.0).box, 1200, 900)
    # Print standing on its side: its ends are at the top and the bottom.
    upright = [[400, 0], [434, 0], [434, 300], [400, 300]]
    assert runs_off(upright, 1200, 900)
    assert not runs_off([[0, 200], [34, 200], [34, 500], [0, 500]], 1200, 900)


def standing(x, flipped, text="PRINTED LINE"):
    return Span(text=text, score=0.99, flipped=flipped, box=[[x, 100], [x + 34, 100], [x + 34, 500], [x, 500]])


def test_the_turned_lines_say_how_the_card_lies():
    level = [line(100, 100 + 60 * row, angle=0.0, flipped=False) for row in range(5)]
    assert quarter_turn(level) == 0
    assert quarter_turn([span.model_copy(update={"flipped": True}) for span in level]) == 180
    # Print running down the photograph reads once laid down; print running up it is turned.
    assert quarter_turn([standing(100 + 60 * row, False) for row in range(5)]) == 270
    assert quarter_turn([standing(100 + 60 * row, True) for row in range(5)]) == 90


def test_an_upright_photograph_is_never_turned_on_a_doubt():
    level = [line(100, 100 + 60 * row, angle=0.0, flipped=row == 0) for row in range(5)]
    assert quarter_turn(level) == 0  # one line in five
    # An engine that does not report what it turned, short tokens and unsure lines say nothing.
    assert quarter_turn([line(100, 100 + 60 * row, angle=0.0) for row in range(5)]) == 0
    assert quarter_turn([line(100, 100, angle=0.0, flipped=True, text="F12")]) == 0
    assert quarter_turn([line(100, 100, angle=0.0, flipped=True, score=0.5)]) == 0
    # As much level print as standing print: no clear orientation.
    mixed = [line(100, 600, width=400, angle=0.0, flipped=False), standing(100, True)]
    assert quarter_turn(mixed) == 0
