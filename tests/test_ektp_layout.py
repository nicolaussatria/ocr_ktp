"""e-KTP geometry: aligned colon column, separate label and value boxes, photo block.

Box positions follow the measured reads of an e-KTP-like synthetic sheet at 1600 px:
labels at x=35-80, values at x=416-425, the photo block's place and date at x=1292.
"""

from card_ocr.parsers import ktp
from card_ocr.parsers.common import Observation, normalize_text, resolve
from card_ocr.schemas import Span


def box(text, x, y, right, height=33, score=0.999, pid="p1"):
    return Span(text=text, score=score, pass_id=pid,
                box=[[x, y], [right, y], [right, y + height], [x, y + height]])


def ektp(*, name="BUDI SANTOSO", address=("JL. SOEKARNO HATTA KOMPLEK GRIYA",), extra=()):
    spans = [
        box("PROVINSI JAWA BARAT", 544, 33, 1055, 39),
        box("KOTA BANDUNG", 618, 87, 982, 42),
        box("NIK", 34, 159, 115, 44),
        box(":9901021508900003", 399, 161, 906, 39),
        box("Nama", 34, 240, 127, 35),
        box(name, 416, 241, 662, 32),
        box("Tempat/Tgl Lahir", 38, 293, 275, 32),
        box(":BANDUNG,15-08-1990", 399, 293, 758, 30),
        box("Jenis Kelamin", 37, 341, 236),
        box("LAKI-LAKI", 417, 342, 571, 31),
        box("Gol. Darah : O", 796, 340, 1012, 36),
        box("Alamat", 35, 391, 143, 34),
        box(address[0], 424, 393, 1018, 29),
    ]
    top = 441
    for line in address[1:]:
        spans.append(box(line, 422, top + 2, 774, 29))
        top += 50
    spans += [
        box("RT/RW", 75, top, 185, 35),
        box("004/007", 417, top, 540, 35),
        box("Kel/Desa", 75, top + 50, 210, 34),
        box("CIPAGANTI", 419, top + 50, 593),
        box("Agama", 34, top + 100, 142, 38),
        box(": ISLAM", 402, top + 101, 523, 34),
    ]
    return spans + list(extra)


def values(spans):
    return {key: [item.value for item in items] for key, items in ktp.parse(spans).fields.items()}


def test_short_labels_keep_values_printed_across_the_colon_column():
    # "Nama" and "Alamat" sit ~9 glyph heights from their values, farther than the old
    # isolated-gap limit, so both values used to be dropped as a separate column.
    fields = values(ektp())
    assert fields["nik"] == ["9901021508900003"]
    assert fields["full_name"] == ["BUDI SANTOSO"]
    assert fields["address"] == ["JL. SOEKARNO HATTA KOMPLEK GRIYA"]
    assert fields["birth_place"] == ["BANDUNG"]
    assert fields["gender"] == ["LAKI-LAKI"]
    assert fields["blood_type"] == ["O"]
    assert fields["religion"] == ["ISLAM"]
    assert fields["rt"] == ["004"] and fields["rw"] == ["007"]


def test_wrapped_address_is_the_whole_block_not_its_second_line():
    parsed = ktp.parse(ektp(address=("JL. SOEKARNO HATTA KOMPLEK GRIYA", "PERMAI BLOK C NO. 21")))
    [address] = parsed.fields["address"]
    assert address.value == "JL. SOEKARNO HATTA KOMPLEK GRIYA PERMAI BLOK C NO. 21"
    assert "label_on_previous_row" not in address.issues
    assert "multiline_address_requires_review" not in address.issues


def test_value_starting_with_a_label_word_stays_with_its_label():
    spans = [s for s in ektp() if s.text != "CIPAGANTI"] + [box("DESA SUKAMAJU", 419, 491, 700)]
    assert values(spans)["village"] == ["DESA SUKAMAJU"]


