"""Find the photographed card around its own print.

A phone photograph of a business card shows more than the card: the hand holding it, a
keyboard, a screen, other cards underneath. All of it is read, and a telephone number on
the card behind is as well formed as one on the card in front. ``imaging.find_card``
needs the whole outline on a plain surface, which a held card never offers.

The first read already says where the card is and how it is turned: its print is the
largest group of lines sharing one direction. In a view levelled on that direction the
card's four edges are straight segments along the axes, found here with OpenCV's line
segment detector. The outline is the rectangle of four such edges around the print whose
sides are best covered by edge segments and meet at its corners.

Two details carry most of the weight:

- A side counts by how its ends behave as well as by how much of it is visible. An edge
  that stops at a corner belongs to the outline. One that runs on past the corner is
  the outer edge of something larger, so the side it crosses there is printed on the
  card: the divider of a two-colour card, or the top of a footer band.
- A side partly hidden by a thumb, or faint where a white card lies on another, still
  counts: the visible part gives its line, and the neighbouring sides ending there
  confirm the corner. A side that cannot be seen at all is not guessed.

Nothing is found when fewer than three sides are visible, or when whole lines of the
same size lie beside the outline (two cards in one picture); callers then keep the
whole photograph.
"""
from collections.abc import Sequence
from dataclasses import dataclass
from math import atan, atan2, degrees

import cv2
import numpy as np

from .schemas import Span

# The working frame: long side in pixels. Edges are located to about a pixel here,
# which is two to three pixels in a 2000-pixel upload.
LOCATE_SIDE = 900
# Print direction: lines within this many degrees of each other vote together.
DIRECTION_WINDOW = 3.0
DIRECTION_MIN_VOTES = 3
DIRECTION_MAX_DEGREES = 45.0
# Segments shorter than this share of the working frame are glyph strokes and key caps.
EDGE_MIN_LENGTH = 0.025
# Perspective turns a card edge a few degrees away from the print direction.
EDGE_MAX_DEGREES = 10.0
# Segments join into one edge when they point the same way and lie on one line. A card
# held in the hand bows slightly: 4.5 px keeps the two halves of a bowed edge together.
CHAIN_MAX_DEGREES = 2.5
CHAIN_MAX_OFFSET = 4.5
CHAIN_BRIDGE = 8
# An edge candidate shows at least this share of the frame's short side, and lies at
# least EDGE_MIN_DISTANCE of it away from the middle of the print.
EDGE_MIN_COVER = 0.10
EDGE_MIN_DISTANCE = 0.03
EDGE_CANDIDATES = 12
# How close to a corner an edge has to come to count as reaching it, and how far past
# it an edge has to run to count as continuing, in working-frame pixels.
CORNER_REACH = 10
CORNER_PASS = (10, 30)
CORNER_PASS_SHARE = 0.6
# Business cards run from 1.42 (ISO 216 A8) to 1.8; perspective widens the range.
OUTLINE_ASPECT = (1.25, 2.3)
OUTLINE_MIN_SIDE = 0.15
# At least three sides must be seen, each over a quarter of its length, and the outline
# has to hold most of the print that shares the dominant direction.
OUTLINE_MIN_SIDES = 3
OUTLINE_SIDE_SHARE = 0.25
OUTLINE_MIN_SHARE = 1.8
OUTLINE_MIN_TEXT = 0.5
# Weights of the outline score: visible share of the four sides (0 to 4), side ends that
# reach a corner (0 to 8), side ends that run on past one (0 to 8), share of the print
# inside (0 to 1). Measured on 17 hand-held photographs and their rotated copies.
SCORE_REACH = 0.4
SCORE_PASS = 1.0
SCORE_TEXT = 1.0
# A card lying on a larger rectangle is preferred to it when it is closed (at most one
# side end running on) and its score is within this margin of the larger one's.
ISLAND_MAX_PASS = 1
ISLAND_MARGIN = 3.0
# Print beside the outline counts as a second card when its lines are at least this
# share of the size of the card's own and together hold this share of its print. Screen
# text behind a held card measured up to 0.21 at half the size; the back of a card
# beside its front holds as much print as the front.
RIVAL_MIN_SIZE = 0.6
RIVAL_MAX_SHARE = 0.3
# The flattened view: margin around the card, and the largest magnification.
VIEW_PADDING = 0.02
VIEW_MAX_UPSCALE = 2.0


