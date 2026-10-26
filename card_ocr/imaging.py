import re
import warnings
from io import BytesIO
from math import atan2, degrees

import cv2
import numpy as np
from PIL import Image, ImageOps, UnidentifiedImageError

from .config import Settings
from .errors import OCRProblem
from .schemas import Quality, Span


def decode_image(payload: bytes, settings: Settings) -> tuple[np.ndarray, Quality]:
    image, quality, _ = decode_source(payload, settings)
    return image, quality


def decode_source(payload: bytes, settings: Settings) -> tuple[np.ndarray, Quality, np.ndarray]:
    """The image every pass reads, its quality figures, and the upload at full size.

    A phone photograph holds two to three times the detail the bounded working image
    keeps. The full-size pixels are used only to cut out a located card; when the upload
    already fits, the same array is returned twice.
    """
    if not payload:
        raise OCRProblem("EMPTY_FILE", "Upload a JPEG, PNG, or WebP image.")
    if len(payload) > settings.max_file_bytes:
        raise OCRProblem("FILE_TOO_LARGE", "Image exceeds the configured upload limit.", 413)
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(payload)) as source:
                if source.format not in {"JPEG", "PNG", "WEBP"}:
                    raise OCRProblem("UNSUPPORTED_IMAGE", "Only JPEG, PNG, and WebP are supported.", 415)
                if getattr(source, "n_frames", 1) != 1:
                    raise OCRProblem("ANIMATED_IMAGE", "Upload one still image.", 415)
                if source.width * source.height > settings.max_pixels:
                    raise OCRProblem("IMAGE_TOO_LARGE", "Image exceeds the configured pixel limit.", 413)
                if min(source.size) < settings.min_side:
                    raise OCRProblem("IMAGE_TOO_SMALL", "Retake a closer, higher-resolution photograph.")
                source = ImageOps.exif_transpose(source)
                # Flatten transparency onto white, never onto a black background.
                rgba = source.convert("RGBA")
                rgb = Image.new("RGB", rgba.size, "white")
                rgb.paste(rgba, mask=rgba.getchannel("A"))
                full = cv2.cvtColor(np.asarray(rgb), cv2.COLOR_RGB2BGR)
                if max(rgb.size) > settings.max_side:
                    rgb.thumbnail((settings.max_side, settings.max_side), Image.Resampling.LANCZOS)
                    image = cv2.cvtColor(np.asarray(rgb), cv2.COLOR_RGB2BGR)
                else:
                    image = full
    except OCRProblem:
        raise
    except (
        UnidentifiedImageError,
        OSError,
        ValueError,
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
    ) as exc:
        raise OCRProblem("INVALID_IMAGE", "The file could not be decoded safely.", 415) from exc

    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    # Consistent measuring scale; these are heuristics, not learned quality scores.
    scale = min(1.0, 1000 / max(gray.shape))
    sample = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    sharpness = float(cv2.Laplacian(sample, cv2.CV_64F).var())
    contrast = float(sample.std())
    issues = []
    if sharpness < 45:
        issues.append("possible_blur")
    if contrast < 20:
        issues.append("low_contrast")
    if max(image.shape[:2]) < 1000:
        issues.append("low_resolution")
    return image, Quality(
        width=image.shape[1],
        height=image.shape[0],
        sharpness=round(sharpness, 2),
        contrast=round(contrast, 2),
        warnings=issues,
    ), full


