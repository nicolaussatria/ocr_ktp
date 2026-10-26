"""Skew measurement and levelling geometry."""

import math

import cv2
import numpy as np
import pytest

from card_ocr.imaging import deskew, find_card, skew_angle
from card_ocr.schemas import Span


def slanted_span(y: float, angle: float, width: float = 300, height: float = 30, x: float = 30) -> Span:
    drop = width * math.tan(math.radians(angle))
    return Span(
        text="TEXT LINE",
        score=0.99,
        box=[[x, y], [x + width, y + drop], [x + width, y + drop + height], [x, y + height]],
    )


def vertical_span(x: float) -> Span:
    return Span(text="SIDE", score=0.99, box=[[x, 30], [x, 330], [x + 30, 330], [x + 30, 30]])


def test_skew_angle_is_the_median_tilt_of_long_lines():
    spans = [slanted_span(index * 50, 4.0) for index in range(4)]
    assert skew_angle(spans) == pytest.approx(4.0, abs=0.01)
    assert skew_angle([slanted_span(index * 50, 6.0) for index in range(4)]) == pytest.approx(6.0, abs=0.01)


def test_skew_angle_needs_enough_votes_and_never_corrects_vertical_text():
    assert skew_angle([slanted_span(index * 50, 4.0) for index in range(2)]) == 0.0
    assert skew_angle([vertical_span(index * 50) for index in range(4)]) == 0.0


def test_skew_angle_ignores_short_tokens():
    short = [
        Span(text="AB", score=0.99, box=[[x, y], [x + 12, y + 1], [x + 12, y + 13], [x, y + 12]])
        for x, y in ((10, 10), (40, 60), (70, 110), (100, 160))
    ]
    assert skew_angle(short) == 0.0


def bar_angle(image: np.ndarray) -> float:
    """Direction of the drawn bar, in the same convention as skew_angle."""
    mask = 255 - cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    points = cv2.findNonZero((mask > 60).astype(np.uint8))
    vx, vy = (float(v) for v in cv2.fitLine(points, cv2.DIST_L2, 0, 0.01, 0.01)[:2].ravel())
    return math.degrees(math.atan2(vy, vx))


@pytest.mark.parametrize("rotation", [-8.0, 8.0])
def test_deskew_levels_a_photographed_line(rotation):
    image = np.full((220, 420, 3), 255, np.uint8)
    cv2.line(image, (60, 110), (360, 110), (0, 0, 0), 6)
    center = (210, 110)
    matrix = cv2.getRotationMatrix2D(center, rotation, 1.0)
    tilted = cv2.warpAffine(image, matrix, (420, 220), flags=cv2.INTER_CUBIC, borderValue=(255, 255, 255))
    measured = bar_angle(tilted)
    assert abs(measured) > 6.0  # the tilt is visible to the measurement
    frame, mapping = deskew(tilted, measured)
    assert abs(bar_angle(frame)) < 0.5
    # Evidence coordinates map back to the original frame through the returned matrix.
    point = np.array([210.0, 110.0, 1.0])
    assert np.allclose(np.linalg.inv(mapping) @ (mapping @ point), point)


def card_on_desk(corners, size=(1200, 900), card=(245, 245, 240), desk=(40, 70, 110)):
    """A light card, drawn as the given quadrilateral, on a darker desk, with some print."""
    width, height = size
    image = np.full((height, width, 3), desk, np.uint8)
    cv2.fillConvexPoly(image, np.int32(corners), card)
    left, top = np.min(corners, axis=0)
    for row in range(5):
        cv2.putText(image, "NAMA : CONTOH", (int(left) + 40, int(top) + 60 + 45 * row),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.9, (20, 20, 20), 2)
    return image


KTP_QUAD = [[250, 220], [950, 190], [980, 640], [230, 650]]


def test_card_on_a_desk_is_flattened_to_its_own_proportions():
    found = find_card(card_on_desk(KTP_QUAD))
    assert found is not None
    frame, matrix = found
    assert 1.4 < frame.shape[1] / frame.shape[0] < 1.8
    assert max(frame.shape[:2]) >= 1500  # magnified towards the detector's working size
    # Each photographed corner lands on the matching corner of the card area.
    mapped = cv2.perspectiveTransform(np.float32([KTP_QUAD]), matrix)[0]
    pad_x, pad_y = frame.shape[1] * 0.02 / 1.04, frame.shape[0] * 0.02 / 1.04
    expected = [[pad_x, pad_y], [frame.shape[1] - pad_x, pad_y],
                [frame.shape[1] - pad_x, frame.shape[0] - pad_y], [pad_x, frame.shape[0] - pad_y]]
    assert np.allclose(mapped, expected, atol=8)


def test_no_card_is_found_when_nothing_should_change():
    # A flat scan: the card fills the picture.
    assert find_card(np.full((900, 1400, 3), 245, np.uint8)) is None
    # The card runs off the edge of the photograph.
    assert find_card(card_on_desk([[-40, 200], [900, 180], [930, 640], [-60, 650]])) is None
    # A square object is not card-shaped.
    assert find_card(card_on_desk([[300, 150], [800, 150], [800, 650], [300, 650]])) is None
    # A small object is not the card.
    assert find_card(card_on_desk([[500, 400], [700, 400], [700, 520], [500, 520]])) is None


def test_two_cards_in_one_photo_are_not_cropped_to_one():
    # A front-and-back mockup: flattening either card would drop the other's details.
    image = card_on_desk([[60, 300], [560, 300], [560, 610], [60, 610]])
    cv2.fillConvexPoly(image, np.int32([[640, 300], [1140, 300], [1140, 610], [640, 610]]), (245, 245, 240))
    assert find_card(image) is None


def test_deskew_with_zero_angle_is_the_identity():
    image = np.full((80, 120, 3), 255, np.uint8)
    frame, mapping = deskew(image, 0.0)
    assert frame.shape == image.shape
    assert np.allclose(mapping, np.eye(3))
