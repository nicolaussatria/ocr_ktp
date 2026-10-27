import pytest
from conftest import KTP_LINES, make_spans

from card_ocr.parsers import business, ktp
from card_ocr.parsers.common import Observation, resolve
from card_ocr.schemas import FieldResult, Span


def test_complete_ktp_and_same_row_fields():
    result = ktp.parse(make_spans(KTP_LINES))
    assert result.anchors >= 12
    for key, expected in {
        "nik": "9901011508901234",
        "gender": "LAKI-LAKI",
        "blood_type": "O",
        "birth_date": "1990-08-15",
        "rt": "001",
        "rw": "002",
        "province": "CONTOH",
        "address": "JL CONTOH NO 123",
    }.items():
        assert result.fields[key][0].value == expected


def test_geometry_reassembles_label_and_value_in_shuffled_order():
    spans = [
        Span(text="NAMA CONTOH", score=0.99, box=[[300, 50], [800, 50], [800, 80], [300, 80]]),
        Span(text="Nama :", score=0.99, box=[[20, 50], [150, 50], [150, 80], [20, 80]]),
    ]
    assert ktp.parse(spans).fields["full_name"][0].value == "NAMA CONTOH"


@pytest.mark.parametrize(
    "nik,issue",
    [
        ("99010115089O1234", "character_substitution_requires_review"),
        ("990101150890123", "nik_must_have_16_digits"),
        ("9901013102901234", "invalid_nik_birth_component"),
        ("9901014008901234", "invalid_nik_birth_component"),
        ("0000001508901234", "suspicious_nik_structure"),
    ],
)
def test_suspicious_nik_never_silently_accepted(nik, issue):
    _, issues = ktp.normalize_nik(nik)
    assert issue in issues


def test_female_date_encoding_valid():
    value, issues = ktp.normalize_nik("9901015508901234")
    assert value == "9901015508901234"
    assert issues == []


def test_two_pass_consensus_does_not_boost_score():
    observations = [
        Observation("VALUE", make_spans(["VALUE"], p, score)) for p, score in [("p1", 0.99), ("p2", 0.95)]
    ]
    result = resolve(observations, 0.93, True)
    assert result.status == "accepted"
    assert result.ocr_score == 0.95


def test_same_pass_duplicates_are_not_consensus():
    item = Observation("VALUE", make_spans(["VALUE"]))
    result = resolve([item, item], 0.93, True)
    assert result.value is None
    assert "second_read_required" in result.reasons


def test_conflicting_high_scores_require_review():
    result = resolve(
        [
            Observation("9901011508901234", make_spans(["A"], "p1")),
            Observation("9901011508901235", make_spans(["B"], "p2")),
        ],
        0.98,
        True,
    )
    assert result.status == "review"
    assert result.value is None
    assert len(result.candidates) == 2


def test_invalid_calendar_date_preserved_without_invention():
    parsed = ktp.parse(make_spans(["Tempat/Tgl Lahir : KOTA, 31-02-1990"]))
    assert parsed.fields["birth_date"][0].value == "31-02-1990"
    assert "invalid_calendar_date" in parsed.fields["birth_date"][0].issues


def test_name_not_corrected_from_zero_to_letter():
    parsed = ktp.parse(make_spans(["Nama : BUD1 SANT0SO"]))
    assert parsed.fields["full_name"][0].value == "BUD1 SANT0SO"
    assert parsed.fields["full_name"][0].issues


def accepted(value):
    return FieldResult(value=value, candidate=value, status="accepted", ocr_score=0.999)


@pytest.mark.parametrize(
    "birth,gender,issue",
    [
        ("1990-08-16", "LAKI-LAKI", "nik_birth_date_mismatch"),
        ("1990-08-15", "PEREMPUAN", "nik_gender_mismatch"),
    ],
)
def test_nik_cross_check_downgrades_conflicts(birth, gender, issue):
    fields = {"nik": accepted("9901011508901234"), "birth_date": accepted(birth), "gender": accepted(gender)}
    ktp.cross_validate(fields)
    assert fields["nik"].value is None
    assert issue in fields["nik"].reasons


def test_missing_birth_date_is_not_reconstructed_from_nik():
    fields = {
        "nik": accepted("9901011508901234"),
        "birth_date": FieldResult(),
        "gender": accepted("LAKI-LAKI"),
    }
    ktp.cross_validate(fields)
    assert fields["birth_date"].candidate is None
    assert fields["nik"].value is None