# Word respacing. This recogniser often returns a printed line with the word breaks
# missing ("BEKASITIMURREGENSIBLOK"), and occasionally invents one ("SITI N URHALIZA").
# The real breaks are visible in the image as blank pixel columns, so they are recovered
# from the picture rather than guessed from a dictionary.
#
# Measured on crops of Arial and Courier card lines (gap width / crop height): letter
# gaps run up to 0.20 — widest between two upright strokes such as N|U or N|I — and word
# gaps start at 0.26. A fixed cut at 0.18 therefore split "NURHALIZA" and "ANGGRAINI".
# A gap now counts as a word break only when it is wider than RESPACE_GAP_RATIO and
# clearly wider (RESPACE_GAP_JUMP) than every letter gap of the same line. A line whose
# letters leave no gaps at all (bold or blurred print) needs RESPACE_LONE_GAP_RATIO.
RESPACE_GAP_RATIO = 0.22
RESPACE_GAP_JUMP = 1.4
RESPACE_LONE_GAP_RATIO = 0.25
RESPACE_SCALE = 4
RESPACE_MIN_TOKEN = 8


def _word_gap(widths: list[int], height: int) -> int | None:
    """Narrowest blank run that separates words on this line, or None.

    The first clear jump is the one from letter gaps to word gaps; a later one would be
    the jump from word gaps to a column gap.
    """
    widths = sorted(widths)
    for narrower, wider in zip(widths, widths[1:], strict=False):
        if wider >= RESPACE_GAP_RATIO * height and wider >= RESPACE_GAP_JUMP * max(narrower, 1):
            return wider
    if widths and widths[0] >= RESPACE_LONE_GAP_RATIO * height:
        return widths[0]
    return None


def respace_candidate(text: str) -> bool:
    """A line worth re-reading word by word: a long run of letters, or a full stop
    glued to the next word ("NO.45", "JL.MERDEKA"). Digits may appear elsewhere in the
    line — the respacer never separates two digits — but a number alone never qualifies."""
    letters = max((len(run) for run in re.findall(r"[^\W\d_]+", text)), default=0)
    return letters >= RESPACE_MIN_TOKEN or bool(re.search(r"[^\W\d_]\.[^\W_]", text))


def crop_span(image: np.ndarray, box: list[list[float]]) -> np.ndarray | None:
    """Deskewed crop of one detected text box."""
    source = np.array(box, dtype="float32")
    if source.shape != (4, 2):
        return None
    width = int(max(np.linalg.norm(source[0] - source[1]), np.linalg.norm(source[3] - source[2])))
    height = int(max(np.linalg.norm(source[0] - source[3]), np.linalg.norm(source[1] - source[2])))
    if width < 8 or height < 8:
        return None
    target = np.array([[0, 0], [width, 0], [width, height], [0, height]], dtype="float32")
    return cv2.warpPerspective(image, cv2.getPerspectiveTransform(source, target), (width, height))


def word_pieces(patch: np.ndarray) -> list[np.ndarray] | None:
    """Split one line crop at its blank pixel columns. None when there is no word break."""
    scaled = cv2.resize(patch, None, fx=RESPACE_SCALE, fy=RESPACE_SCALE, interpolation=cv2.INTER_CUBIC)
    gray = cv2.GaussianBlur(cv2.cvtColor(scaled, cv2.COLOR_BGR2GRAY), (5, 5), 0)
    _, ink = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    columns = (ink > 0).sum(axis=0)
    height = scaled.shape[0]
    blank = columns <= max(1, int(0.03 * height))
    runs: list[tuple[int, int]] = []
    start: int | None = None
    for index, empty in enumerate(blank):
        if empty and start is None:
            start = index
        if not empty and start is not None:
            runs.append((start, index))
            start = None
    if start is not None:
        runs.append((start, len(blank)))
    inner = [(left, right) for left, right in runs if left > 3 and right < len(blank) - 3]
    cut = _word_gap([right - left for left, right in inner], height)
    breaks = [(left, right) for left, right in inner if cut is not None and right - left >= cut]
    if not breaks:
        return None
    pieces = []
    previous = 0
    for left, right in breaks:
        pieces.append(scaled[:, previous:left])
        previous = right
    pieces.append(scaled[:, previous:])
    kept = [piece for piece in pieces if piece.shape[1] >= 0.15 * height]
    return kept if len(kept) > 1 else None


