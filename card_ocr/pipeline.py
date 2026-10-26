from dataclasses import replace
from statistics import median
from time import perf_counter
from uuid import uuid4

import numpy as np
import phonenumbers

from .config import Settings
from .engine import Engine
from .errors import OCRProblem
from .imaging import (
    SKEW_MIN_CORRECTION,
    crop_span,
    decode_source,
    deskew,
    enhance,
    find_card,
    respace_candidate,
    rotate,
    rotation_matrix,
    skew_angle,
    text_focus,
    word_pieces,
)
from .locate import (
    CardOutline,
    card_view,
    line_geometry,
    locate_card,
    on_card,
    quarter_turn,
    runs_off,
    text_direction,
)
from .parsers import business, ktp
from .parsers.common import Observation, Parsed, flag, resolve
from .schemas import DocumentType, FieldResult, Mode, OCRResponse, PassInfo, Processing, Span


def _agreement_key(text: str) -> str:
    return "".join(character for character in text.upper() if character.isalnum())


def _with_breaks(text: str, word_lengths: list[int], kept: list[int] | None = None) -> str:
    """The characters of ``text`` with a space before each word that starts a new
    re-read piece; ``word_lengths`` counts letters and digits per piece. ``kept`` lists
    further breaks, by letters and digits before them, that stay. Punctuation stays
    attached to the word before it, and two digits are never separated."""
    if sum(word_lengths) != sum(character.isalnum() for character in text):
        return text
    starts = set(kept or ())
    total = 0
    for length in word_lengths[:-1]:
        total += length
        starts.add(total)
    result: list[str] = []
    seen = 0
    previous = ""
    for character in text:
        if character.isspace():
            continue
        if character.isalnum():
            if seen in starts and result and not (previous.isdigit() and character.isdigit()):
                result.append(" ")
            seen += 1
            previous = character
        result.append(character)
    return "".join(result)


def _chain(*matrices) -> np.ndarray | None:
    """Compose 3x3 transforms written in application order right to left; None is identity."""
    present = [np.asarray(matrix, dtype=float) for matrix in matrices if matrix is not None]
    if not present:
        return None
    result = present[0]
    for matrix in present[1:]:
        result = result @ matrix
    return result


# A magnified text-crop retry runs when the median detected glyph height falls below
# OCR_SMALL_TEXT_HEIGHT_PX; see config.Settings for the measured tradeoff.
def _small_print(heights: list[float], settings: Settings) -> bool:
    return bool(heights) and median(heights) < settings.small_text_height_px


# An outline that covers this much of a level photograph is the photograph: reading its
# flattened view again would show the recogniser the same pixels.
CARD_FILLS_FRAME = 0.85
# Print turned by more than this against the rest of the card is not part of its layout:
# another card underneath, a cable, a logo set on its side.
CARD_TEXT_MAX_TURN = 8.0
# Print standing on its side reads as a tall box. Two letters can be taller than wide.
SIDEWAYS_MIN_CHARACTERS = 3
SIDEWAYS_RATIO = 2.0


def _card_text(spans: list[Span], outline: CardOutline | None, forward, width: int, height: int) -> list[Span]:
    """The boxes that belong to the photographed business card.

    Dropped: print outside the located outline, print cut off by the edge of the
    photograph (the rest of that line was never seen), and print turned against the
    direction most of the card shares. ``forward`` maps the photograph onto the frame
    the boxes were read from; None when they were read from the photograph itself.
    """
    back = None if forward is None else np.linalg.inv(np.asarray(forward, dtype=float))
    kept = []
    for span in spans:
        box = np.asarray(span.box, dtype=float)
        if box.shape != (4, 2):
            continue
        if back is not None:
            box = _carry(box, back)
        if runs_off(box.tolist(), width, height):
            continue
        if outline is not None and not on_card(box, outline.corners):
            continue
        kept.append(span)
    direction = text_direction(kept)
    if direction is None:
        return kept
    aligned = []
    for span in kept:
        angle, length, tall = line_geometry(span.box)
        if len(span.text.strip()) >= SIDEWAYS_MIN_CHARACTERS and (
                tall >= SIDEWAYS_RATIO * length
                or (length >= 1.5 * tall and abs(angle - direction) > CARD_TEXT_MAX_TURN)):
            continue
        aligned.append(span)
    return aligned


