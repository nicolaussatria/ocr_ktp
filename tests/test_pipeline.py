"""Pipeline pass selection: deskew recovery and small-print retries."""

import math

import cv2
import numpy as np
import pytest
from conftest import StubEngine, drawn_photo, tilted_line

from card_ocr.config import Settings
from card_ocr.pipeline import OCRPipeline
from card_ocr.schemas import Span


def slanted_box(x: float, y: float, width: float, height: float, angle: float) -> list[list[float]]:
    """A text-line quad whose top edge is tilted by ``angle`` degrees (y grows downward)."""
    drop = width * math.tan(math.radians(angle))
    return [[x, y], [x + width, y + drop], [x + width, y + drop + height], [x, y + height]]


class TiltAwareEngine(StubEngine):
    """Tilted boxes on the first read; level boxes once the view is corrected."""

    def recognize(self, image, pass_id):
        self.calls += 1
        angle = 2.5 if pass_id == "p1" else 0.0
        return [
            Span(text=text, score=0.999, box=slanted_box(30, index * 50, 300, 30, angle), pass_id=pass_id)
            for index, text in enumerate(self.lines, 1)
        ]


def test_tilted_read_is_replaced_by_a_levelled_read(image_bytes):
    engine = TiltAwareEngine()
    result = OCRPipeline(engine, Settings(_env_file=None)).process(image_bytes, "ktp")
    assert [item.enhancement for item in result.processing.passes][:2] == ["original", "deskew"]
    assert result.data["full_name"] == "NAMA CONTOH"
    assert result.data["nik"] == "9901011508901234"


def test_level_reads_do_not_add_a_deskew_pass(image_bytes):
    engine = StubEngine()
    result = OCRPipeline(engine, Settings(_env_file=None)).process(image_bytes, "ktp")
    assert [item.enhancement for item in result.processing.passes] == ["original", "clahe"]
    assert engine.calls == 2


def test_deskew_can_be_disabled_and_is_skipped_in_fast_mode(image_bytes):
    engine = TiltAwareEngine()
    result = OCRPipeline(engine, Settings(_env_file=None, deskew_retry=False)).process(image_bytes, "ktp")
    # The page is re-read unlevelled: no deskew pass, and evidence keeps the pass ids of the reads made.
    assert [item.enhancement for item in result.processing.passes] == ["original", "clahe"]
    assert {span.pass_id for span in result.raw_ocr or []} <= {"p1", "p2"}
    engine = TiltAwareEngine()
    OCRPipeline(engine, Settings(_env_file=None)).process(image_bytes, "ktp", "fast")
    assert engine.calls == 1


class SteepTiltEngine(StubEngine):
    """Every read tilted by 5 degrees across wide lines: enough to merge neighbouring rows."""

    def recognize(self, image, pass_id):
        self.calls += 1
        return [
            Span(text=text, score=0.999, box=slanted_box(30, index * 50, 1000, 30, 5.0), pass_id=pass_id)
            for index, text in enumerate(self.lines, 1)
        ]


def test_fast_mode_levels_the_geometry_of_a_tilted_read(image_bytes):
    settings = Settings(_env_file=None)
    unlevelled = OCRPipeline(SteepTiltEngine(), Settings(_env_file=None, deskew_retry=False))
    assert unlevelled.process(image_bytes, "ktp", "fast").data["religion"] != "ISLAM"  # rows merged
    engine = SteepTiltEngine()
    result = OCRPipeline(engine, settings).process(image_bytes, "ktp", "fast", include_raw=True)
    assert engine.calls == 1
    assert result.data["religion"] == "ISLAM"
    assert result.data["full_name"] == "NAMA CONTOH"
    # Boxes are reported in the levelled frame, and to_input still maps them onto the upload.
    first = result.raw_ocr[0]
    corner = np.asarray(result.processing.passes[0].to_input) @ np.array([*first.box[0], 1.0])
    assert np.allclose(corner[:2] / corner[2], slanted_box(30, 50, 1000, 30, 5.0)[0], atol=0.5)


