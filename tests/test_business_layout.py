"""Regression fixtures use synthetic text, independent of the submitted card photos."""
import numpy as np
import pytest
from conftest import IsolatedSettings, StubEngine, listed, make_spans
from fastapi.testclient import TestClient

from card_ocr.api import create_app
from card_ocr.imaging import rotate, rotation_matrix, text_focus
from card_ocr.parsers import business
from card_ocr.parsers.common import Observation
from card_ocr.pipeline import OCRPipeline
from card_ocr.schemas import Span


def span(text, x, y, width=250, height=30, score=0.999, pid="p1"):
    return Span(text=text, score=score, box=[[x, y], [x + width, y],
                [x + width, y + height], [x, y + height]], pass_id=pid)


def finish(spans, field, region="ID"):
    observations = []
    for pid in ("p1", "p2"):
        read = [s.model_copy(update={"pass_id": pid}) for s in spans]
        observations.extend(business.parse(read, region).fields.get(field, []))
    return business.resolve_field(observations, 0.93, True)


def test_company_co_and_indonesian_job_are_not_person_candidates():
    items = [span("Contoh Co", 100, 30), span("Lestari Wijaya", 700, 100, 500, 70),
             span("Agen Real Estate", 730, 185, 400, 40), span("hello@example.com", 750, 300)]
    assert finish(items, "company").value == "Contoh Co"
    assert finish(items, "full_name").value == "Lestari Wijaya"
    assert finish(items, "full_name").assignment == "layout"
    assert finish(items, "job_title").value == "Agen Real Estate"
    assert len(finish(items, "full_name").candidates) == 1


def test_contacts_do_not_swallow_company_in_another_column():
    parsed = business.parse([span("HP:0812 3456 7890", 30, 100),
                             span("PT. Contoh Makmur", 700, 100)])
    assert parsed.fields["company"][0].value == "PT. Contoh Makmur"
    assert parsed.fields["phones"][0].value == "+6281234567890"


def test_large_logo_does_not_merge_small_text_on_different_rows():
    parsed = business.parse([span("EXAMPLE", 800, 100, 400, 130),
                             span("PT. Contoh Makmur", 300, 140, 250, 15),
                             span("Authorized Vehicle Dealer", 300, 158, 250, 15),
                             span("Sales, Service, Spare Parts.", 300, 176, 250, 15)])
    assert parsed.fields["company"][0].value == "PT. Contoh Makmur"
    assert not parsed.fields.get("job_title")


def test_two_people_do_not_become_one_accepted_identity():
    items = [span("Nama Pertama", 30, 50, 250, 45), span("Sales Manager", 30, 105),
             span("Nama Kedua", 700, 50, 250, 45), span("Engineering Manager", 700, 105)]
    result = finish(items, "full_name")
    assert result.status == "review"
    assert "multiple_person_blocks" in result.reasons
    assert {c.value for c in result.candidates} == {"Nama Pertama", "Nama Kedua"}


def test_street_and_postcode_are_not_telephone_numbers():
    parsed = business.parse([span("50 Example St., Example City, NJ 08060", 30, 50),
                             span("Jakarta Barat 11620, Indonesia", 30, 90)])
    assert not parsed.fields.get("phones")
    assert parsed.fields["address"][0].value.endswith("Jakarta Barat 11620, Indonesia")


def test_wrapped_address_stops_at_contacts_and_skips_other_columns():
    parsed = business.parse([span(": Jl. Contoh Raya,", 30, 50),
                             span("OTHER LOGO", 850, 85),
                             span("Kota Contoh, Indonesia", 40, 85),
                             span("+62 812 3456 7890", 30, 125)])
    assert parsed.fields["address"][0].value == "Jl. Contoh Raya, Kota Contoh, Indonesia"
    assert len(parsed.fields["phones"]) == 1


def test_phone_extension_is_not_lost():
    parsed = business.parse([span("031 7654321 ex 123", 30, 50)])
    assert parsed.fields["phones"][0].value == "+62317654321;ext=123"


def test_second_landline_number_shares_the_printed_area_code():
    # "(0251)" is printed once for both numbers of the same exchange.
    parsed = business.parse([span("Telp: (0251) 8345678, 8345679", 30, 50)])
    assert [o.value for o in parsed.fields["phones"]] == ["+622518345678", "+622518345679"]
    assert not parsed.fields["phones"][1].issues
    # OCR_SHARED_AREA_CODE=false keeps the short number as printed, for review.
    parsed = business.parse([span("Telp: (0251) 8345678, 8345679", 30, 50)], shared_area_code=False)
    assert [o.value for o in parsed.fields["phones"]] == ["+622518345678", "8345679"]
    assert parsed.fields["phones"][1].issues == ["phone_country_or_area_code_required"]