def test_photo_block_text_is_never_a_label_value():
    # The recogniser missed the religion value; the issuing place under the photo shares
    # the row below. It must not become the religion, even as a review candidate.
    spans = [s for s in ektp() if s.text != ": ISLAM"]
    spans += [box("BANDUNG", 1292, 579, 1434, 29), box("12-05-2017", 1294, 620, 1437, 31)]
    fields = values(spans)
    assert "religion" not in fields
    assert "BANDUNG" not in fields.get("occupation", [])


def test_photo_block_splits_off_a_label_value_row_with_an_equally_wide_gap():
    # Label gap and photo gap are both ~280 px: the label gap no longer masks the photo gap.
    spans = [s for s in ektp() if s.text != ": ISLAM"]
    spans += [box("KATHOLIK", 416, 541, 700), box("BANDUNG", 980, 541, 1120)]
    assert values(spans)["religion"] == ["KATHOLIK"]


def test_label_with_a_separate_colon_box_is_rejoined():
    spans = [s for s in ektp() if s.text != "BUDI SANTOSO"]
    spans += [box(":", 400, 241, 408, 32), box("BUDI SANTOSO", 425, 241, 662, 32)]
    assert values(spans)["full_name"] == ["BUDI SANTOSO"]


def test_missing_name_label_keeps_a_review_candidate_between_nik_and_birth():
    for label in (None, "Narna"):
        spans = [s for s in ektp() if s.text != "Nama"]
        if label:
            spans.append(box(label, 34, 240, 127, 35))
        [name] = ktp.parse(spans).fields["full_name"]
        assert name.value == "BUDI SANTOSO"
        assert name.issues == ["unlabeled_name_requires_review"]
        assert resolve([name], 0.93, False, single_pass_threshold=0.99).value is None


def test_missing_name_does_not_borrow_a_photo_caption_or_another_field():
    spans = [s for s in ektp() if s.text not in {"Nama", "BUDI SANTOSO"}]
    for candidate in (box("BANDUNG", 1292, 241, 1434), box("15-08-1990", 416, 241, 650),
                      box("Agama ISLAM", 416, 241, 650)):
        assert "full_name" not in ktp.parse(spans + [candidate]).fields


def test_missing_name_label_requires_both_neighbouring_labels_and_one_row():
    spans = [s for s in ektp() if s.text != "Nama"]
    for omitted in ("NIK", "Tempat/Tgl Lahir"):
        assert "full_name" not in ktp.parse([s for s in spans if s.text != omitted]).fields
    spans.append(box("EXTRA LINE", 416, 211, 650, height=15))
    assert "full_name" not in ktp.parse(spans).fields


def test_recovery_block_keeps_a_missing_field_and_wrapped_address_in_context():
    spans = [s for s in ektp(address=("JL. SOEKARNO HATTA", "BLOK C NO. 21")) if s.text != "Nama"]
    identity = ktp.recovery_spans(spans, {"full_name", "nik"})
    assert {"NIK", "BUDI SANTOSO", "Tempat/Tgl Lahir"} <= {s.text for s in identity}
    address = ktp.recovery_spans(spans, {"address", "village"})
    assert {"Alamat", "BLOK C NO. 21", "RT/RW", "Kel/Desa"} <= {s.text for s in address}