class SmallPrintEngine(StubEngine):
    """KTP lines with print below the small-text threshold."""

    def recognize(self, image, pass_id):
        self.calls += 1
        return [
            Span(text=text, score=0.999, box=[[30, index * 22], [600, index * 22],
                                              [600, index * 22 + 16], [30, index * 22 + 16]], pass_id=pass_id)
            for index, text in enumerate(self.lines, 1)
        ]


def test_small_print_ktp_gets_magnified_retries(image_bytes):
    engine = SmallPrintEngine()
    result = OCRPipeline(engine, Settings(_env_file=None)).process(image_bytes, "ktp")
    assert engine.calls == 4
    assert [item.enhancement for item in result.processing.passes] == [
        "original", "clahe", "text_focus", "text_focus_contrast"
    ]
    assert "small_text" in result.quality.warnings
    assert result.quality.text_height_px == 16.0
    assert result.data["nik"] == "9901011508901234"


def desk_photo() -> bytes:
    image = np.full((900, 1200, 3), (40, 70, 110), np.uint8)
    cv2.fillConvexPoly(image, np.int32([[250, 220], [950, 190], [980, 640], [230, 650]]), (245, 245, 240))
    return cv2.imencode(".png", image)[1].tobytes()


class ShapeEngine(StubEngine):
    """Reads the card only from frames whose shape passes ``readable``."""

    def __init__(self, readable):
        super().__init__()
        self.readable = readable
        self.shapes = []

    def recognize(self, image, pass_id):
        self.shapes.append(image.shape[:2])
        return super().recognize(image, pass_id) if self.readable(image.shape[:2]) else []


def test_photographed_card_is_read_from_its_flattened_view():
    engine = ShapeEngine(lambda shape: True)
    result = OCRPipeline(engine, Settings(_env_file=None)).process(desk_photo(), "ktp")
    passes = result.processing.passes
    assert [item.enhancement for item in passes] == ["card", "clahe"]
    assert engine.shapes[0] != (900, 1200)
    assert result.data["nik"] == "9901011508901234"
    # Card-view coordinates map back onto the uploaded photograph, inside the card.
    corner = np.asarray(passes[0].to_input) @ np.array([0.0, 0.0, 1.0])
    x, y = corner[:2] / corner[2]
    assert 200 < x < 260 and 170 < y < 230
    assert passes[1].to_input == passes[0].to_input


def test_a_card_view_that_does_not_read_falls_back_to_the_whole_photo():
    engine = ShapeEngine(lambda shape: shape == (900, 1200))
    result = OCRPipeline(engine, Settings(_env_file=None)).process(desk_photo(), "ktp")
    assert [item.enhancement for item in result.processing.passes] == ["card", "original", "clahe"]
    assert result.data["nik"] == "9901011508901234"
    # The discarded card read contributes no evidence.
    assert {e.pass_id for e in result.fields["nik"].candidates[0].evidence} == {"p2", "p3"}


def test_card_detection_can_be_disabled(image_bytes):
    engine = ShapeEngine(lambda shape: True)
    settings = Settings(_env_file=None, card_detection=False)
    result = OCRPipeline(engine, settings).process(desk_photo(), "ktp")
    assert [item.enhancement for item in result.processing.passes] == ["original", "clahe"]
    # A flat scan never gets a card pass.
    result = OCRPipeline(ShapeEngine(lambda shape: True), Settings(_env_file=None)).process(image_bytes, "ktp")
    assert [item.enhancement for item in result.processing.passes] == ["original", "clahe"]