def test_business_multiple_contacts_and_no_domain_fabrication():
    parsed = business.parse(
        make_spans(
            [
                "NAMA CONTOH",
                "PT CONTOH TEKNOLOGI",
                "Sales Manager",
                "info@example.com",
                "other@example.org",
                "+62 812-3456-7890",
                "www.example.com",
            ]
        )
    )
    assert [o.value for o in parsed.fields["emails"]] == ["info@example.com", "other@example.org"]
    assert [o.value for o in parsed.fields["phones"]] == ["+6281234567890"]
    assert [o.value for o in parsed.fields["websites"]] == ["https://www.example.com"]
    assert "unlabeled_name_requires_review" in parsed.fields["full_name"][0].issues


def test_explicit_name_label_supported():
    result = business.parse(make_spans(["Name: NAMA CONTOH", "Company: CONTOH GROUP"]))
    assert result.fields["full_name"][0].issues == []
    assert result.fields["company"][0].value == "CONTOH GROUP"


def test_malformed_email_candidate_is_retained():
    result = business.parse(make_spans(["Email: info @ example com"]))
    assert result.fields["emails"][0].issues == ["unparsed_email_requires_review"]


def test_email_trailing_digit_cannot_be_silently_truncated():
    result = business.parse(make_spans(["info@example.com1"]))
    assert result.fields["emails"][0].value == "info@example.com1"
    assert result.fields["emails"][0].issues


def test_bare_domain_requires_review_to_avoid_degree_name_false_positive():
    result = business.parse(make_spans(["S.Kom"]))
    assert result.fields["websites"][0].issues == ["bare_domain_requires_review"]


def test_explicit_website_label_is_kept():
    result = business.parse(make_spans(["Website: example.com"]))
    assert result.fields["websites"][0].value == "https://example.com"
    assert result.fields["websites"][0].issues == []


def test_website_with_unsupported_port_is_not_truncated():
    result = business.parse(make_spans(["https://example.com:8443/path"]))
    assert result.fields["websites"][0].value == "https://example.com:8443/path"
    assert result.fields["websites"][0].issues


def boxed(items, pass_id="p1"):
    """Spans with explicit geometry: (text, x, y, width, score)."""
    return [
        Span(
            text=text,
            score=score,
            box=[[x, y], [x + width, y], [x + width, y + 30], [x, y + 30]],
            pass_id=pass_id,
        )
        for text, x, y, width, score in items
    ]


def test_photo_column_does_not_contaminate_the_field_value():
    # "KOTA BEKASI" under the photo shares a baseline with the Agama row.
    parsed = ktp.parse(boxed([("Agama", 29, 870, 82, 0.99), (":KATHOLIK", 252, 866, 127, 0.95),
                              ("KOTABEKASI", 721, 865, 145, 0.99)]))
    assert parsed.fields["religion"][0].value == "KATHOLIK"


def test_label_and_value_split_by_a_wide_gap_stay_together():
    parsed = ktp.parse(boxed([("Nama", 26, 628, 72, 0.99), (":ANDREAS SURYA", 245, 623, 289, 0.97)]))
    assert parsed.fields["full_name"][0].value == "ANDREAS SURYA"


def test_same_row_gender_and_blood_type_survive_column_splitting():
    parsed = ktp.parse(boxed([("Jenis kelamin", 29, 708, 142, 0.99), ("LAKI-LAKI", 254, 702, 116, 0.99),
                              ("Gol. Darah : O", 465, 695, 180, 0.99)]))
    assert parsed.fields["gender"][0].value == "LAKI-LAKI"
    assert parsed.fields["blood_type"][0].value == "O"


def test_wrapped_name_line_is_appended():
    parsed = ktp.parse(boxed([("Nama", 26, 628, 72, 0.99), (":ANDREAS SURYA", 245, 623, 289, 0.97),
                              ("PRATAMA", 254, 646, 120, 0.99)]))
    assert parsed.fields["full_name"][0].value == "ANDREAS SURYA PRATAMA"


def test_misread_label_row_is_never_appended_to_the_name():
    # "Tempat/TgILahir" with a capital I would fail a stricter label match; a row holding
    # digits must not be swallowed by the name above it.
    parsed = ktp.parse(boxed([("Nama", 26, 628, 72, 0.99), (":NAMA CONTOH", 245, 623, 289, 0.97),
                              ("XXXX : BANDUNG, 15-08-1990", 245, 660, 300, 0.99)]))
    assert parsed.fields["full_name"][0].value == "NAMA CONTOH"