def test_fullwidth_marks_from_the_recogniser_never_reach_a_value():
    assert normalize_text("：BANDUNG，15－08－1990") == ":BANDUNG,15-08-1990"
    assert normalize_text("９９０１") == "9901"
    assert normalize_text("LAKI–LAKI") == "LAKI-LAKI"
    spans = [
        box("NIK", 34, 159, 115, 44), box("：９９０１０２１５０８９００００３", 399, 161, 906, 39),
        box("Tempat/Tgl Lahir", 38, 293, 275, 32), box("：BANDUNG,15-08-1990", 399, 293, 758, 30),
        box("Jenis Kelamin", 37, 341, 236), box("LAKI–LAKI", 417, 342, 571, 31),
        box("Gol. Darah：O", 796, 340, 1012, 36),
        box("Berlaku Hingga", 36, 791, 290), box("：SEUMUR HIDUP", 400, 791, 665, 30),
    ]
    fields = ktp.parse(spans).fields
    assert fields["nik"][0].value == "9901021508900003"
    assert fields["nik"][0].issues == []  # a fullwidth digit is the same digit, not a substitution
    assert fields["birth_place"][0].value == "BANDUNG"
    assert fields["gender"][0].value == "LAKI-LAKI"
    assert fields["blood_type"][0].value == "O"
    assert fields["valid_until"][0].value == "SEUMUR HIDUP"
    for key in ("birth_place", "blood_type", "valid_until"):
        assert fields[key][0].issues == []


def test_raw_boxes_keep_the_recogniser_code_points():
    span = box("：BANDUNG,15-08-1990", 399, 293, 758, 30)
    ktp.parse([box("Tempat/Tgl Lahir", 38, 293, 275, 32), span])
    assert span.text.startswith("：")


def read(value, pid, score):
    return Observation(value, [box(value, 400, 160, 900, 39, score, pid)])


def test_a_weaker_agreeing_pass_does_not_lower_the_field_score():
    result = resolve([read("9901021508900003", "p1", 0.99), read("9901021508900003", "p2", 0.985),
                      read("9901021508900003", "p3", 0.95)], 0.98, True, single_pass_threshold=None)
    assert result.status == "accepted"
    assert result.ocr_score == 0.985
    assert result.candidates[0].supporting_passes == ["p1", "p2"]


def test_two_strong_passes_are_still_required_and_rivals_still_block():
    weak = resolve([read("9901021508900003", "p1", 0.99), read("9901021508900003", "p2", 0.95)],
                   0.98, True, single_pass_threshold=None)
    assert weak.status == "review" and "low_ocr_score" in weak.reasons
    rival = resolve([read("9901021508900003", "p1", 0.99), read("9901021508900003", "p2", 0.99),
                     read("9901021508900008", "p3", 0.99)], 0.98, True, single_pass_threshold=None)
    assert rival.status == "review" and "conflicting_readings" in rival.reasons


def test_value_is_scored_on_its_printed_characters():
    # The recogniser doubts the colon (0.61), not the value; the line mean hides that.
    value = box(":BANDUNG,15-08-1990", 399, 293, 758, 30, score=0.975)
    value = value.model_copy(update={"content_score": 0.996})
    assert Observation("BANDUNG", [value]).score == 0.996
    # A lone colon box is not part of the value, and without character scores the
    # recogniser's line score is used as before.
    colon = box(":", 400, 241, 408, 32, score=0.6)
    assert Observation("BUDI", [colon, box("BUDI", 425, 241, 662, 32, score=0.97)]).score == 0.97


def test_nik_is_scored_by_its_weakest_digit():
    # Mean 0.985 over the line, but one digit read at 0.76: that is the doubt that matters.
    nik = box(":9901022103850007", 399, 161, 906, 39, score=0.985)
    nik = nik.model_copy(update={"content_score": 0.985, "digit_score": 0.764})
    parsed = ktp.parse([box("NIK", 34, 159, 115, 44), nik])
    assert parsed.fields["nik"][0].score == 0.764
    assert Observation("x", [nik]).score == 0.985  # other fields keep the content score


def test_internal_scores_never_reach_the_response():
    span = box("WNI", 400, 700, 470).model_copy(update={"content_score": 0.99, "digit_score": None})
    assert set(span.model_dump()) == {"text", "score", "box", "pass_id"}


def test_accented_misreads_fold_on_a_ktp_only():
    assert normalize_text("RATNA DEWÍ", fold_accents=True) == "RATNA DEWI"
    assert normalize_text("José", fold_accents=False) == "José"
    spans = [s for s in ektp() if s.text != "BUDI SANTOSO"] + [box("BUDÍ SANTOSO", 416, 241, 662, 32)]
    assert values(spans)["full_name"] == ["BUDI SANTOSO"]