def test_small_print_retries_can_be_disabled_and_skip_fast_mode(image_bytes):
    engine = SmallPrintEngine()
    OCRPipeline(engine, Settings(_env_file=None, small_text_retry=False)).process(image_bytes, "ktp")
    assert engine.calls == 2
    # The retained business-card setting still disables the shared small-print retry.
    engine = SmallPrintEngine()
    OCRPipeline(engine, Settings(_env_file=None, business_retry=False)).process(image_bytes, "ktp")
    assert engine.calls == 2
    # A threshold at or below the measured glyph height does not retry either.
    engine = SmallPrintEngine()
    OCRPipeline(engine, Settings(_env_file=None, small_text_height_px=16)).process(image_bytes, "ktp")
    assert engine.calls == 2
    engine = SmallPrintEngine()
    OCRPipeline(engine, Settings(_env_file=None)).process(image_bytes, "ktp", "fast")
    assert engine.calls == 1


class IncompleteKTPEngine(StubEngine):
    """Ordinary-sized print with a missing name and damaged NIK/address at first."""

    def __init__(self, recover=True, conflict=False):
        super().__init__()
        self.recover = recover
        self.conflict = conflict

    def recognize(self, image, pass_id):
        spans = super().recognize(image, pass_id)
        if self.calls <= 2 or not self.recover:
            for span in spans:
                if span.text.startswith("NIK"):
                    span.text = "NIK : 990101150890123"
                if span.text.startswith("Alamat"):
                    span.text = "Alamat : JL CNT0H"
                    span.score = 0.70
            return [s for s in spans if not s.text.startswith("Nama")]
        if self.conflict:
            for span in spans:
                if span.text.startswith("NIK"):
                    # Two plausible complete readings must stay in review.
                    span.text = "NIK : 990101150890123" + ("4" if self.calls == 3 else "5")
        return spans


def test_incomplete_ktp_triggers_recovery_even_without_small_print(image_bytes):
    engine = IncompleteKTPEngine()
    result = OCRPipeline(engine, Settings(_env_file=None)).process(image_bytes, "ktp", include_raw=True)
    assert engine.calls == 4
    assert "small_text" not in result.quality.warnings
    assert [p.enhancement for p in result.processing.passes] == [
        "original", "clahe", "ktp_recovery", "ktp_recovery_contrast"]
    assert result.data["nik"] == "9901011508901234"
    assert result.data["full_name"] == "NAMA CONTOH"
    assert result.data["address"] == "JL CONTOH NO 123"
    assert result.fields["nik"].candidates[0].supporting_passes == ["p3", "p4"]
    assert any(c.value == "990101150890123" for c in result.fields["nik"].candidates)
    retry = result.processing.passes[2]
    point = np.asarray(retry.to_input) @ np.array([0., 0., 1.])
    assert 0 <= point[0] / point[2] <= result.quality.width
    assert 0 <= point[1] / point[2] <= result.quality.height
    assert {s.pass_id for s in result.raw_ocr} == {"p1", "p2", "p3", "p4"}


@pytest.mark.parametrize("mode, enabled, calls", [("fast", True, 1), ("accurate", False, 2)])
def test_ktp_recovery_can_be_disabled_and_preserves_fast_mode(image_bytes, mode, enabled, calls):
    engine = IncompleteKTPEngine()
    result = OCRPipeline(engine, Settings(_env_file=None, ktp_recovery=enabled)).process(image_bytes, "ktp", mode)
    assert engine.calls == calls
    assert result.data["nik"] is None
    assert "nik_must_have_16_digits" in result.fields["nik"].reasons


def test_recovery_is_bounded_and_never_completes_a_missing_nik_digit(image_bytes):
    engine = IncompleteKTPEngine(recover=False)
    result = OCRPipeline(engine, Settings(_env_file=None)).process(image_bytes, "ktp")
    assert engine.calls == 4
    assert result.fields["nik"].candidate == "990101150890123"
    assert result.data["nik"] is None
    assert result.fields["full_name"].status == "missing"
    assert result.data["address"] is None


def test_recovery_preserves_conflicting_complete_niks(image_bytes):
    result = OCRPipeline(IncompleteKTPEngine(conflict=True), Settings(_env_file=None)).process(image_bytes, "ktp")
    assert result.data["nik"] is None
    assert "conflicting_readings" in result.fields["nik"].reasons