def test_labels_survive_dropped_spaces_and_l_read_as_capital_i():
    parsed = ktp.parse(make_spans([
        "PROVINSIJAWABARAT",
        "KOTABEKASI",
        "Tempat/TgILahir : BANDUNG, 15-08-1990",
        "RTRW : 001/018",
        "Status Perkawinan : BELUMKAWIN",
        "Berlaku Hingga : SEUMURHIDUP",
    ]))
    assert parsed.fields["province"][0].value == "JAWABARAT"
    assert parsed.fields["city"][0].value == "BEKASI"
    assert parsed.fields["birth_date"][0].value == "1990-08-15"
    assert parsed.fields["rt"][0].value == "001"
    assert parsed.fields["marital_status"][0].value == "BELUM KAWIN"
    assert parsed.fields["marital_status"][0].issues == []
    assert parsed.fields["valid_until"][0].value == "SEUMUR HIDUP"
    assert parsed.fields["valid_until"][0].issues == []


def test_spacing_only_difference_between_passes_counts_as_agreement():
    result = resolve(
        [
            Observation("ANDREAS SURYA", make_spans(["A"], "p1", 0.97)),
            Observation("ANDREASSURYA", make_spans(["B"], "p2", 0.99)),
        ],
        0.93,
        True,
    )
    assert result.status == "accepted"
    assert result.value == "ANDREAS SURYA"  # the form that kept the word break
    assert result.ocr_score == 0.97


def test_invalid_reading_never_outranks_a_valid_one_on_score():
    result = resolve(
        [
            Observation("LAKI-LAKI", make_spans(["A"], "p1", 0.91)),
            Observation("LAKHLAKI", make_spans(["B"], "p2", 0.96), ["unrecognized_gender"]),
        ],
        0.90,
        False,
    )
    assert result.candidate == "LAKI-LAKI"
    assert result.status == "accepted"


def test_sub_threshold_reading_does_not_veto_a_good_one():
    result = resolve(
        [
            Observation("MUSTIKAJAYA", make_spans(["A"], "p1", 0.99)),
            Observation("MUAAYA", make_spans(["B"], "p2", 0.85)),
        ],
        0.93,
        False,
    )
    assert result.status == "accepted"
    assert "conflicting_readings" not in result.reasons


def test_two_valid_readings_above_threshold_still_conflict():
    result = resolve(
        [
            Observation("LAKI-LAKI", make_spans(["A"], "p1", 0.99)),
            Observation("PEREMPUAN", make_spans(["B"], "p2", 0.99)),
        ],
        0.93,
        False,
    )
    assert result.status == "review"
    assert "conflicting_readings" in result.reasons


def test_single_pass_acceptance_never_applies_to_nik():
    single = [Observation("9901011508901234", make_spans(["A"], "p1", 0.999))]
    assert resolve(single, 0.98, True, single_pass_threshold=None).status == "review"
    assert resolve(single, 0.98, True, single_pass_threshold=0.99).status == "accepted"


def test_label_score_does_not_gate_the_value_score():
    spans = boxed([("RTRW", 82, 784, 86, 0.76), ("001/018", 259, 780, 82, 0.99)])
    observation = ktp.parse(spans).fields["rt"][0]
    assert observation.score == pytest.approx(0.99)


def test_nik_accepted_when_printed_fields_agree_but_are_themselves_under_review():
    fields = {
        "nik": accepted("9901011508901234"),
        "birth_date": FieldResult(candidate="1990-08-15", status="review", reasons=["low_ocr_score"]),
        "gender": FieldResult(candidate="LAKI-LAKI", status="review", reasons=["low_ocr_score"]),
    }
    ktp.cross_validate(fields)
    assert fields["nik"].value == "9901011508901234"
    ktp.cross_validate(fields, strict=True)
    assert fields["nik"].value is None


def address_block(*lines, closing: str | None = "RT/RW : 001/018", pass_id="p1"):
    """An Alamat row, its wrapped lines, and whatever row follows the block."""
    spans = boxed([("Alamat", 28, 100, 82, 0.99), (":JL.MELATI RAYA CEMPAKA", 165, 100, 330, 0.98)],
                  pass_id=pass_id)
    y = 130
    for line in lines:
        spans += boxed([(line, 171, y, 152, 0.98)], pass_id=pass_id)
        y += 30
    if closing:
        spans += boxed([(closing, 54, y, 200, 0.99)], pass_id=pass_id)
    return spans


def test_wrapped_address_closed_by_a_label_row_is_not_flagged():
    # Between Alamat and the next label there is no other field the wrapped line could
    # belong to, so its extent is settled by the layout rather than guessed.
    observation = ktp.parse(address_block("KENANGA VII/18")).fields["address"][0]
    assert observation.value == "JL.MELATI RAYA CEMPAKA KENANGA VII/18"
    assert observation.issues == []


def test_wrapped_address_with_nothing_below_it_stays_flagged():
    observation = ktp.parse(address_block("KENANGA VII/18", closing=None)).fields["address"][0]
    assert observation.issues == ["multiline_address_requires_review"]