def test_shared_area_code_setting_reaches_the_parser(image_bytes):
    lines = ["Name: EXAMPLE PERSON", "Company: EXAMPLE CO", "Telp: (0251) 8345678, 8345679"]
    result = OCRPipeline(StubEngine(lines), IsolatedSettings()).process(image_bytes, "business_card")
    assert result.data["phones"] == ["+622518345678", "+622518345679"]
    settings = IsolatedSettings(shared_area_code=False)
    result = OCRPipeline(StubEngine(lines), settings).process(image_bytes, "business_card")
    assert result.data["phones"] == ["+622518345678"]
    assert [field.candidate for field in listed(result, "phones")] == ["+622518345678", "8345679"]


def test_foreign_national_numbers_not_silently_made_indonesian():
    items = [span("(423) 220-0983 | (423) 945-1611", 30, 50)]
    parsed = business.parse(items)
    assert all(o.issues for o in parsed.fields["phones"])
    assert all(not o.value.startswith("+62") for o in parsed.fields["phones"])
    parsed_us = business.parse(items, "US")
    assert [o.value for o in parsed_us.fields["phones"]] == ["+14232200983", "+14239451611"]
    assert all(not o.issues for o in parsed_us.fields["phones"])


def test_invalid_unlabeled_placeholder_is_retained_as_printed():
    parsed = business.parse([span("123-456-7890", 30, 50)])
    assert parsed.fields["phones"][0].value == "123-456-7890"
    assert parsed.fields["phones"][0].issues


def test_phone_ocr_substitution_is_not_repaired_or_truncated():
    parsed = business.parse([span("+62812345O6789", 30, 50)])
    assert parsed.fields["phones"][0].value == "+62812345O6789"
    assert parsed.fields["phones"][0].issues == ["unparsed_phone_requires_review"]


def test_social_handle_does_not_become_malformed_email():
    parsed = business.parse([span("@contoh_agen", 30, 50), span("hello@example.com", 30, 100)])
    assert [o.value for o in parsed.fields["social_handles"]] == ["@contoh_agen"]
    assert [o.value for o in parsed.fields["emails"]] == ["hello@example.com"]


def test_honorific_and_dotted_sentence_are_not_website_candidates():
    parsed = business.parse([span("MR.JOHN DOE", 30, 50),
                             span("lorem ipsum dolor sit amet.consectetur", 30, 100)])
    assert not parsed.fields.get("websites")


def test_company_template_is_not_person_and_is_not_verified():
    parsed = business.parse([span("COMPANY NAME", 30, 50)])
    assert not parsed.fields.get("full_name")
    assert finish([span("COMPANY NAME", 30, 50)], "company").status == "review"


def test_brand_logo_remains_review_without_explicit_company_role():
    items = [span("EXAMPLIA", 30, 30), span("NAMA CONTOH", 30, 160, 500, 50),
             span("REAL ESTATE AGENT", 30, 225)]
    assert finish(items, "full_name").value == "NAMA CONTOH"
    assert finish(items, "company").candidate == "EXAMPLIA"
    assert finish(items, "company").status == "review"


def test_email_punctuation_differences_are_not_agreement():
    observations = [Observation(value, make_spans([value], pid)) for pid, value in
                    [("p1", "a.b@example.com"), ("p2", "ab@example.com")]]
    result = business.resolve_field(observations, .93, True)
    assert result.value is None
    assert "conflicting_readings" in result.reasons


def test_same_pass_duplicates_do_not_supply_two_readings():
    item = Observation("VALUE", make_spans(["VALUE"]))
    assert business.resolve_field([item, item], .93, True).value is None


def test_two_clear_rereads_can_recover_one_weak_read_but_not_a_strong_conflict():
    values = [("p1", "WRONG", .8), ("p2", "CORRECT", .96), ("p3", "CORRECT", .98)]
    items = [Observation(v, make_spans([v], pid, score)) for pid, v, score in values]
    result = business.resolve_field(items, .93, True)
    assert result.value == "CORRECT"
    assert result.ocr_score == .96
    assert set(result.candidates[0].supporting_passes) == {"p2", "p3"}
    items.append(Observation("OTHER", make_spans(["OTHER"], "p4", .99)))
    assert business.resolve_field(items, .93, True).value is None