def _carry(points, matrix: np.ndarray) -> np.ndarray:
    """Points carried into another frame by a 3x3 transform."""
    points = np.asarray(points, dtype=float)
    carried = np.c_[points, np.ones(len(points))] @ np.asarray(matrix, dtype=float).T
    return carried[:, :2] / carried[:, 2:]


def _move(spans: list[Span], matrix: np.ndarray) -> None:
    """Carry boxes into another frame, in place."""
    for span in spans:
        span.box = _carry(span.box, matrix).round(2).tolist()


def _classify(spans: list[Span], region: str) -> tuple[str | None, int]:
    parsed_ktp = ktp.parse(spans)
    if parsed_ktp.anchors >= 3:
        return "ktp", parsed_ktp.anchors * 10
    # Only the kinds of contact are counted here; how a second number is completed is not.
    parsed_business = business.parse(spans, region)
    if parsed_business.anchors and len(spans) >= 2:
        return "business_card", parsed_business.anchors * 3
    return None, 0


def _resolve_ktp(observations: dict[str, list[Observation]], mode: Mode, settings: Settings) -> dict[str, FieldResult]:
    # Layout-only name candidates are a fallback. Once a printed name label is
    # read, only those labelled observations may establish its value/consensus.
    names = observations.get("full_name", [])
    labeled_names = [item for item in names if "unlabeled_name_requires_review" not in item.issues]
    fields = {
        key: resolve(
            (labeled_names or names) if key == "full_name" else observations.get(key, []),
            settings.nik_threshold if key == "nik" else settings.field_threshold,
            consensus=(mode == "accurate" or key == "nik"),
            single_pass_threshold=None if key == "nik" else settings.single_pass_threshold,
        )
        for key in ktp.FIELDS
    }
    ktp.cross_validate(fields, strict=settings.strict_nik_cross_check,
                       corroborate_gender=settings.nik_corroborates_gender)
    ktp.review_lookalikes(fields)
    return fields