def test_context_at_the_recovery_crop_edge_does_not_replace_accepted_fields(image_bytes):
    class ClippedContextEngine(IncompleteKTPEngine):
        def recognize(self, image, pass_id):
            spans = super().recognize(image, pass_id)
            if self.calls > 2:
                for span in spans:
                    if span.text.startswith("PROVINSI"):
                        span.text = "PROVINSI CON TOH"
                    if span.text.startswith("RT/RW"):
                        span.text = "RT/RW : 003/004"
            return spans

    result = OCRPipeline(ClippedContextEngine(), Settings(_env_file=None)).process(image_bytes, "ktp")
    assert result.data["nik"] == "9901011508901234"
    assert result.data["province"] == "CONTOH"
    assert result.data["rt"] == "001"
    assert result.data["rw"] == "002"


def test_a_name_cut_off_by_the_recovery_crop_is_never_accepted(image_bytes):
    class ClippedNameEngine(IncompleteKTPEngine):
        def recognize(self, image, pass_id):
            spans = super().recognize(image, pass_id)
            if self.calls > 2:
                for span in spans:
                    if span.text.startswith("Nama"):
                        span.box[1][0] = span.box[2][0] = image.shape[1] - 1
            return spans

    result = OCRPipeline(ClippedNameEngine(), Settings(_env_file=None)).process(image_bytes, "ktp")
    assert result.fields["full_name"].candidate == "NAMA CONTOH"
    assert result.data["full_name"] is None
    assert "recovery_text_touches_crop_edge" in result.fields["full_name"].reasons


def test_labelled_name_recovery_is_not_blocked_by_the_layout_fallback(image_bytes):
    from test_ektp_layout import ektp

    class MissingLabelEngine(StubEngine):
        def recognize(self, image, pass_id):
            self.calls += 1
            return [s.model_copy(update={"pass_id": pass_id}) for s in ektp()
                    if self.calls > 2 or s.text != "Nama"]

    result = OCRPipeline(MissingLabelEngine(), Settings(_env_file=None)).process(image_bytes, "ktp")
    assert result.data["full_name"] == "BUDI SANTOSO"
    assert result.fields["full_name"].candidates[0].supporting_passes == ["p3", "p4"]


class SidewaysEngine(StubEngine):
    """A card turned by a quarter: the upright read finds only a phone-like number."""

    def recognize(self, image, pass_id):
        self.calls += 1
        if self.calls == 1:
            return [Span(text="0812 3456 7890", score=0.99, box=[[30, 30], [400, 30], [400, 60], [30, 60]],
                         pass_id=pass_id),
                    Span(text="HP: 0812 3456 7890", score=0.99, box=[[30, 90], [400, 90], [400, 120], [30, 120]],
                         pass_id=pass_id)]
        if self.calls == 3:  # the 270-degree probe
            return super().recognize(image, pass_id)
        return []


def test_a_ktp_that_reads_like_a_business_card_is_turned_before_giving_up(image_bytes):
    engine = SidewaysEngine()
    result = OCRPipeline(engine, Settings(_env_file=None)).process(image_bytes, "ktp")
    assert [p.enhancement for p in result.processing.passes][:3] == [
        "original", "orientation_probe", "orientation_probe"]
    assert result.processing.passes[2].rotation_clockwise == 270
    assert result.data["full_name"] == "NAMA CONTOH"
    # Fast mode turns it too, rather than answering with an error.
    result = OCRPipeline(SidewaysEngine(), Settings(_env_file=None)).process(image_bytes, "ktp", "fast")
    assert [p.enhancement for p in result.processing.passes] == [
        "original", "orientation_probe", "orientation_probe"]
    assert result.data["full_name"] == "NAMA CONTOH"


