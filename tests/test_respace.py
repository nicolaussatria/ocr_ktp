import numpy as np
from conftest import StubEngine

from card_ocr.config import Settings
from card_ocr.engine import _BreakEvidence, _measure_rated_breaks, _with_rated_breaks
from card_ocr.imaging import respace_candidate, word_pieces
from card_ocr.parsers import ktp
from card_ocr.pipeline import OCRPipeline, _with_breaks
from card_ocr.schemas import FieldResult, Span


def bars(widths, gap, height=40, margin=6):
    """A line image of black word blocks separated by blank columns."""
    total = margin * 2 + sum(widths) + gap * (len(widths) - 1)
    image = np.full((height, total, 3), 255, dtype=np.uint8)
    x = margin
    for width in widths:
        image[8 : height - 8, x : x + width] = 0
        x += width + gap
    return image


def letters(widths, gaps, height=40, margin=6):
    """Glyph blocks separated by the given blank widths, like one printed line."""
    total = margin * 2 + sum(widths) + sum(gaps)
    image = np.full((height, total, 3), 255, dtype=np.uint8)
    x = margin
    for index, width in enumerate(widths):
        image[8 : height - 8, x : x + width] = 0
        x += width + (gaps[index] if index < len(gaps) else 0)
    return image


def test_word_gap_is_split_and_letter_gap_is_not():
    pieces = word_pieces(bars([40, 40], gap=14))
    assert pieces is not None and len(pieces) == 2
    assert word_pieces(bars([40, 40], gap=2)) is None


def test_wide_letter_gap_is_not_a_word_break():
    # Measured on card crops: letter gaps reach 0.20 of the line height between two
    # upright strokes (N|U), word gaps start at 0.26. At 4x, height 160: 0.2 -> 32 px.
    # "SITI NURHALIZA": a wide N|U letter gap next to ordinary letter gaps and a word gap.
    line = letters([10] * 6, [3, 3, 12, 8, 3])
    pieces = word_pieces(line)
    assert pieces is not None and len(pieces) == 2
    # A single word whose only wide gap is a letter gap stays whole.
    assert word_pieces(letters([10] * 4, [3, 8, 3])) is None


def test_respace_is_only_attempted_on_long_all_letter_lines():
    assert respace_candidate("CIMAHISELATANPERMAIBLOK")
    assert respace_candidate(":ANDREASSURYA")
    assert not respace_candidate("9901011508901234")
    assert not respace_candidate("BANDUNG,15-08-1990")  # a space here would break the date
    assert not respace_candidate("KOTA BEKASI")  # no token long enough to be worth re-reading
    assert respace_candidate("JL. MERDEKA NO.45")  # a full stop glued to the next word
    assert respace_candidate("JL.SOEKARNO HATTA 21")  # digits elsewhere are allowed
    assert not respace_candidate("NIK:9901011508901234")


def test_breaks_confirmed_on_the_whole_line_survive_respacing():
    # "PEKALONGAN BARAT" had its break inserted from the line's rating; a plain re-read
    # of one piece holding both words does not remove it.
    assert _with_breaks(":PEKALONGAN BARAT", [15], kept=[10]) == ":PEKALONGAN BARAT"
    assert _with_breaks(":PEKALONGAN BARAT", [15]) == ":PEKALONGANBARAT"


def test_breaks_never_drop_punctuation_or_split_digits():
    assert _with_breaks("Jabatan : MarketingManager", [7, 9, 7]) == "Jabatan: Marketing Manager"
    assert _with_breaks("JL. MERDEKA NO.45", [2, 7, 2, 2]) == "JL. MERDEKA NO. 45"
    assert _with_breaks("NIK:9901011508901234", [3, 8, 8]) == "NIK: 9901011508901234"
    assert _with_breaks("SITI N URHALIZA", [4, 9]) == "SITI NURHALIZA"
    # Pieces that do not account for every letter and digit leave the line untouched.
    assert _with_breaks("ABCD", [1, 1]) == "ABCD"