class OCRPipeline:
    def __init__(self, engine: Engine, settings: Settings):
        self.engine = engine
        self.settings = settings

    def _respace(self, image: np.ndarray, spans: list[Span]) -> None:
        """Set the word breaks of a line from the image, in place.

        Each word between the blank pixel columns of a line is re-read on its own. When
        the re-read letters and digits are those of the original line, the re-read word
        breaks are applied to the original characters. Only spaces change: a colon or full
        stop the narrow-piece filter dropped from the re-read is kept, and a break is never
        put inside a run of digits.
        """
        reader = getattr(self.engine, "recognize_crop", None)
        if reader is None:
            return
        for span in spans:
            if not respace_candidate(span.text):
                continue
            patch = crop_span(image, span.box)
            if patch is None:
                continue
            pieces = word_pieces(patch)
            if not pieces:
                continue
            words = []
            for piece in pieces:
                word = reader(piece)
                if word is None:
                    words = []
                    break
                if word:
                    words.append(word)
            if not words or _agreement_key("".join(words)) != _agreement_key(span.text):
                continue
            # Breaks are the pixel gaps plus any break the recogniser still reads inside
            # one piece: a space is removed only when the tight re-read also has none.
            lengths = [len(_agreement_key(part)) for part in " ".join(words).split()]
            span.text = _with_breaks(span.text, [length for length in lengths if length], span.kept_breaks)

    def process(
        self,
        payload: bytes,
        document_type: DocumentType = "auto",
        mode: Mode = "accurate",
        include_raw: bool = False,
        rotation: int = 0,
        phone_region: str | None = None,
    ) -> OCRResponse:
        started = perf_counter()
        region = (phone_region or self.settings.default_phone_region).strip().upper()
        if region not in phonenumbers.SUPPORTED_REGIONS:
            raise OCRProblem("INVALID_PHONE_REGION", "Use a supported two-letter phone region, such as ID or US.")
        image, quality, source = decode_source(payload, self.settings)
        image, source = rotate(image, rotation), rotate(source, rotation)
        passes: list[PassInfo] = []
        raw: list[Span] = []
        # What maps the rotated upload onto the frame each pass read; None is the upload.
        frames: dict[str, np.ndarray | None] = {}

        def to_input(degrees: int, forward) -> list[list[float]]:
            return (np.linalg.inv(rotation_matrix(quality.width, quality.height, degrees))
                    @ np.linalg.inv(np.eye(3) if forward is None else forward)).round(8).tolist()

        def read(frame: np.ndarray, degrees: int, enhancement: str, forward=None) -> list[Span]:
            pass_id = f"p{len(passes) + 1}"
            tick = perf_counter()
            spans = self.engine.recognize(frame, pass_id)
            passes.append(
                PassInfo(
                    id=pass_id,
                    rotation_clockwise=degrees % 360,
                    enhancement=enhancement,
                    width=frame.shape[1],
                    height=frame.shape[0],
                    ocr_ms=round((perf_counter() - tick) * 1000, 2),
                    to_input=to_input(degrees, forward),
                )
            )
            raw.extend(spans)
            frames[pass_id] = forward
            return spans

        def card_text(spans: list[Span]) -> list[Span]:
            if not spans:
                return spans
            return _card_text(spans, outline, frames[spans[0].pass_id], image.shape[1], image.shape[0])

        base: list[Span] | None = None
        for upright in (False, True):
            base, input_view = None, image
            # Maps the rotated upload onto the flattened card view, when one is used.
            origin: np.ndarray | None = None
            # A card photographed on a background is read from a flattened front view: the
            # detector sees the card at full resolution, and perspective no longer makes
            # its rows converge. The view is kept only when it reads as the requested kind
            # of card; otherwise the whole image is read exactly as before, and the
            # discarded read stays visible in raw_ocr without contributing evidence.
            if self.settings.card_detection:
                card = find_card(image, self.settings.max_side)
                if card is not None:
                    frame, matrix = card
                    spans = read(frame, rotation, "card", matrix)
                    found, _ = _classify(spans, region)
                    if found is not None and document_type in ("auto", found):
                        base, input_view, origin = spans, frame, matrix
            if base is None:
                base = read(image, rotation, "original")
            # A card held sideways or upside down is still read line by line, each line
            # turned on its own, with its layout standing on its head: names under titles,
            # rows as columns. Which lines the classifier turned says how the card lies,
            # so the upload is set upright and read once more (both modes). A requested
            # KTP keeps its own orientation probes below.
            turn = 0 if upright or document_type == "ktp" else quarter_turn(base)
            if not turn:
                break
            image, source = rotate(image, turn), rotate(source, turn)
            rotation = (rotation + turn) % 360
        # A business card held in a hand, or lying among other things, is found around its
        # own print: the first read says where the card is and how it is turned. Accurate
        # mode reads a flattened view cut from the full-size upload, and the first read
        # then only stays visible in raw_ocr; fast mode moves its one read into that view.
        # Either way print outside the outline never becomes evidence. The view is kept
        # when it reads as a business card with every kind of contact the first read saw
        # on the card. The outline is looked for in whatever was read first, so a view
        # found by the card's silhouette that also took in the card underneath is
        # narrowed to the card in front. A KTP keeps the path it was tuned on.
        outline: CardOutline | None = None
        screened = bool(base) and (document_type == "business_card" or (
            document_type == "auto" and _classify(base, region)[0] == "business_card"))
        if screened and self.settings.card_detection:
            outline = locate_card(input_view, base)
            if (outline is not None and outline.area >= CARD_FILLS_FRAME
                    and abs(outline.angle) < SKEW_MIN_CORRECTION):
                outline = None
            if outline is not None:
                if origin is not None:
                    outline = replace(outline, corners=_carry(outline.corners, np.linalg.inv(origin)))
                detail = source.shape[1] / image.shape[1]
                frame, matrix = card_view(source, outline.corners * detail, self.settings.max_side)
                matrix = matrix @ np.diag([detail, detail, 1.0])
                if mode == "accurate":
                    spans = read(frame, rotation, "card", matrix)
                    found, _ = _classify(spans, region)
                    seen = business.parse(card_text(base), region).anchors
                    if found == "business_card" and business.parse(card_text(spans), region).anchors >= max(seen, 1):
                        base, input_view, origin = spans, frame, matrix
                    else:
                        outline = None
                        screened = found != "ktp"
                else:
                    read_as = next(item for item in passes if item.id == base[0].pass_id)
                    step = matrix if origin is None else matrix @ np.linalg.inv(origin)
                    _move([span for span in raw if span.pass_id == read_as.id], step)
                    read_as.to_input = to_input(rotation, matrix)
                    frames[read_as.id] = matrix
                    input_view, origin = frame, matrix
        if screened:
            base = card_text(base)
        view, skew_matrix = input_view, None
        # A tilted page inflates the rotated text boxes, which breaks row clustering and
        # column splitting. The levelled re-read replaces the tilted read for parsing;
        # the tilted read stays visible in raw_ocr without contributing evidence.
        if self.settings.deskew_retry:
            angle = skew_angle(base)
            if abs(angle) >= SKEW_MIN_CORRECTION:
                frame, matrix = deskew(input_view, angle)
                if mode == "accurate":
                    corrected = read(frame, rotation, "deskew", _chain(matrix, origin))
                    if screened:
                        corrected = card_text(corrected)
                    if (corrected and abs(skew_angle(corrected)) < abs(angle)
                            and (origin is None or _classify(corrected, region)[0] is not None)):
                        base, view, skew_matrix = corrected, frame, matrix
                else:
                    # Fast mode has no read to spare. The recognised text of a tilted page
                    # is sound; its row geometry is not. The boxes are moved into the
                    # levelled frame instead, and the pass's to_input follows them.
                    _move([span for span in raw if span.pass_id == passes[-1].id], np.asarray(matrix))
                    passes[-1].to_input = to_input(rotation, _chain(matrix, origin))
                    frames[passes[-1].id] = _chain(matrix, origin)
                    view, skew_matrix = frame, matrix
        inferred, rank = _classify(base, region)
        # Orientation probes run when classification fails, or when a KTP was requested and
        # the read does not look like one: a card turned by a quarter reads as scattered
        # digits, which can pass for a business card's phone numbers. Fast mode probes only
        # in that second case, where the alternative is an error response. Business
        # small-print retries are separate. A card view was kept only because it classified
        # as the requested kind, so it never needs one.
        sideways = bool(base) and document_type == "ktp" and inferred != "ktp"
        misread = inferred is None or sideways
        if misread and (mode == "accurate" or sideways) and origin is None:
            alternatives = [(rank, inferred, base, view, rotation, skew_matrix)]
            for extra in (90, 270):
                alternative = rotate(input_view, extra)
                matrix = None
                if skew_matrix is not None:
                    alternative, matrix = deskew(alternative, angle)
                spans = read(alternative, rotation + extra, "orientation_probe", matrix)
                kind, rating = _classify(spans, region)
                alternatives.append((rating, kind, spans, alternative, (rotation + extra) % 360, matrix))
            before = rotation
            _, inferred, base, view, rotation, skew_matrix = max(alternatives, key=lambda item: item[0])
            # A probe frame is the upload turned once more; its boxes are not screened.
            screened = screened and rotation == before
        if not base:
            raise OCRProblem("NO_TEXT", "No readable text found. Retake the image without blur or glare.")
        if document_type == "auto":
            if inferred is None:
                raise OCRProblem(
                    "DOCUMENT_TYPE_UNCERTAIN", "Select KTP or business_card explicitly, or retake the image."
                )
            kind = inferred
        else:
            kind = document_type
            if (kind == "ktp" and inferred != "ktp") or (kind == "business_card" and inferred == "ktp"):
                raise OCRProblem(
                    "DOCUMENT_TYPE_MISMATCH", "The image does not match the selected document type."
                )
        # Business cards are respaced too, but never a contact line: a gap around the "@"
        # or a dot of an address is not a word break.
        if self.settings.respace_words:
            self._respace(view, base if kind == "ktp"
                          else [span for span in base if not business.contact_text(span.text)])
        selected_passes = [base]
        screen = card_text if screened else (lambda spans: spans)
        if mode == "accurate":
            selected_passes.append(screen(read(enhance(view), rotation, "clahe", _chain(skew_matrix, origin))))
        # Small print is re-read from a magnified crop for either card type: detection at
        # a larger effective glyph size can separate lines the full-image pass merged,
        # and every retry read joins the same evidence pool as the full-image reads.
        heights = [(np.linalg.norm(np.asarray(s.box[3]) - s.box[0])
                    + np.linalg.norm(np.asarray(s.box[2]) - s.box[1])) / 2
                   for s in base if len(s.text.strip()) >= 3 and s.score >= 0.7]
        small_print = _small_print(heights, self.settings)
        if heights:
            quality.text_height_px = round(median(heights), 1)
        if small_print:
            quality.warnings.append("small_text")
            if mode == "accurate" and self.settings.small_text_retry and self.settings.business_retry:
                for contrast in (False, True):
                    focus = text_focus(view, base, self.settings, contrast=contrast)
                    if focus is not None:
                        frame, forward = focus
                        selected_passes.append(screen(read(frame, rotation,
                            "text_focus_contrast" if contrast else "text_focus",
                            _chain(forward, skew_matrix, origin))))
        parsed_passes: list[Parsed] = [
            ktp.parse(spans) if kind == "ktp"
            else business.parse(spans, region, self.settings.shared_area_code)
            for spans in selected_passes
        ]
        observations: dict[str, list[Observation]] = {}
        for parsed in parsed_passes:
            for key, items in parsed.fields.items():
                observations.setdefault(key, []).extend(items)
        fields: dict[str, FieldResult | list[FieldResult]] = {}
        if kind == "ktp":
            fields = _resolve_ktp(observations, mode, self.settings)
            recover = {key for key in (*ktp.REQUIRED, "rt", "rw", "village", "district")
                       if fields[key].status != "accepted"
                       and fields[key].reasons != ["ambiguous_block_character"]}
            if mode == "accurate" and self.settings.ktp_recovery and recover:
                focus = text_focus(view, ktp.recovery_spans(base, recover), self.settings)
                if focus is not None:
                    frame, forward = focus
                    for contrast in (False, True):
                        retry_view = enhance(frame) if contrast else frame
                        spans = read(retry_view, rotation,
                                     "ktp_recovery_contrast" if contrast else "ktp_recovery",
                                     _chain(forward, skew_matrix, origin))
                        if self.settings.respace_words:
                            self._respace(retry_view, spans)
                        for key, items in ktp.parse(spans).fields.items():
                            # Neighbouring rows are context and can be cut by the crop.
                            # Only unresolved target fields receive retry observations;
                            # e.g. a clipped header must not replace a complete one.
                            if key in recover:
                                height, width = retry_view.shape[:2]
                                for item in items:
                                    if any(runs_off(s.box, width, height) or s.y <= 1
                                           or s.y + s.height >= height - 2
                                           for s in item.value_spans or item.spans):
                                        item.issues.append("recovery_text_touches_crop_edge")
                                observations.setdefault(key, []).extend(items)
                    fields = _resolve_ktp(observations, mode, self.settings)
        else:
            for key in business.SCALAR_FIELDS:
                fields[key] = business.resolve_field(
                    observations.get(key, []), self.settings.field_threshold, consensus=mode == "accurate",
                    spacing_insensitive=True,
                )
            transforms = {p.id: p.to_input for p in passes}
            for key in business.LIST_FIELDS:
                fields[key] = business.resolve_contacts(
                    observations.get(key, []), self.settings.field_threshold, mode == "accurate", transforms
                )
            if not any(observations.values()):
                raise OCRProblem("NO_FIELDS", "Text was detected but no card fields could be extracted.")

        review_reasons = [f"image:{issue}" for issue in quality.warnings]
        severe_quality = any(w in quality.warnings for w in ("possible_blur", "low_contrast"))
        data: dict[str, str | None | list[str]] = {}
        for key, result in fields.items():
            results = result if isinstance(result, list) else [result]
            for field in results:
                if severe_quality:
                    flag(field, "image_quality_requires_review")
                if field.status == "review":
                    review_reasons.append(f"{key}:" + ",".join(field.reasons))
            data[key] = (
                [f.value for f in results if f.value is not None]
                if isinstance(result, list)
                else result.value
            )
        required = ktp.REQUIRED if kind == "ktp" else ("full_name", "company")
        for key in required:
            if fields[key].status == "missing":
                review_reasons.append(f"{key}:not_found")
        if kind == "business_card":
            # The accepted numbers that are mobile lines, for a form's "mobile phone" field.
            data["mobile_phones"] = [field.value for field in fields["phones"]
                                     if field.value is not None and field.phone_type == "mobile"]
        if kind == "business_card" and not any(data[k] for k in ("emails", "phones", "websites")):
            review_reasons.append("no_accepted_contact")
        if mode == "fast":
            review_reasons.append("fast_mode_single_read")
        needs_review = bool(review_reasons)
        return OCRResponse(
            request_id=str(uuid4()),
            document_type=kind,
            status="needs_review" if needs_review else "ok",
            needs_review=needs_review,
            data=data,
            fields=fields,
            review_reasons=sorted(set(review_reasons)),
            quality=quality,
            processing=Processing(
                mode=mode,
                elapsed_ms=round((perf_counter() - started) * 1000, 2),
                engine=self.engine.name,
                models=self.engine.models,
                model_hashes=self.engine.hashes,
                passes=passes,
                phone_region=region if kind == "business_card" else None,
            ),
            raw_ocr=raw if include_raw else None,
        )