# A business card held over a desk, with another card lying under it at an angle.
HELD_CARD = [[200, 300], [1000, 280], [1010, 760], [190, 770]]
CARD_PRINT = [  # text, left and top as shares of the card, width as a share of it
    ("Rina Wijaya", 0.08, 0.12, 0.40),
    ("Account Manager", 0.08, 0.26, 0.34),
    ("PT Contoh Makmur", 0.08, 0.48, 0.38),
    ("rina.wijaya@contoh.co.id", 0.08, 0.60, 0.50),
    ("+62 812 3456 7890", 0.08, 0.72, 0.36),
    ("Jl. Melati No. 10, Jakarta 10110", 0.08, 0.84, 0.60),
]
BEHIND = [("Dewi Lestari", 60, 70), ("+62 811 1111 1111", 50, 110), ("dewi@lain.co.id", 40, 150)]


def held_card_image() -> np.ndarray:
    other = [[20, 20], [560, 220], [500, 400], [-40, 200]]
    return drawn_photo((other, (240, 242, 244)), (HELD_CARD, (240, 242, 244)), grain=4.0)


def held_card_photo() -> bytes:
    return cv2.imencode(".png", held_card_image())[1].tobytes()


def photo_print(pass_id: str) -> list[Span]:
    """What a read of the whole photograph finds: the card, and the card behind it."""
    card = [tilted_line(200 + 800 * left, 295 + 470 * top, 800 * wide, 34, -1.4, text, pass_id=pass_id)
            for text, left, top, wide in CARD_PRINT]
    return card + [tilted_line(x, y, 260, 26, 20.0, text, pass_id=pass_id) for text, x, y in BEHIND]


class HeldCardEngine(StubEngine):
    """Reads the photograph with the card behind, and the flattened view with the card alone.

    ``wide`` is a view that still shows both cards, as (height, width) and the matrix
    that maps the photograph onto it.
    """

    def __init__(self, view_reads=True, wide=None):
        super().__init__()
        self.view_reads = view_reads
        self.wide = wide
        self.shapes = []

    def recognize(self, image, pass_id):
        self.calls += 1
        height, width = image.shape[:2]
        self.shapes.append((height, width))
        if (height, width) == (900, 1200):
            return photo_print(pass_id)
        if self.wide is not None and (height, width) == self.wide[0]:
            spans = photo_print(pass_id)
            for span in spans:
                points = np.c_[np.asarray(span.box), np.ones(4)] @ self.wide[1].T
                span.box = (points[:, :2] / points[:, 2:]).tolist()
            return spans
        if not self.view_reads:
            return []
        card_w, card_h = width / 1.04, height / 1.04
        return [tilted_line(0.02 * card_w + card_w * left, 0.02 * card_h + card_h * top, card_w * wide,
                            0.07 * card_h, 0.0, text, pass_id=pass_id) for text, left, top, wide in CARD_PRINT]


@pytest.fixture
def held(monkeypatch):
    """A card whose silhouette cannot be found: held in a hand, among other things."""
    monkeypatch.setattr("card_ocr.pipeline.find_card", lambda image, max_side: None)


def test_a_held_business_card_is_read_from_its_own_flattened_view(held):
    engine = HeldCardEngine()
    result = OCRPipeline(engine, Settings(_env_file=None)).process(held_card_photo(), "business_card")
    passes = result.processing.passes
    assert [item.enhancement for item in passes] == ["original", "card", "clahe"]
    assert engine.shapes[0] == (900, 1200) and max(engine.shapes[1]) > 1500
    assert result.data["full_name"] == "Rina Wijaya"
    assert result.data["company"] == "PT Contoh Makmur"
    assert result.data["address"] == "Jl. Melati No. 10, Jakarta 10110"
    # The card behind was read by the first pass and is evidence for nothing.
    assert result.data["phones"] == ["+6281234567890"]
    assert [field.candidate for field in result.fields["emails"]] == ["rina.wijaya@contoh.co.id"]
    assert len(result.fields["full_name"].candidates) == 1
    assert result.status == "ok"
    # Evidence comes from the two reads of the view, and maps back onto the photograph.
    assert {e.pass_id for e in result.fields["full_name"].candidates[0].evidence} == {"p2", "p3"}
    edge = np.array([0.02 * passes[1].width / 1.04, 0.02 * passes[1].height / 1.04, 1.0])
    corner = np.asarray(passes[1].to_input) @ edge
    assert np.allclose(corner[:2] / corner[2], HELD_CARD[0], atol=10)