def test_a_box_between_two_rows_does_not_merge_them():
    # Photographed card with rows 20 px apart: the issuing place under the photo sits
    # between "Status Perkawinan" and "Pekerjaan" and used to bridge them into one row.
    spans = [
        box("Agama", 46, 490, 110, 26), box(": ISLAM", 204, 493, 260, 21),
        box("Status Perkawinan: KAWIN", 45, 508, 284, 30),
        box("KOTA PEKALONGAN", 535, 523, 700, 26),
        box("Pekerjaan", 44, 527, 140, 29), box(":WIRASWASTA", 199, 529, 349, 29),
        box("Kewarganegaraan: WNI", 43, 548, 258, 30),
    ]
    fields = values(spans)
    assert fields["occupation"] == ["WIRASWASTA"]
    assert fields["marital_status"] == ["KAWIN"]


def test_a_misread_birth_label_is_still_recognised_by_lahir():
    for label in ("TempaV T gI Lahir", "Tempat T gi Lahir"):
        spans = [box(label, 20, 240, 200, 33), box("SAMARINDA, 08-10-1991", 221, 242, 520, 30),
                 box("Nama", 22, 200, 80, 29), box("HARIYANTO OKNES", 230, 200, 480, 27)]
        fields = values(spans)
        assert fields["birth_place"] == ["SAMARINDA"], label
        assert fields["birth_date"] == ["1991-10-08"], label


def test_a_single_strong_read_outranks_two_weak_ones():
    strong = read("BLOK A-1/NO.33", "p1", 0.96)
    weak = [read("BLOK A1ON/3", pid, score) for pid, score in (("p2", 0.70), ("p3", 0.55))]
    result = resolve([strong, *weak], 0.93, True, single_pass_threshold=None)
    assert result.candidate == "BLOK A-1/NO.33"
    assert result.status == "review" and "second_read_required" in result.reasons


def test_readings_that_differ_in_punctuation_are_not_settled():
    one = read("JL. KH.MAS MANSYUR NO.5A", "p1", 0.99)
    other = read("JL.KH.MAS MANSYUR NO 5A", "p2", 0.999)
    result = resolve([one, other], 0.93, True, single_pass_threshold=0.99)
    # The form that kept its full stop is proposed; neither form is confirmed twice.
    assert result.candidate == "JL. KH.MAS MANSYUR NO.5A"
    assert result.value is None and "punctuation_differs" in result.reasons
    # Spacing alone is not a punctuation difference, and a form read twice is settled.
    spaced = resolve([one, read("JL. KH.MAS MANSYUR NO.5A", "p2", 0.99)], 0.93, True)
    assert spaced.value == "JL. KH.MAS MANSYUR NO.5A"
    outvoted = resolve([one, read("JL. KH.MAS MANSYUR NO.5A", "p2", 0.99),
                        read("JL.KH.MAS MANSYUR NO 5A", "p3", 0.99)], 0.93, True)
    assert outvoted.value == "JL. KH.MAS MANSYUR NO.5A"


def test_a_block_code_read_as_the_digit_one_stays_in_review():
    fields = {key: resolve([read(value, pid, 0.99) for pid in ("p1", "p2")], 0.93, True)
              for key, value in (("address", "BEKASI TIMUR BLOK 1-1/NO.33"),)}
    ktp.review_lookalikes(fields)
    assert fields["address"].value is None
    assert "ambiguous_block_character" in fields["address"].reasons
    for printed in ("BLOK I-1/NO.33", "BLOK A-1/5", "ANGGREK VIII/42", "JL. MERDEKA NO.1/2"):
        fields = {"address": resolve([read(printed, pid, 0.99) for pid in ("p1", "p2")], 0.93, True)}
        ktp.review_lookalikes(fields)
        assert fields["address"].value == printed, printed