@dataclass(frozen=True)
class CardOutline:
    """Top-left, top-right, bottom-right, bottom-left corners in image pixels."""

    corners: np.ndarray
    # Tilt of the card's print in degrees, in the convention of ``imaging.skew_angle``.
    angle: float
    # Share of the photograph the outline covers.
    area: float


def line_geometry(box: list[list[float]]) -> tuple[float, float, float] | None:
    """Direction in degrees, length and height of one detected text box."""
    points = np.asarray(box, dtype=float)
    if points.shape != (4, 2):
        return None
    top, bottom = points[1] - points[0], points[2] - points[3]
    width = (float(np.linalg.norm(top)) + float(np.linalg.norm(bottom))) / 2
    height = (float(np.linalg.norm(points[3] - points[0])) + float(np.linalg.norm(points[2] - points[1]))) / 2
    return degrees((atan2(top[1], top[0]) + atan2(bottom[1], bottom[0])) / 2), width, height


# A line is cut off by the photograph when one of its ends lies on the frame and the
# line heads into that side: the rest of it was never seen. A box whose long side runs
# along the frame is only the detector's padding touching it; the line is whole.
FRAME_CUT = 2.0
FRAME_HEADING = 0.34  # sine of 20 degrees


def runs_off(box: np.ndarray | Sequence[Sequence[float]], width: int, height: int) -> bool:
    """Whether a text box, in the pixels of a photograph, is cut off at one of its ends."""
    points = np.asarray(box, dtype=float)
    if points.shape != (4, 2):
        return False
    along = (points[1] - points[0] + points[2] - points[3]) / 2
    down = (points[3] - points[0] + points[2] - points[1]) / 2
    if np.linalg.norm(down) > np.linalg.norm(along):  # print standing on its side
        ends, along = ((points[[0, 1]], -1.0), (points[[3, 2]], 1.0)), down
    else:
        ends = ((points[[0, 3]], -1.0), (points[[1, 2]], 1.0))
    heading = along / max(float(np.linalg.norm(along)), 1e-6)
    for corners, sign in ends:
        x, y = sign * heading
        if ((x <= -FRAME_HEADING and corners[:, 0].min() <= FRAME_CUT)
                or (x >= FRAME_HEADING and corners[:, 0].max() >= width - 1 - FRAME_CUT)
                or (y <= -FRAME_HEADING and corners[:, 1].min() <= FRAME_CUT)
                or (y >= FRAME_HEADING and corners[:, 1].max() >= height - 1 - FRAME_CUT)):
            return True
    return False


# How the card lies in the photograph, from what the line classifier turned. Measured on
# 17 cards in all four orientations, over confident lines of four characters or more and
# by area: of upright print 0.00 to 0.02 was turned, of print standing on its head 0.94
# to 1.00; sideways print read downwards 0.00 to 0.01, read upwards 0.96 to 1.00.
TURN_MIN_CHARACTERS = 4
TURN_MIN_SCORE = 0.8
TURN_UPRIGHT_DEGREES = 30.0
TURN_DOMINANCE = 2.0
TURN_SHARE = (0.15, 0.35)