def test_fast_mode_keeps_its_one_read_and_drops_what_is_not_on_the_card(held):
    engine = HeldCardEngine()
    result = OCRPipeline(engine, Settings(_env_file=None)).process(
        held_card_photo(), "business_card", "fast", include_raw=True)
    assert engine.calls == 1
    assert result.data["full_name"] == "Rina Wijaya"
    assert result.data["phones"] == ["+6281234567890"]
    assert [field.candidate for field in result.fields["emails"]] == ["rina.wijaya@contoh.co.id"]
    # The read is reported in the levelled card frame, and still maps onto the photograph.
    name = next(span for span in result.raw_ocr if span.text == "Rina Wijaya")
    assert abs(name.box[0][1] - name.box[1][1]) < 2.0
    corner = np.asarray(result.processing.passes[0].to_input) @ np.array([*name.box[0], 1.0])
    assert np.allclose(corner[:2] / corner[2], [264, 351.4], atol=6)


def test_a_card_view_that_reads_nothing_falls_back_to_the_photograph(held):
    engine = HeldCardEngine(view_reads=False)
    result = OCRPipeline(engine, Settings(_env_file=None)).process(held_card_photo(), "business_card")
    passes = result.processing.passes
    assert [item.enhancement for item in passes] == ["original", "card", "deskew", "clahe"]
    assert (passes[3].height, passes[3].width) != (passes[1].height, passes[1].width)
    assert result.fields["full_name"].candidate == "Rina Wijaya"
    # Print turned against the card's own is still left out.
    assert [field.candidate for field in result.fields["phones"]] == ["+6281234567890"]


def test_the_card_outline_is_not_looked_for_when_card_detection_is_off():
    engine = HeldCardEngine()
    settings = Settings(_env_file=None, card_detection=False, deskew_retry=False)
    result = OCRPipeline(engine, settings).process(held_card_photo(), "business_card")
    assert [item.enhancement for item in result.processing.passes] == ["original", "clahe"]


def test_a_silhouette_view_that_took_in_the_card_behind_is_narrowed(monkeypatch):
    # The two white cards overlap: their common silhouette is one large light quadrilateral.
    region = np.float32([[0, 0], [1100, 0], [1100, 825], [0, 825]])
    matrix = cv2.getPerspectiveTransform(region, np.float32([[0, 0], [1600, 0], [1600, 1200], [0, 1200]]))
    wide = cv2.warpPerspective(held_card_image(), matrix, (1600, 1200))
    monkeypatch.setattr("card_ocr.pipeline.find_card", lambda image, max_side: (wide, matrix.astype(float)))
    engine = HeldCardEngine(wide=((1200, 1600), matrix.astype(float)))
    result = OCRPipeline(engine, Settings(_env_file=None)).process(held_card_photo(), "business_card")
    passes = result.processing.passes
    assert [item.enhancement for item in passes] == ["card", "card", "clahe"]
    assert (passes[1].height, passes[1].width) != (1200, 1600)
    assert result.data["full_name"] == "Rina Wijaya"
    assert result.data["phones"] == ["+6281234567890"]
    assert [field.candidate for field in result.fields["emails"]] == ["rina.wijaya@contoh.co.id"]
    edge = np.array([0.02 * passes[1].width / 1.04, 0.02 * passes[1].height / 1.04, 1.0])
    corner = np.asarray(passes[1].to_input) @ edge
    assert np.allclose(corner[:2] / corner[2], HELD_CARD[0], atol=10)