def test_crop_coordinates_keep_conflicting_contact_in_same_result():
    a = span("a.b@example.com", 100, 50, pid="p1")
    b = span("ab@example.com", 200, 100, 500, 60, pid="p2")
    fields = business.resolve_contacts([Observation(a.text, [a]), Observation(b.text, [b])], .93, True,
                                       {"p1": np.eye(3), "p2": np.diag([.5, .5, 1])})
    assert len(fields) == 1
    assert len(fields[0].candidates) == 2
    assert fields[0].value is None


@pytest.mark.parametrize("degrees", [0, 90, 180, 270])
def test_rotation_matrix_matches_actual_pixels(degrees):
    source = np.arange(35).reshape(5, 7)
    rotated = rotate(source, degrees)
    matrix = rotation_matrix(7, 5, degrees)
    for x, y in [(0, 0), (2, 3), (6, 4)]:
        mapped = matrix @ [x, y, 1]
        assert rotated[int(mapped[1]), int(mapped[0])] == source[y, x]


def test_crop_transform_and_output_are_bounded():
    source = np.full((600, 800, 3), 255, dtype=np.uint8)
    box = span("HELLO", 200, 150, 250, 20)
    result = text_focus(source, [box], IsolatedSettings(), contrast=False)
    assert result is not None
    frame, forward = result
    assert max(frame.shape[:2]) <= 2000
    mapped = forward @ [200, 150, 1]
    assert 0 < mapped[0] < frame.shape[1]
    assert 0 < mapped[1] < frame.shape[0]
    assert np.allclose(np.linalg.inv(forward) @ mapped, [200, 150, 1])


@pytest.mark.parametrize("region,expected", [(None, []), ("US", ["+14232200983"])])
def test_rest_phone_region_contract(image_bytes, region, expected):
    engine = StubEngine(["Name: EXAMPLE PERSON", "Company: EXAMPLE CO", "(423) 220-0983"])
    with TestClient(create_app(IsolatedSettings(), engine)) as client:
        data = {} if region is None else {"phone_region": region}
        result = client.post("/v1/ocr/business_card", files={"file": ("card.png", image_bytes)}, data=data)
    assert result.status_code == 200
    assert result.json()["data"]["phones"] == expected
    assert result.json()["processing"]["phone_region"] == (region or "ID")


def test_unknown_phone_region_rejected_before_ocr(image_bytes):
    engine = StubEngine()
    with TestClient(create_app(IsolatedSettings(), engine)) as client:
        result = client.post("/v1/ocr/business_card", files={"file": ("card.png", image_bytes)},
                             data={"phone_region": "XX"})
    assert result.status_code == 422
    assert result.json()["error"]["code"] == "INVALID_PHONE_REGION"
    assert engine.calls == 0


def test_small_print_retries_are_bounded_and_fast_mode_skips_them(image_bytes):
    class TinyEngine(StubEngine):
        def recognize(self, image, pass_id):
            self.calls += 1
            return [span("Name: EXAMPLE PERSON", 100, 100, 300, 16, pid=pass_id),
                    span("Company: EXAMPLE CO", 100, 140, 300, 16, pid=pass_id),
                    span("hello@example.com", 100, 180, 300, 16, pid=pass_id)]
    engine = TinyEngine()
    pipeline = OCRPipeline(engine, IsolatedSettings())
    result = pipeline.process(image_bytes, "business_card")
    assert engine.calls == 4
    assert len(result.processing.passes) == 4
    assert "small_text" in result.quality.warnings
    pipeline.process(image_bytes, "business_card", "fast")
    assert engine.calls == 5
    engine = TinyEngine()
    OCRPipeline(engine, IsolatedSettings(business_retry=False)).process(image_bytes, "business_card")
    assert engine.calls == 2


def test_street_prefix_read_as_capital_i_is_written_out():
    # "JI." is the recogniser reading the l of "Jl." as I; the abbreviation is fixed.
    assert business._canonical_street("JI. Raya Ciawi Km.8, Bogor") == ("Jl. Raya Ciawi Km.8, Bogor", [])
    assert business._canonical_street("J1.Raya Ciawi") == ("Jl.Raya Ciawi", [])
    assert business._canonical_street("JI. MELATI RAYA VIII") == ("JL. MELATI RAYA VIII", [])