def test_address_wrapping_over_two_lines_stays_flagged():
    parsed = ktp.parse(address_block("KENANGA VII/18", "BLOK C NOMOR 7"))
    assert parsed.fields["address"][0].issues == ["multiline_address_requires_review"]


def test_wrapped_address_accepted_when_both_passes_agree():
    observations = []
    for pass_id in ("p1", "p2"):
        observations += ktp.parse(address_block("KENANGA VII/18", pass_id=pass_id)).fields["address"]
    result = resolve(observations, 0.93, consensus=True, single_pass_threshold=0.99)
    assert result.value == "JL.MELATI RAYA CEMPAKA KENANGA VII/18"


def test_photo_column_splits_off_a_row_holding_only_label_and_caption():
    # "Status Perkawinan; KAWIN" is one box, and the city printed under the photo shares
    # its baseline. The row has two boxes, so the row's own gaps cannot settle it.
    parsed = ktp.parse(boxed([("Status Perkawinan; KAWIN", 17, 310, 221, 0.97),
                              ("KOTABANJARMASIN", 533, 304, 156, 0.96)]))
    assert parsed.fields["marital_status"][0].value == "KAWIN"


def test_ordinary_label_and_value_gap_never_splits():
    parsed = ktp.parse(boxed([("Nama", 26, 628, 72, 0.99), (":DEWI LESTARI", 245, 623, 289, 0.97)]))
    assert parsed.fields["full_name"][0].value == "DEWI LESTARI"


def test_third_address_line_is_assembled_not_dropped():
    parsed = ktp.parse(address_block("KENANGA VII/18", "BLOK C NOMOR 7"))
    assert parsed.fields["address"][0].value.endswith("KENANGA VII/18 BLOK C NOMOR 7")


def test_documented_label_lookalikes_do_not_lose_a_field():
    # "Berlaky" is the recogniser reading the u of "Berlaku" as y; "N1K"/"WN1" are the
    # documented I/1 confusion. The value is taken from the untouched text.
    parsed = ktp.parse(make_spans([
        "N1K : 9901011508901234",
        "Berlaky Hingga : SEUMUR HIDUP",
        "Kewarganegaraan : WN1",
    ]))
    assert parsed.fields["nik"][0].value == "9901011508901234"
    assert parsed.fields["valid_until"][0].value == "SEUMUR HIDUP"
    assert parsed.fields["valid_until"][0].issues == []
    assert parsed.fields["nationality"][0].value == "WNI"
    assert parsed.fields["nationality"][0].issues == []


def test_printed_categories_fold_documented_lookalikes():
    parsed = ktp.parse(make_spans([
        "Jenis Kelamin : LAK1-LAK1   Gol. Darah : 0",
        "Status Perkawinan : BELUMKAW1N",
    ]))
    assert parsed.fields["gender"][0].value == "LAKI-LAKI"
    assert parsed.fields["gender"][0].issues == []
    assert parsed.fields["blood_type"][0].value == "O"
    assert parsed.fields["marital_status"][0].value == "BELUM KAWIN"
    assert parsed.fields["marital_status"][0].issues == []


def test_undocumented_gender_misread_stays_unrecognized():
    parsed = ktp.parse(make_spans(["Jenis Kelamin : LAKHLAKI"]))
    assert parsed.fields["gender"][0].issues == ["unrecognized_gender"]


def test_ktp_street_prefix_is_written_out_but_other_text_is_not_folded():
    parsed = ktp.parse(make_spans(["Alamat : JI. MERDEKA NO. 45", "Nama : BUD1 SANT0SO"]))
    assert parsed.fields["address"][0].value == "JL. MERDEKA NO. 45"
    assert parsed.fields["address"][0].issues == []
    assert parsed.fields["full_name"][0].value == "BUD1 SANT0SO"
    assert "suspicious_name_characters" in parsed.fields["full_name"][0].issues


def test_labeled_address_gets_the_same_street_canonicalization():
    parsed = business.parse(make_spans(["Alamat : JI. Raya Bogor No. 88, Depok"]))
    assert parsed.fields["address"][0].value == "Jl. Raya Bogor No. 88, Depok"
    assert parsed.fields["address"][0].issues == []


def test_indonesian_phone_labels_are_understood():
    parsed = business.parse(make_spans(["Telepon : 0856 7890 1234", "HP : 0812 3456 7890",
                                        "No. Telp : 021 555 0987"]))
    assert [o.value for o in parsed.fields["phones"]] == ["+6285678901234", "+6281234567890",
                                                          "+62215550987"]
    assert all(o.issues == [] for o in parsed.fields["phones"])