def quarter_turn(spans: list[Span]) -> int:
    """Clockwise turn in degrees that sets the photographed print upright: 0, 90, 180 or 270.

    0 as well when the engine does not report which lines it turned, or when the lines
    disagree: an upright photograph is never turned on a doubt.
    """
    level = sideways = level_turned = sideways_turned = 0.0
    for span in spans:
        geometry = line_geometry(span.box)
        if (span.flipped is None or geometry is None or span.score < TURN_MIN_SCORE
                or len(span.text.strip()) < TURN_MIN_CHARACTERS):
            continue
        angle, length, tall = geometry
        if length >= 1.5 * tall and abs(angle) <= TURN_UPRIGHT_DEGREES:
            level += length * tall
            level_turned += length * tall * span.flipped
        elif tall >= 1.5 * length:
            sideways += length * tall
            sideways_turned += length * tall * span.flipped
    low, high = TURN_SHARE
    if sideways > TURN_DOMINANCE * level:
        # A tall crop is laid down anticlockwise before it is read: print running down
        # the photograph then reads at once, print running up it has to be turned.
        share = sideways_turned / sideways
        return 90 if share >= high else 270 if share <= low else 0
    if level > TURN_DOMINANCE * sideways and level_turned / level >= high:
        return 180
    return 0


def _votes(spans: list[Span]) -> list[tuple[float, float, Span]]:
    """Direction and area of every line long enough to have a direction."""
    votes = []
    for span in spans:
        geometry = line_geometry(span.box)
        if geometry is None or len(span.text.strip()) < 3:
            continue
        angle, width, height = geometry
        if width >= 16 and width >= 1.5 * height and abs(angle) <= DIRECTION_MAX_DEGREES:
            votes.append((angle, width * height, span))
    return votes


def text_direction(spans: list[Span]) -> float | None:
    """Tilt shared by most of the print, by area, in degrees; None without a clear one.

    The median used for a page (``imaging.skew_angle``) follows whatever there is most
    of. On a card photographed over other cards that can be the background: one card in
    front at 1 degree and two behind at -25 gave a median of -25.
    """
    votes = _votes(spans)
    if len(votes) < DIRECTION_MIN_VOTES:
        return None
    angles = np.array([angle for angle, _, _ in votes])
    areas = np.array([area for _, area, _ in votes])
    near = np.abs(angles[:, None] - angles[None, :]) <= DIRECTION_WINDOW
    best = int(np.argmax(near @ areas))
    return float(np.average(angles[near[best]], weights=areas[near[best]]))