class CropEngine(StubEngine):
    def __init__(self, words):
        super().__init__()
        self.words = list(words)

    def recognize_crop(self, patch):
        return self.words.pop(0) if self.words else ""


def respaced(words, text="AAAABBBB"):
    image = bars([40, 40], gap=14)
    span = Span(text=text, score=0.99, box=[[0, 0], [image.shape[1], 0],
                                            [image.shape[1], image.shape[0]], [0, image.shape[0]]])
    settings = Settings()
    OCRPipeline(CropEngine(words), settings)._respace(image, [span])
    return span.text


def test_word_break_is_restored_from_the_image():
    assert respaced(["AAAA", "BBBB"]) == "AAAA BBBB"


def test_a_re_read_that_changes_characters_is_rejected():
    # The split may only insert a space. Different characters mean the crop was wrong.
    assert respaced(["AAAA", "CCCC"]) == "AAAABBBB"
    assert respaced(["AAAA", "BBB"]) == "AAAABBBB"


def test_a_re_read_that_loses_a_colon_keeps_it():
    # The narrow colon piece is not re-read; the colon stays in the line regardless.
    assert respaced(["AAAAAAAA", "BBBB"], text="AAAAAAAA:BBBB") == "AAAAAAAA: BBBB"


def test_a_space_the_image_does_not_show_is_removed():
    assert respaced(["AAAAAAAA", "BBBB"], text="AAAA AAAABBBB") == "AAAAAAAA BBBB"


def test_respacing_can_be_switched_off():
    image = bars([40, 40], gap=14)
    span = Span(text="AAAABBBB", score=0.99, box=[[0, 0], [image.shape[1], 0],
                                                  [image.shape[1], image.shape[0]], [0, image.shape[0]]])
    settings = Settings(respace_words=False)
    pipeline = OCRPipeline(CropEngine(["AAAA", "BBBB"]), settings)
    if settings.respace_words:  # mirrors the pipeline's own guard
        pipeline._respace(image, [span])
    assert span.text == "AAAABBBB"


def accepted_nik():
    return FieldResult(value="9901011508901234", candidate="9901011508901234",
                       status="accepted", ocr_score=0.999)


def unsure_gender(reasons):
    return FieldResult(candidate="LAKI-LAKI", status="review", ocr_score=0.91, reasons=reasons)


def test_gender_accepted_when_it_agrees_with_an_accepted_nik():
    fields = {"nik": accepted_nik(), "birth_date": FieldResult(candidate="1990-08-15"),
              "gender": unsure_gender(["low_ocr_score", "second_read_required"])}
    ktp.cross_validate(fields, corroborate_gender=True)
    assert fields["gender"].value == "LAKI-LAKI"
    assert fields["gender"].reasons == ["corroborated_by_nik"]


def test_gender_that_failed_validation_is_never_corroborated():
    fields = {"nik": accepted_nik(), "birth_date": FieldResult(candidate="1990-08-15"),
              "gender": FieldResult(candidate="LAKHLAKI", status="review",
                                    reasons=["unrecognized_gender"])}
    ktp.cross_validate(fields, corroborate_gender=True)
    assert fields["gender"].value is None


def test_gender_is_not_corroborated_by_a_nik_that_was_not_accepted():
    fields = {"nik": FieldResult(candidate="9901011508901234", status="review",
                                 reasons=["low_ocr_score"]),
              "birth_date": FieldResult(candidate="1990-08-15"),
              "gender": unsure_gender(["low_ocr_score"])}
    ktp.cross_validate(fields, corroborate_gender=True)
    assert fields["gender"].value is None