def enhance(image: np.ndarray) -> np.ndarray:
    lab = cv2.cvtColor(image, cv2.COLOR_BGR2LAB)
    light, a, b = cv2.split(lab)
    light = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(light)
    return cv2.cvtColor(cv2.merge((light, a, b)), cv2.COLOR_LAB2BGR)


def rotate(image: np.ndarray, clockwise: int) -> np.ndarray:
    return np.ascontiguousarray(np.rot90(image, -(clockwise // 90)))


def rotation_matrix(width: int, height: int, clockwise: int) -> np.ndarray:
    return np.asarray({
        0: [[1, 0, 0], [0, 1, 0], [0, 0, 1]],
        90: [[0, -1, height - 1], [1, 0, 0], [0, 0, 1]],
        180: [[-1, 0, width - 1], [0, -1, height - 1], [0, 0, 1]],
        270: [[0, 1, 0], [-1, 0, width - 1], [0, 0, 1]],
    }[clockwise % 360], dtype=float)


# A handheld photograph is rarely level. This recogniser returns a rotated quad per text
# line, so the median top-edge angle measures the page tilt. Only lines clearly wider
# than tall vote; a short token has an imprecise angle, and a scan rotated by a quarter
# turn is not a tilt to correct. A correction below SKEW_MIN_CORRECTION is not worth a
# whole extra read.
SKEW_MAX_DEGREES = 30.0
SKEW_MIN_VOTES = 3
SKEW_MIN_CORRECTION = 1.2


def skew_angle(spans: list[Span]) -> float:
    """Median tilt of the detected text lines in degrees; 0.0 when there is no clear tilt."""
    angles = []
    for span in spans:
        box = np.asarray(span.box, dtype=float)
        if box.shape != (4, 2):
            continue
        top = box[1] - box[0]
        bottom = box[2] - box[3]
        width = float(np.linalg.norm(top))
        if width < 16 or width < 1.5 * float(np.linalg.norm(box[3] - box[0])):
            continue
        angle = degrees(float(atan2(top[1], top[0]) + atan2(bottom[1], bottom[0])) / 2)
        if abs(angle) <= SKEW_MAX_DEGREES:
            angles.append(angle)
    return float(np.median(angles)) if len(angles) >= SKEW_MIN_VOTES else 0.0


def deskew(image: np.ndarray, angle: float) -> tuple[np.ndarray, np.ndarray]:
    """Rotate the view level by the measured tilt, keeping every pixel visible.

    The returned matrix maps the input frame to the returned frame, so pass evidence
    can be mapped back to the uploaded canvas. An angle of 0 is the identity.
    """
    height, width = image.shape[:2]
    centre = (width / 2.0, height / 2.0)
    matrix = cv2.getRotationMatrix2D(centre, angle, 1.0)
    cosine, sine = abs(matrix[0, 0]), abs(matrix[0, 1])
    new_width = int(height * sine + width * cosine)
    new_height = int(height * cosine + width * sine)
    matrix[0, 2] += new_width / 2.0 - centre[0]
    matrix[1, 2] += new_height / 2.0 - centre[1]
    frame = cv2.warpAffine(image, matrix, (new_width, new_height),
                           flags=cv2.INTER_CUBIC, borderValue=(255, 255, 255))
    return frame, np.vstack([matrix, [0.0, 0.0, 1.0]])


# Card localisation. A handheld photograph shows the card on a desk or in a hand, at an
# angle and filling only part of the frame. The detector reads the whole frame at a
# bounded size, so the card gets fewer pixels than the upload holds, and perspective
# makes its rows converge. When the card outline is a clear quadrilateral, the card is
# flattened to a front view at a detector-friendly size. Nothing is found — and nothing
# changes — when the card fills the frame, when an edge is hidden or cut off, or when
# the outline is not card-shaped. KTP is 85.6 x 54 mm (1.59) and business cards run
# from about 1.5 to 1.9; perspective widens the range that has to be accepted.
CARD_MIN_AREA = 0.12
CARD_MAX_AREA = 0.92
CARD_ASPECT = (1.25, 2.2)
CARD_BORDER_MARGIN = 0.004
CARD_TARGET_SIDE = 1600
CARD_MAX_UPSCALE = 2.0
CARD_PADDING = 0.02
CARD_MIN_ANGLE, CARD_MAX_ANGLE = 60.0, 120.0


def _ordered_corners(points: np.ndarray) -> np.ndarray:
    """Top-left, top-right, bottom-right, bottom-left, whatever the in-plane angle."""
    points = points.reshape(4, 2).astype("float32")
    centre = points.mean(axis=0)
    ordered = points[np.argsort(np.arctan2(points[:, 1] - centre[1], points[:, 0] - centre[0]))]
    return np.roll(ordered, -int(np.argmin(ordered.sum(axis=1))), axis=0)


def _card_quad(contour: np.ndarray, width: int, height: int) -> np.ndarray | None:
    hull = cv2.convexHull(contour)
    area = cv2.contourArea(hull)
    if not CARD_MIN_AREA * width * height <= area <= CARD_MAX_AREA * width * height:
        return None
    perimeter = cv2.arcLength(hull, True)
    for epsilon in (0.02, 0.03, 0.045):
        approx = cv2.approxPolyDP(hull, epsilon * perimeter, True)
        if len(approx) == 4:
            break
    else:
        return None
    corners = _ordered_corners(approx)
    # A rounded card corner cuts the hull short; the quad must still cover the outline.
    if cv2.contourArea(corners) < 0.9 * area or cv2.contourArea(contour) < 0.8 * area:
        return None
    margin_x, margin_y = CARD_BORDER_MARGIN * width, CARD_BORDER_MARGIN * height
    if (corners[:, 0].min() < margin_x or corners[:, 0].max() > width - 1 - margin_x
            or corners[:, 1].min() < margin_y or corners[:, 1].max() > height - 1 - margin_y):
        return None  # touching the frame: the card is cut off or fills the picture
    for index in range(4):
        before = corners[index - 1] - corners[index]
        after = corners[(index + 1) % 4] - corners[index]
        cosine = float(before @ after / (np.linalg.norm(before) * np.linalg.norm(after) + 1e-9))
        if not CARD_MIN_ANGLE <= degrees(np.arccos(np.clip(cosine, -1, 1))) <= CARD_MAX_ANGLE:
            return None
    sides = [float(np.linalg.norm(corners[(i + 1) % 4] - corners[i])) for i in range(4)]
    across, down = (sides[0] + sides[2]) / 2, (sides[1] + sides[3]) / 2
    aspect = max(across, down) / max(min(across, down), 1.0)
    if not CARD_ASPECT[0] <= aspect <= CARD_ASPECT[1]:
        return None
    return corners


def _card_masks(image: np.ndarray):
    """Candidate foreground masks, cheapest and most specific first."""
    lab = cv2.cvtColor(cv2.GaussianBlur(image, (5, 5), 0), cv2.COLOR_BGR2LAB).astype(np.float32)
    # The card differs from its surroundings: measure every pixel against the colour of
    # the frame border, which a card that does not fill the picture leaves visible.
    border = np.concatenate([lab[:4].reshape(-1, 3), lab[-4:].reshape(-1, 3),
                             lab[:, :4].reshape(-1, 3), lab[:, -4:].reshape(-1, 3)])
    distance = np.linalg.norm(lab - np.median(border, axis=0), axis=2)
    distance = cv2.normalize(distance, np.zeros_like(distance), 0, 255, cv2.NORM_MINMAX).astype(np.uint8)
    _, mask = cv2.threshold(distance, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (9, 9))
    yield cv2.morphologyEx(cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel), cv2.MORPH_OPEN, kernel)
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    level = float(np.median(gray))
    edges = cv2.Canny(cv2.GaussianBlur(gray, (5, 5), 0), 0.5 * level, 1.2 * level)
    yield cv2.morphologyEx(edges, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (7, 7)))


# Two foreground objects this large, and within a factor of two of each other, are two
# cards rather than one card and some clutter.
CARD_OBJECT_AREA = 0.05


def _several_objects(mask: np.ndarray) -> bool:
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    areas = sorted((cv2.contourArea(c) for c in contours), reverse=True)
    large = [a for a in areas if a >= CARD_OBJECT_AREA * mask.size]
    return len(large) >= 2 and large[1] >= 0.5 * large[0]


def find_card(image: np.ndarray, max_side: int = 2000) -> tuple[np.ndarray, np.ndarray] | None:
    """Flattened front view of a card photographed on a background, or None.

    The returned 3x3 matrix maps the given image onto the returned frame.
    """
    height, width = image.shape[:2]
    scale = min(1.0, 640 / max(height, width))
    small = cv2.resize(image, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    small_h, small_w = small.shape[:2]
    corners = None
    for number, mask in enumerate(_card_masks(small)):
        if number == 0 and _several_objects(mask):
            return None  # a front-and-back mockup or two cards: cropping one would drop the other
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        for contour in sorted(contours, key=cv2.contourArea, reverse=True)[:3]:
            corners = _card_quad(contour, small_w, small_h)
            if corners is not None:
                break
        if corners is not None:
            break
    if corners is None:
        return None
    corners = corners / scale
    sides = [float(np.linalg.norm(corners[(i + 1) % 4] - corners[i])) for i in range(4)]
    across, down = max(sides[0], sides[2]), max(sides[1], sides[3])
    zoom = min(CARD_MAX_UPSCALE, max(1.0, CARD_TARGET_SIDE / max(across, down)),
               max_side / (max(across, down) * (1 + 2 * CARD_PADDING)))
    card_w, card_h = across * zoom, down * zoom
    pad_x, pad_y = CARD_PADDING * card_w, CARD_PADDING * card_h
    target = np.array([[pad_x, pad_y], [pad_x + card_w, pad_y],
                       [pad_x + card_w, pad_y + card_h], [pad_x, pad_y + card_h]], dtype=np.float32)
    matrix = cv2.getPerspectiveTransform(corners.astype("float32"), target)
    size = (round(card_w + 2 * pad_x), round(card_h + 2 * pad_y))
    frame = cv2.warpPerspective(image, matrix, size, flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)
    return frame, matrix.astype(float)


def text_focus(image, spans, settings, *, contrast=False):
    """Magnify the detected text area, with a bounded output and coordinate transform.

    Used when the median detected text height is small: re-detecting the crop at a
    larger effective size gives the detector and the recogniser more pixels per glyph.
    """
    used = [s for s in spans if s.score >= 0.7 and len(s.text.strip()) >= 3]
    if not used:
        return None
    xy = np.asarray([p for s in used for p in s.box])
    padding = max(12, round(np.median([s.height for s in used])))
    x0, y0 = np.maximum(0, np.floor(xy.min(axis=0) - padding)).astype(int)
    x1, y1 = np.minimum(image.shape[1::-1], np.ceil(xy.max(axis=0) + padding)).astype(int)
    if x1 - x0 < 40 or y1 - y0 < 30:
        return None
    frame = image[y0:y1, x0:x1]
    scale = min(2.5, settings.max_side / max(frame.shape[:2]))
    width, height = round(frame.shape[1] * scale), round(frame.shape[0] * scale)
    frame = cv2.resize(frame, (width, height), interpolation=cv2.INTER_CUBIC)
    if contrast:
        frame = enhance(frame)
    matrix = np.asarray([[width / (x1 - x0), 0, -x0 * width / (x1 - x0)],
                         [0, height / (y1 - y0), -y0 * height / (y1 - y0)], [0, 0, 1]])
    return frame, matrix