def test_correct_street_prefix_is_left_exactly_as_printed():
    for printed in ("Jl. Kebon Agung Gede", "JL.MELATI RAYA", "Jalan Merdeka 10"):
        assert business._canonical_street(printed) == (printed, [])


def test_a_guessed_street_prefix_is_still_flagged():
    # "H." is not a known misreading of "Jl.", so it stays a guess.
    assert business._canonical_street("H. Meruya Ilir Raya No.10A")[1] == ["uncertain_street_prefix"]


def test_outvoted_one_character_misread_does_not_block_the_majority():
    items = [Observation(v, make_spans([v], pid, score)) for pid, v, score in [
        ("p1", "Jl. Raya Ciawi Km.8, Bogor, Jawa Barat, 16720", .98),
        ("p2", "Jl. Raya Ciawi Km.8, Bogor, Jawa Barat, 16720", .98),
        ("p3", "Jl. Raya Ciawi Km.8, Bogor, Jawa Barat, 16720", .98),
        ("p4", "Jl. Raya Ciawi Km.8, Bogoc, Jawa Barat, 16720", .96)]]
    result = business.resolve_field(items, .93, True)
    assert result.value == "Jl. Raya Ciawi Km.8, Bogor, Jawa Barat, 16720"
    assert "conflicting_readings" not in result.reasons


def test_an_equally_backed_misread_still_blocks():
    items = [Observation(v, make_spans([v], pid, .98)) for pid, v in [
        ("p1", "Jl. Melati 10"), ("p2", "Jl. Melati 10"),
        ("p3", "Jl. Melati 16"), ("p4", "Jl. Melati 16")]]
    assert business.resolve_field(items, .93, True).value is None


def test_business_address_accepted_end_to_end():
    spans = [span("Jl. Kebon Agung Gede, Karanganyar, Jakarta Pusat", 200, 400, 600, 30)]
    assert finish(spans, "address").value == "Jl. Kebon Agung Gede, Karanganyar, Jakarta Pusat"


def test_readings_that_differ_only_in_word_breaks_agree():
    items = [Observation(v, make_spans([v], pid, .98)) for pid, v in [
        ("p1", "Jl. Melati No.12, Jakarta"), ("p2", "Jl. Melati No. 12, Jakarta")]]
    result = business.resolve_field(items, .93, True, spacing_insensitive=True)
    assert result.value == "Jl. Melati No. 12, Jakarta"
    # Punctuation still has to match, and exact agreement stays the default.
    rivals = [Observation("Jl. Melati No 12, Jakarta", make_spans(["x"], pid, .98)) for pid in ("p3", "p4")]
    assert business.resolve_field(items + rivals, .93, True, spacing_insensitive=True).value is None
    assert business.resolve_field(items, .93, True).value is None


def test_street_prefix_glued_to_the_street_name_is_an_address():
    parsed = business.parse([span("JI.Gatot Subroto Kav. 36, Jakarta", 30, 100, 600)])
    assert parsed.fields["address"][0].value == "Jl.Gatot Subroto Kav. 36, Jakarta"
    # An email or a domain that happens to start the same way is still a contact.
    parsed = business.parse([span("ji.andreas@gmail.com", 30, 100, 600), span("jl.co.id", 30, 200, 600)])
    assert "address" not in parsed.fields
    assert parsed.fields["emails"][0].value == "ji.andreas@gmail.com"


def test_only_non_contact_lines_are_respaced():
    for contact in ("rizky.pratama@arthamandiri.co.id", "www.arthamandiri.co.id", "arthamandiri.co.id",
                    "0813-2468-1357", "T. +62 22 8765 4321", "@arthamandiri"):
        assert business.contact_text(contact), contact
    for other in ("MarketingManager", "DEWILESTARI", "Jabatan : MarketingManager",
                  "Jl. Melati No.12, Jakarta", "JI.Gatot Subroto Kav. 36, Jakarta"):
        assert not business.contact_text(other), other


class RecordingPipeline(OCRPipeline):
    def _respace(self, image, spans):
        self.respaced = [span.text for span in spans]


def test_business_respacing_never_touches_contact_lines(image_bytes):
    engine = StubEngine(["DEWILESTARI", "Direktur Operasional", "dewi.lestari@example.com",
                         "0812-3456-7890", "Jl. Melati No.12, Jakarta"])
    pipeline = RecordingPipeline(engine, IsolatedSettings())
    pipeline.process(image_bytes, "business_card", "fast")
    assert pipeline.respaced == ["DEWILESTARI", "Direktur Operasional", "Jl. Melati No.12, Jakarta"]