class TurnedCardEngine(StubEngine):
    """A card photographed sideways: the first read finds print running up the photograph."""

    LINES = ["Rina Wijaya", "Account Manager", "PT Contoh Makmur", "rina.wijaya@contoh.co.id", "+62 812 3456 7890"]

    def recognize(self, image, pass_id):
        self.calls += 1
        if self.calls == 1:
            return [Span(text=text, score=0.99, pass_id=pass_id, flipped=True,
                         box=[[x, 100], [x + 34, 100], [x + 34, 500], [x, 500]])
                    for x, text in zip(range(100, 600, 60), self.LINES, strict=False)]
        return [Span(text=text, score=0.99, pass_id=pass_id, flipped=False,
                     box=[[100, y], [500, y], [500, y + 34], [100, y + 34]])
                for y, text in zip(range(100, 600, 60), self.LINES, strict=False)]


@pytest.mark.parametrize("mode,reads", [("accurate", 3), ("fast", 2)])
def test_a_sideways_business_card_is_set_upright_and_read_again(image_bytes, mode, reads):
    engine = TurnedCardEngine()
    result = OCRPipeline(engine, Settings(_env_file=None)).process(image_bytes, "business_card", mode)
    assert engine.calls == reads
    passes = result.processing.passes
    assert [(item.enhancement, item.rotation_clockwise) for item in passes][:2] == [("original", 0), ("original", 90)]
    assert (passes[1].width, passes[1].height) == (passes[0].height, passes[0].width)
    assert result.data["full_name"] == "Rina Wijaya"
    assert result.data["job_title"] == "Account Manager"


def test_a_requested_ktp_is_not_turned_by_the_line_classifier(image_bytes):
    class Flipped(StubEngine):
        def recognize(self, image, pass_id):
            return [span.model_copy(update={"flipped": True}) for span in super().recognize(image, pass_id)]

    result = OCRPipeline(Flipped(), Settings(_env_file=None)).process(image_bytes, "ktp")
    assert [(item.enhancement, item.rotation_clockwise) for item in result.processing.passes] == [
        ("original", 0), ("clahe", 0)]


def test_mobile_numbers_are_listed_on_their_own(image_bytes):
    lines = ["Name: EXAMPLE PERSON", "Company: EXAMPLE CO", "T: (021) 2345 6789",
             "F: (021) 2345 6780", "M: 0812 3456 7890"]
    result = OCRPipeline(StubEngine(lines), Settings(_env_file=None)).process(image_bytes, "business_card")
    assert result.data["phones"] == ["+622123456789", "+622123456780", "+6281234567890"]
    assert result.data["mobile_phones"] == ["+6281234567890"]
    assert [field.phone_type for field in result.fields["phones"]] == ["landline", "fax", "mobile"]
    # A KTP has no telephone numbers, and no such list.
    result = OCRPipeline(StubEngine(), Settings(_env_file=None)).process(image_bytes, "ktp")
    assert "mobile_phones" not in result.data
    assert result.fields["nik"].phone_type is None


def test_a_trading_name_is_reported_beside_the_legal_company_name(image_bytes):
    lines = ["Name: EXAMPLE PERSON", "CONTOH-NET INDONESIA", "PT. EXAMPLE GROUP", "person@contoh-net.co.id"]
    result = OCRPipeline(StubEngine(lines), Settings(_env_file=None)).process(image_bytes, "business_card")
    assert result.data["company"] == "PT. EXAMPLE GROUP"
    assert result.data["company_alias"] == "CONTOH-NET INDONESIA"
    assert result.fields["company_alias"].assignment == "contact"
    # A card with one company name has the field, empty, and is not sent to review for it.
    lines = ["Name: EXAMPLE PERSON", "PT. EXAMPLE GROUP", "person@example.co.id", "M: 0812 3456 7890"]
    result = OCRPipeline(StubEngine(lines), Settings(_env_file=None)).process(image_bytes, "business_card")
    assert result.data["company_alias"] is None
    assert result.fields["company_alias"].status == "missing"
    assert not any(reason.startswith("company_alias") for reason in result.review_reasons)