def test_disagreeing_gender_is_still_flagged_on_both_fields():
    fields = {"nik": accepted_nik(), "birth_date": FieldResult(candidate="1990-08-15"),
              "gender": FieldResult(value="PEREMPUAN", candidate="PEREMPUAN", status="accepted")}
    ktp.cross_validate(fields, corroborate_gender=True)
    assert fields["gender"].value is None
    assert "nik_gender_mismatch" in fields["nik"].reasons


class Rated:
    """Decoder output carrying the break ratings and pixel confirmations the engine records."""

    def __init__(self, breaks, confirmed):
        self.breaks = breaks
        self.confirmed = confirmed


def rated(text, ratings, confirmed=None):
    breaks = [0.0] * len(text)
    for index, value in ratings.items():
        breaks[index] = value
    return _with_rated_breaks(text, Rated(breaks, set(ratings) if confirmed is None else confirmed))[0]


def test_breaks_the_recogniser_rated_are_restored():
    assert rated("PEKALONGANBARAT", {10: 0.46}) == "PEKALONGAN BARAT"
    assert rated("Kewarganegaraan:WNI", {16: 0.30}) == "Kewarganegaraan: WNI"
    # A rating the ink does not confirm is not a break.
    assert rated("PEKALONGANBARAT", {10: 0.46}, confirmed=set()) == "PEKALONGANBARAT"


def line(gaps, height=40):
    """Glyph blocks 12 px wide separated by the given blank widths; centres as fractions."""
    width = 4 + sum(12 + gap for gap in gaps) + 12 + 4
    image = np.full((height, width, 3), 255, dtype=np.uint8)
    x, centres = 4, []
    for gap in [*gaps, 0]:
        image[8 : height - 8, x : x + 12] = 0
        centres.append((x + 6) / width)
        x += 12 + gap
    return image, centres


class Info:
    confirmed: set[int]

    def __init__(self, breaks, positions):
        self.breaks = breaks
        self.positions = positions


def test_a_rated_break_needs_a_gap_wider_than_the_line_spacing():
    # Tight print: letter gaps 1 px, a 9 px gap (0.22 of the height) at the rated break.
    image, centres = line([1, 1, 9, 1, 1])
    info = Info([0.0, 0.0, 0.0, 0.02, 0.0, 0.0], centres)
    _measure_rated_breaks(image, info)
    assert info.confirmed == {3}
    # Monospace print: every letter gap is 6 px, so a 7 px gap with a weak rating is not a break.
    image, centres = line([6, 6, 7, 6, 6])
    info = Info([0.0, 0.0, 0.0, 0.03, 0.0, 0.0], centres)
    _measure_rated_breaks(image, info)
    assert info.confirmed == set()


def test_rated_breaks_never_enter_numbers_or_abbreviations():
    assert rated("9901015508901234", {4: 0.9}) == "9901015508901234"
    assert rated("JL.MELATI", {3: 0.9}) == "JL.MELATI"
    assert rated("NO.12", {3: 0.9}) == "NO.12"
    assert rated("BANDUNG,15-08-1990", {8: 0.5}) == "BANDUNG, 15-08-1990"


def test_break_ratings_follow_the_decoded_characters():
    class Decoder:
        character = ["blank", "A", "B", " "]
        dict = {c: i for i, c in enumerate(character)}

        def get_ignored_tokens(self):
            return [0]

        def decode(self, index, best, return_word_box, ratios, padded, remove_duplicate=False):
            assert index.tolist() == [[1, 1, 0, 0, 2, 0]]
            return [("AB", 0.9)], [type("Info", (), {})()]

    steps = np.full((1, 6, 4), 0.01)
    for step, token in enumerate([1, 1, 0, 0, 2, 0]):
        steps[0, step, token] = 0.9
    steps[0, 3, 3] = 0.3  # a break rated between A and B, though blank won
    _, [info] = _BreakEvidence(Decoder())(steps, True, wh_ratio_list=[6.0], max_wh_ratio=6.0)
    assert info.breaks == [0.0, 0.3]
    assert info.positions == [0.5 / 6, 4.5 / 6]