def _chains(segments: np.ndarray, size: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Join collinear segments into edges.

    Rows of ``segments`` are (start, offset at start, end, offset at end): positions along
    the edge and across it. Returns, per edge, its slope, its offset at position 0 and the
    running count of covered positions (so a difference of two entries is a covered length).
    """
    slopes: list[float] = []
    offsets: list[float] = []
    members: list[list[tuple[float, float, float, float]]] = []
    for start, first, end, last in segments[np.argsort(segments[:, 0] - segments[:, 2])]:
        slope = (last - first) / (end - start)
        for index, (other, offset) in enumerate(zip(slopes, offsets, strict=True)):
            if (abs(degrees(atan(slope) - atan(other))) <= CHAIN_MAX_DEGREES
                    and abs(first - (other * start + offset)) <= CHAIN_MAX_OFFSET
                    and abs(last - (other * end + offset)) <= CHAIN_MAX_OFFSET):
                members[index].append((start, first, end, last))
                rows = np.asarray(members[index])
                along = np.r_[rows[:, 0], rows[:, 2]]
                if np.ptp(along) > 1:
                    weights = np.tile(rows[:, 2] - rows[:, 0], 2)
                    slopes[index], offsets[index] = np.polyfit(along, np.r_[rows[:, 1], rows[:, 3]], 1, w=weights)
                break
        else:
            slopes.append(float(slope))
            offsets.append(float(first - slope * start))
            members.append([(start, first, end, last)])
    cover = np.zeros((len(members), size + 2), dtype=np.int32)
    for index, rows in enumerate(members):
        seen = np.zeros(size + 1, dtype=bool)
        for start, _, end, _ in rows:
            seen[max(0, round(start)) : min(size, round(end)) + 1] = True
        marks = np.flatnonzero(seen)
        for gap in np.flatnonzero((np.diff(marks) > 1) & (np.diff(marks) <= CHAIN_BRIDGE)):
            seen[marks[gap] : marks[gap + 1]] = True
        cover[index, 1:] = np.cumsum(seen)
    return np.asarray(slopes), np.asarray(offsets), cover


def _candidates(chains, seed_along: float, seed_across: float, after: bool, border: float, short: float):
    """The strongest edges on one side of the print, and the frame border as the last one.

    Returns slope, offset, covered positions, whether the edge is a seen one rather than
    the frame border, and the distance from the middle of the print.
    """
    slopes, offsets, cover = chains
    distance = (slopes * seed_along + offsets - seed_across) * (1 if after else -1)
    lengths = cover[:, -1] if len(cover) else np.zeros(0)
    usable = np.flatnonzero((distance > EDGE_MIN_DISTANCE * short) & (lengths >= EDGE_MIN_COVER * short))
    usable = usable[np.argsort(-lengths[usable], kind="stable")][:EDGE_CANDIDATES]
    blank = np.zeros((1, cover.shape[1]), dtype=np.int32)
    return (np.r_[slopes[usable], 0.0], np.r_[offsets[usable], border],
            np.vstack([cover[usable], blank]), np.r_[np.ones(len(usable), bool), False],
            np.r_[distance[usable], abs(border - seed_across)])


def _side(cover: np.ndarray, start: np.ndarray, end: np.ndarray) -> tuple[np.ndarray, ...]:
    """For every candidate side: the share of it that is visible, whether its first and
    its last end reach their corners, and how many of the two run on past one. Axis 0 of
    ``start``/``end`` is the edge."""
    index = np.arange(len(cover)).reshape((-1,) + (1,) * (np.ndim(start) - 1))
    limit = cover.shape[1] - 1

    def covered(low, high):
        low = np.clip(np.rint(low), 0, limit).astype(int)
        high = np.clip(np.rint(high), 0, limit).astype(int)
        return np.maximum(cover[index, high] - cover[index, low], 0)

    near, far = CORNER_PASS
    needed = CORNER_PASS_SHARE * (far - near)
    share = covered(start, end) / np.maximum(end - start, 1.0)
    first = covered(start - CORNER_REACH, start + CORNER_REACH) > 0
    last = covered(end - CORNER_REACH, end + CORNER_REACH) > 0
    passing = ((covered(start - far, start - near) >= needed).astype(float)
               + (covered(end + near, end + far) >= needed))
    # The two ends are measured against different corners; give both the shape of the sides.
    return share, first | np.zeros_like(last), last | np.zeros_like(first), passing


def locate_card(image: np.ndarray, spans: list[Span]) -> CardOutline | None:
    """Outline of the card that carries most of the read print, or None.

    ``spans`` are the boxes of one read of ``image``. The outline is found in a reduced,
    levelled copy and returned in the pixels of ``image``.
    """
    angle = text_direction(spans)
    if angle is None:
        return None
    height, width = image.shape[:2]
    scale = LOCATE_SIDE / max(height, width)
    matrix = cv2.getRotationMatrix2D((width / 2.0, height / 2.0), angle, scale)
    cosine, sine = abs(matrix[0, 0]) / scale, abs(matrix[0, 1]) / scale
    frame_w = int(round((height * sine + width * cosine) * scale))
    frame_h = int(round((height * cosine + width * sine) * scale))
    matrix[0, 2] += frame_w / 2.0 - width / 2.0
    matrix[1, 2] += frame_h / 2.0 - height / 2.0
    level = cv2.warpAffine(image, matrix, (frame_w, frame_h), flags=cv2.INTER_AREA,
                           borderMode=cv2.BORDER_REPLICATE)
    try:
        detector = cv2.createLineSegmentDetector(cv2.LSD_REFINE_STD)
        found = detector.detect(cv2.cvtColor(level, cv2.COLOR_BGR2GRAY))[0]
    except cv2.error:  # builds without the detector (OpenCV 4.5.1 to 4.5.3)
        return None
    if found is None:
        return None
    segments = found[:, 0, :].astype(float)
    delta = segments[:, 2:] - segments[:, :2]
    turn = np.degrees(np.arctan2(delta[:, 1], delta[:, 0])) % 180
    long_enough = np.hypot(delta[:, 0], delta[:, 1]) >= EDGE_MIN_LENGTH * LOCATE_SIDE
    across = segments[long_enough & ((turn <= EDGE_MAX_DEGREES) | (turn >= 180 - EDGE_MAX_DEGREES))]
    down = segments[long_enough & (np.abs(turn - 90) <= EDGE_MAX_DEGREES)]
    # Horizontal edges run along x and are offset in y; vertical ones the other way round.
    across = np.where((across[:, 0] <= across[:, 2])[:, None], across, across[:, [2, 3, 0, 1]])
    down = np.where((down[:, 1] <= down[:, 3])[:, None], down[:, [1, 0, 3, 2]], down[:, [3, 2, 1, 0]])
    rows, columns = _chains(across, frame_w), _chains(down, frame_h)

    # The print that shares the dominant direction, in the working frame.
    centres, areas, sizes = [], [], []
    for vote_angle, area, span in _votes(spans):
        box = np.asarray(span.box, dtype=float)
        geometry = line_geometry(span.box)  # never None: _votes keeps only measurable boxes
        if (geometry is not None and abs(vote_angle - angle) <= DIRECTION_WINDOW + 2 and span.score >= 0.8
                and not runs_off(span.box, width, height)):
            centres.append(matrix @ np.r_[box.mean(axis=0), 1.0])
            areas.append(area)
            sizes.append(geometry[2])
    if len(centres) < 2:
        return None
    centres, areas, sizes = np.asarray(centres), np.asarray(areas), np.asarray(sizes)
    seed = np.array([_weighted_median(centres[:, 0], areas), _weighted_median(centres[:, 1], areas)])

    short = min(frame_w, frame_h)
    top = _candidates(rows, seed[0], seed[1], False, 0.0, short)
    bottom = _candidates(rows, seed[0], seed[1], True, frame_h - 1.0, short)
    left = _candidates(columns, seed[1], seed[0], False, 0.0, short)
    right = _candidates(columns, seed[1], seed[0], True, frame_w - 1.0, short)

    def corner(row, column):
        """Crossing points of every row edge with every column edge: (rows, columns)."""
        x = (column[0][None, :] * row[1][:, None] + column[1][None, :]) / (1 - column[0][None, :] * row[0][:, None])
        return x, row[0][:, None] * x + row[1][:, None]

    tl_x, tl_y = corner(top, left)
    tr_x, tr_y = corner(top, right)
    bl_x, bl_y = corner(bottom, left)
    br_x, br_y = corner(bottom, right)
    # Every combination of a top, bottom, left and right edge, as axes 0 to 3.
    sides = [
        [value[:, None, :, :] for value in _side(top[2], tl_x[:, :, None], tr_x[:, None, :])],
        [value[None, :, :, :] for value in _side(bottom[2], bl_x[:, :, None], br_x[:, None, :])],
        [value.transpose(1, 2, 0)[:, :, :, None]
         for value in _side(left[2], tl_y.T[:, :, None], bl_y.T[:, None, :])],
        [value.transpose(1, 2, 0)[:, :, None, :]
         for value in _side(right[2], tr_y.T[:, :, None], br_y.T[:, None, :])],
    ]
    above, below, before, after = sides
    every = (len(top[0]), len(bottom[0]), len(left[0]), len(right[0]))
    share = sum(np.broadcast_to(side[0], every) for side in sides)
    reach = sum(side[1].astype(float) + side[2] for side in sides)
    passing = sum(side[3] for side in sides)
    seen = sum((side[0] >= OUTLINE_SIDE_SHARE).astype(int) for side in sides)
    # The frame stands in for a side only where the card leaves the photograph: both
    # neighbouring sides have to run out to it.
    leaves = ((top[3][:, None, None, None] | (before[1] & after[1]))
              & (bottom[3][None, :, None, None] | (before[2] & after[2]))
              & (left[3][None, None, :, None] | (above[1] & below[1]))
              & (right[3][None, None, None, :] | (above[2] & below[2])))
    inside = np.einsum(
        "in,jn,kn,ln,n->ijkl",
        (centres[None, :, 1] > top[0][:, None] * centres[None, :, 0] + top[1][:, None]).astype(float),
        (centres[None, :, 1] < bottom[0][:, None] * centres[None, :, 0] + bottom[1][:, None]).astype(float),
        (centres[None, :, 0] > left[0][:, None] * centres[None, :, 1] + left[1][:, None]).astype(float),
        (centres[None, :, 0] < right[0][:, None] * centres[None, :, 1] + right[1][:, None]).astype(float),
        areas,
    ) / areas.sum()
    widths = ((tr_x[:, None, :] - tl_x[:, :, None])[:, None] + (br_x[:, None, :] - bl_x[:, :, None])[None]) / 2
    heights = ((bl_y[None, :, :] - tl_y[:, None, :])[:, :, :, None]
               + (br_y[None, :, :] - tr_y[:, None, :])[:, :, None, :]) / 2
    with np.errstate(divide="ignore", invalid="ignore"):
        aspect = np.maximum(widths, heights) / np.minimum(widths, heights)
    real = (top[3][:, None, None, None].astype(int) + bottom[3][None, :, None, None]
            + left[3][None, None, :, None] + right[3][None, None, None, :])
    valid = (
        (np.minimum(widths, heights) >= OUTLINE_MIN_SIDE * short)
        & (real >= OUTLINE_MIN_SIDES)
        & leaves
        & (seen >= OUTLINE_MIN_SIDES)
        & (share >= OUTLINE_MIN_SHARE)
        & (inside >= OUTLINE_MIN_TEXT)
        & (aspect <= OUTLINE_ASPECT[1])
        # A card cut off by the frame shows less than its own proportions.
        & ((aspect >= OUTLINE_ASPECT[0]) | (real < 4))
    )
    if not valid.any():
        return None
    score = np.where(valid, share + SCORE_REACH * reach - SCORE_PASS * passing + SCORE_TEXT * inside, -np.inf)
    i, j, k, m = np.unravel_index(int(np.argmax(score)), score.shape)
    # The best-supported rectangle around the print can be what the card lies on: a
    # laptop, a tray, a sheet of paper. A card lying on it is an island, a closed
    # rectangle nearer to the print on all four sides. A printed panel is not one: it
    # shares its other sides with the card.
    while True:
        island = (valid & (passing <= ISLAND_MAX_PASS) & (score >= score[i, j, k, m] - ISLAND_MARGIN)
                  & (top[4][:, None, None, None] < top[4][i]) & (bottom[4][None, :, None, None] < bottom[4][j])
                  & (left[4][None, None, :, None] < left[4][k]) & (right[4][None, None, None, :] < right[4][m]))
        if not island.any():
            break
        i, j, k, m = np.unravel_index(int(np.argmax(np.where(island, score, -np.inf))), score.shape)
    # Whole lines of the same size and direction beside the outline are a second card: the
    # other side in a front-and-back picture, or two cards laid out together. Cropping to
    # one would drop the other, so such a photograph is left as it is.
    on_it = ((centres[:, 1] > top[0][i] * centres[:, 0] + top[1][i])
             & (centres[:, 1] < bottom[0][j] * centres[:, 0] + bottom[1][j])
             & (centres[:, 0] > left[0][k] * centres[:, 1] + left[1][k])
             & (centres[:, 0] < right[0][m] * centres[:, 1] + right[1][m]))
    beside = ~on_it & (sizes >= RIVAL_MIN_SIZE * np.median(sizes[on_it]))
    if areas[beside].sum() >= RIVAL_MAX_SHARE * areas[on_it].sum():
        return None
    corners = np.array([[tl_x[i, k], tl_y[i, k]], [tr_x[i, m], tr_y[i, m]],
                        [br_x[j, m], br_y[j, m]], [bl_x[j, k], bl_y[j, k]]])
    back = cv2.invertAffineTransform(matrix)
    corners = np.c_[corners, np.ones(4)] @ back.T
    return CardOutline(corners=corners, angle=angle,
                       area=float(cv2.contourArea(corners.astype(np.float32)) / (width * height)))


def _weighted_median(values: np.ndarray, weights: np.ndarray) -> float:
    order = np.argsort(values)
    running = np.cumsum(weights[order])
    return float(values[order][np.searchsorted(running, running[-1] / 2)])


def card_view(source: np.ndarray, corners: np.ndarray, max_side: int) -> tuple[np.ndarray, np.ndarray]:
    """Flattened front view of the outlined card, and the matrix mapping ``source`` onto it.

    The view is as large as ``max_side`` allows without magnifying more than
    VIEW_MAX_UPSCALE, so a card that fills a third of a 12-megapixel photograph is read
    at its full recorded detail rather than at the reduced size of the first read.
    """
    corners = np.asarray(corners, dtype=np.float32)
    across = max(float(np.linalg.norm(corners[1] - corners[0])), float(np.linalg.norm(corners[2] - corners[3])))
    down = max(float(np.linalg.norm(corners[3] - corners[0])), float(np.linalg.norm(corners[2] - corners[1])))
    zoom = min(VIEW_MAX_UPSCALE, max_side / (max(across, down) * (1 + 2 * VIEW_PADDING)))
    card_w, card_h = across * zoom, down * zoom
    pad_x, pad_y = VIEW_PADDING * card_w, VIEW_PADDING * card_h
    target = np.array([[pad_x, pad_y], [pad_x + card_w, pad_y],
                       [pad_x + card_w, pad_y + card_h], [pad_x, pad_y + card_h]], dtype=np.float32)
    size = (round(card_w + 2 * pad_x), round(card_h + 2 * pad_y))
    # Reducing by more than a third through the warp alone would alias fine print: the
    # part of the photograph that holds the card is reduced by area averaging first.
    reduce = zoom if zoom < 0.75 else 1.0
    shift = np.eye(3)
    if reduce < 1.0:
        height, width = source.shape[:2]
        margin = 0.1 * max(across, down)
        x0, y0 = np.maximum(np.floor(corners.min(axis=0) - margin), 0).astype(int)
        x1, y1 = np.minimum(np.ceil(corners.max(axis=0) + margin), [width, height]).astype(int)
        source = cv2.resize(source[y0:y1, x0:x1], None, fx=reduce, fy=reduce, interpolation=cv2.INTER_AREA)
        shift = np.array([[reduce, 0, -x0 * reduce], [0, reduce, -y0 * reduce], [0, 0, 1.0]])
        corners = (np.c_[corners, np.ones(4)] @ shift.T)[:, :2].astype(np.float32)
    matrix = cv2.getPerspectiveTransform(corners, target)
    frame = cv2.warpPerspective(source, matrix, size, flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)
    return frame, matrix.astype(float) @ shift


def on_card(box: np.ndarray | Sequence[Sequence[float]], corners: np.ndarray) -> bool:
    """Whether the middle of a text box, given in the outline's pixels, lies on the card."""
    x, y = np.asarray(box, dtype=float).mean(axis=0)
    return cv2.pointPolygonTest(np.asarray(corners, dtype=np.float32), (float(x), float(y)), False) >= 0
