"""Layout cases met on Indonesian business cards, rebuilt with made-up names and contacts.

These exercise parser geometry and role assignment, not recognition accuracy on the
photographed cards. No name, address, number or domain here belongs to a real card.
"""

import pytest

from card_ocr.parsers import business
from card_ocr.schemas import Span


def line(text, x=40, y=40, width=360, height=24, pid="p1", score=.999):
    return Span(text=text, score=score, pass_id=pid,
                box=[[x, y], [x + width, y], [x + width, y + height], [x, y + height]])


def resolved(items, key, **options):
    observations = []
    for pid in ("p1", "p2"):
        observations.extend(business.parse([
            item.model_copy(update={"pass_id": pid}) for item in items
        ], **options).fields.get(key, []))
    return business.resolve_field(observations, .93, True)


def contacts(items, key):
    return [(item.value, item.issues) for item in business.parse(items).fields.get(key, [])]


@pytest.mark.parametrize("label", ["M", "P", "T", "F", "Ph.", "Tel", "Mobile", "WA", "No. HP"])
def test_phone_labels_without_colons(label):
    parsed = business.parse([line(f"{label} +62 812 3456 7890")])
    assert [item.value for item in parsed.fields["phones"]] == ["+6281234567890"]
    assert not parsed.fields["phones"][0].issues


def test_printed_country_code_in_parentheses():
    parsed = business.parse([line("Ph.(62-21) 2345 6789")])
    assert parsed.fields["phones"][0].value == "+622123456789"
    assert not parsed.fields["phones"][0].issues


def test_second_number_after_a_slash_shares_the_printed_area_code():
    # "+62 21" is printed once for both subscriber numbers.
    assert contacts([line("P: +62 21 2345 6789/2345 6780")], "phones") == [
        ("+622123456789", []), ("+622123456780", [])]
    assert contacts([line("+6221 234 5678, 234 5679")], "phones") == [("+62212345678", []), ("+62212345679", [])]
    # Switched off, the short number stays as printed and under review.
    parsed = business.parse([line("P: +62 21 2345 6789/2345 6780")], shared_area_code=False)
    assert [item.value for item in parsed.fields["phones"]] == ["+622123456789", "2345 6780"]
    assert parsed.fields["phones"][1].issues == ["phone_country_or_area_code_required"]


@pytest.mark.parametrize("printed,second", [
    # One digit short of the first subscriber number: not the same kind of number.
    ("P: +62 21 2345 6789/234 5678", ("234 5678", ["phone_country_or_area_code_required"])),
    # A mobile number has no area code to share.
    ("M: +62 812 3456 7890/3456 7891", ("3456 7891", ["phone_country_or_area_code_required"])),
    # A number printed with its own prefix is itself.
    ("P: +62 21 2345 6789/0812 3456 7890", ("+6281234567890", [])),
])
def test_a_second_number_is_completed_only_when_it_fits_the_first(printed, second):
    assert contacts([line(printed)], "phones")[1] == second


def test_phone_label_split_into_its_own_box_is_not_a_person():
    parsed = business.parse([line("M", width=15), line("+62 812 3456 7890", x=70)])
    assert parsed.fields["phones"][0].value == "+6281234567890"
    assert len(parsed.fields["phones"][0].spans) == 2
    assert not parsed.fields.get("full_name")


def test_pictogram_read_as_a_glyph_is_not_part_of_the_number():
    # A handset drawn in front of the number comes back as a CJK character.
    assert contacts([line("白:+62-899.1234.567")], "phones") == [("+628991234567", [])]
    assert business.parse([line("PT CONTOH MAKMUR 回")]).fields["company"][0].value == "PT CONTOH MAKMUR"
    # Print that really is in that script is left alone.
    assert business._without_icon("陈伟明") == "陈伟明"


@pytest.mark.parametrize("name_parts,title", [
    (["Bambang", "Irawan"], "Regional Sales Manager"),
    (["Rina Kartika", "Wijaya"], "Account Executive"),
    (["SUKMAWATI S"], "Account Manager"),
    (["Dharmawan C. G."], "Account Manager"),
])
def test_name_above_title_including_wrapped_names(name_parts, title):
    items = [line(text, y=40 + index * 34, height=30) for index, text in enumerate(name_parts)]
    items.append(line(title, y=40 + len(name_parts) * 34, height=20))
    assert resolved(items, "full_name").value == " ".join(name_parts)
    assert resolved(items, "job_title").value == title


def test_wrapped_title_does_not_become_a_second_name():
    items = [line("BUDI TEJO SANTOSO", y=40, height=30),
             line("SENIOR INFORMATION TECHNOLOGY", y=80, height=20),
             line("MANAGER", y=105, height=20)]
    assert resolved(items, "full_name").value == "BUDI TEJO SANTOSO"
    assert resolved(items, "job_title").value == "SENIOR INFORMATION TECHNOLOGY MANAGER"


def test_multiple_job_lines_form_one_title():
    items = [line("Dewi Lestari", height=32), line("Sales & Marketing", y=80, height=20),
             line("Manager", y=104, height=20)]
    assert resolved(items, "full_name").value == "Dewi Lestari"
    assert resolved(items, "job_title").value == "Sales & Marketing Manager"


@pytest.mark.parametrize("title", ["Senior Solutions Consultant", "Customer Service Officer",
                                   "GM of Commercial", "VP Engineering", "Head of Sales", "Staff Administrasi"])
def test_a_role_is_a_role_whatever_it_sells(title):
    # "Solutions" and "Service" also describe what a company offers; with a role beside
    # them the line is the person's. "GM" and "VP" are roles only in capitals.
    items = [line("Dewi Lestari", height=32), line(title, y=80, height=20)]
    assert resolved(items, "job_title").value == title
    assert resolved(items, "full_name").value == "Dewi Lestari"


@pytest.mark.parametrize("offer", ["IT SERVICES AND SOFTWARE SOLUTIONS", "CONSULTING SERVICES",
                                   "Authorized Sales Agent", "Digital Transformation Solutions",
                                   "TRUSTED IT PARTNER", "Consultants & Advisors", "the gm visit"])
def test_what_a_company_offers_is_not_a_role(offer):
    assert "job_title" not in business.parse([line("Dewi Lestari", height=32), line(offer, y=200)]).fields


def test_office_heading_and_services_are_not_job_titles_or_names():
    items = [line("Rina Wijaya", y=30, height=32), line("Account Manager", y=70, height=20),
             line("Sales & Marketing Office", y=150), line("Jl. Melati No. 29", y=180),
             line("Jakarta 13470", y=210), line("Indonesia", y=240),
             line("BUSINESS INTELLIGENT", x=650, y=70),
             line("FINANCIAL & CONSULTATION", x=650, y=100)]
    assert resolved(items, "full_name").value == "Rina Wijaya"
    assert resolved(items, "job_title").value == "Account Manager"
    assert resolved(items, "address").value == "Jl. Melati No. 29 Jakarta 13470 Indonesia"


def test_building_floor_street_and_locality_form_one_address():
    items = [line("PT CONTOH INDONESIA", y=20), line("GRAHA CONTOH @Melati City", y=60),
             line("15th Floor Suite 1503-05", y=90), line("Jl. Jend. A. Contoh Kav. 28", y=120),
             line("Jakarta Barat 11470 - Indonesia", y=150),
             line("T +62 21 2345 6789", y=180)]
    address = resolved(items, "address")
    assert address.value == ("GRAHA CONTOH @Melati City 15th Floor Suite 1503-05 "
                             "Jl. Jend. A. Contoh Kav. 28 Jakarta Barat 11470 - Indonesia")
    assert len(address.candidates) == 1
    assert not business.parse(items).fields.get("emails")


def test_head_office_with_building_and_plain_locality_lines():
    items = [line("Head Office", y=20), line("Taman Contoh Indah", y=50),
             line("Blok A17 No. 29-30", y=80), line("Jl. Melati Raya Outer Ring Road", y=110),
             line("Kebon Jeruk, Jakarta Barat,", y=140), line("Jakarta, Indonesia, 11730.", y=170)]
    assert resolved(items, "address").value == (
        "Taman Contoh Indah Blok A17 No. 29-30 Jl. Melati Raya Outer Ring Road "
        "Kebon Jeruk, Jakarta Barat, Jakarta, Indonesia, 11730."
    )


def test_wrapped_company_keeps_country_line_out_of_person_candidates():
    items = [line("PT. Contoh Lentera", y=20, height=30),
             line("INDONESIA", y=54, height=24), line("Agus Adi Pratama", y=160, height=32),
             line("Managing Director", y=200, height=20)]
    assert resolved(items, "company").value == "PT. Contoh Lentera INDONESIA"
    assert resolved(items, "full_name").value == "Agus Adi Pratama"


def test_inline_address_phone_is_kept_in_separate_fields():
    parsed = business.parse([line("Jl. Melati No. 10, Bekasi 17433 Tel: +62 21 2345 6789")])
    assert parsed.fields["address"][0].value == "Jl. Melati No. 10, Bekasi 17433"
    assert parsed.fields["phones"][0].value == "+622123456789"


def test_two_card_layout_does_not_join_people_or_addresses():
    items = [line("Andi Wijaya", y=30, height=32), line("Sales Manager", y=70, height=20),
             line("Jl. Melati No. 10", y=130), line("Dewi Lestari", x=650, y=30, height=32),
             line("Project Manager", x=650, y=70, height=20), line("Jl. Mawar No. 20", x=650, y=130)]
    names = resolved(items, "full_name")
    assert names.status == "review"
    assert {item.value for item in names.candidates} == {"Andi Wijaya", "Dewi Lestari"}
    assert resolved(items, "address").status == "review"


@pytest.mark.parametrize("text", ["15810", "RT 001 / RW 008", "Blok E / 10", "Jakarta 10310"])
def test_address_numbers_are_not_phones(text):
    assert not business.parse([line(text)]).fields.get("phones")


def test_oversized_logo_beside_legal_company_is_a_separate_column():
    items = [line("Contohmebel", x=65, y=334, width=760, height=190),
             line("PT Contohmebel Furnitama", x=913, y=385, width=603, height=64)]
    assert resolved(items, "company").value == "PT Contohmebel Furnitama"


def test_right_aligned_name_and_address_blocks():
    items = [line("Andreas Surya Pratama", x=496, y=46, width=1177, height=113),
             line("Account Manager", x=1310, y=166, width=290, height=47),
             line("Head Office", x=1395, y=520, width=237, height=47),
             line("Taman Contoh Indah", x=1120, y=582, width=545, height=59),
             line("Blok A17 No. 29-30", x=1185, y=645, width=479, height=60),
             line("Jl. Melati Raya Outer Ring Road", x=857, y=707, width=812, height=74),
             line("Kebon Jeruk, Jakarta Barat,", x=966, y=775, width=700, height=70),
             line("Jakarta, Indonesia, 11730.", x=986, y=839, width=677, height=66)]
    assert resolved(items, "full_name").value == "Andreas Surya Pratama"
    address = resolved(items, "address").value
    assert address is not None and address.startswith("Taman Contoh Indah Blok A17")
    assert address.endswith("Jakarta, Indonesia, 11730.")


def test_unit_address_followed_by_city_and_postcode():
    items = [line("PT. CONTOH GLOBAL", y=20), line("Contoh Park 38D 66-67 Alam Melati", y=60),
             line("Tangerang 15143, Indonesia", y=90)]
    assert resolved(items, "address").value == (
        "Contoh Park 38D 66-67 Alam Melati Tangerang 15143, Indonesia"
    )


def test_phone_after_locality_continuation():
    parsed = business.parse([line("Menara Contoh level 6 No. 69", y=20),
                             line("Jatiasih Bekasi, Jawa Barat, Indonesia 17433 Tel: +62 21 2345 6789", y=50)])
    assert parsed.fields["address"][0].value.endswith("Indonesia 17433")
    assert parsed.fields["phones"][0].value == "+622123456789"


def test_street_printed_after_the_building_is_written_out():
    # "Jl" without its full stop, after the unit: the l comes back as a capital I.
    items = [line("Menara Contoh level 6 Unit A - H, JI Melati No 69", y=20, width=700),
             line("Jatiasih Bekasi, Jawa Barat, Indonesia 17433", y=50, width=700)]
    assert resolved(items, "address").value == (
        "Menara Contoh level 6 Unit A - H, Jl Melati No 69 Jatiasih Bekasi, Jawa Barat, Indonesia 17433")
    assert business._canonical_street("JI Melati No 69, Bekasi") == ("Jl Melati No 69, Bekasi", [])
    assert business._canonical_street("GRAHA CONTOH, J1. MELATI RAYA 5") == ("GRAHA CONTOH, JL. MELATI RAYA 5", [])


def test_a_block_code_is_not_a_street_and_a_doubtful_one_is_held():
    assert business._canonical_street("Ruko Contoh Blok J1 No. 5, Bekasi") == ("Ruko Contoh Blok J1 No. 5, Bekasi", [])
    # Not at the start of a part of the address: "JI" may be a name here.
    assert business._canonical_street("Arena JI Expo Kemayoran, Jakarta") == (
        "Arena JI Expo Kemayoran, Jakarta", ["uncertain_street_prefix"])
    assert resolved([line("Arena JI Expo Kemayoran, Jakarta 10620")], "address").value is None


def test_a_numeral_read_with_a_lowercase_l_is_held():
    assert business._canonical_street("Jl. Melati Raya ll No. 29")[1] == ["ambiguous_numeral_requires_review"]
    assert business._canonical_street("Jl. Melati Raya II No. 29")[1] == []
    assert resolved([line("Jl. Melati Raya lI No. 29, Jakarta 13470")], "address").value is None


def test_single_word_name_has_a_title_anchor():
    assert resolved([line("SUKARNO", height=32), line("Account Manager", y=80)], "full_name").value == "SUKARNO"
    assert resolved([line("SUKARNO", height=32)], "full_name").value is None


def test_group_affiliation_does_not_compete_with_printed_employer():
    items = [line("PT CONTOH GLOBAL SOLUSI"), line("Member of XYZ Group", y=300)]
    assert resolved(items, "company").value == "PT CONTOH GLOBAL SOLUSI"


def test_name_is_not_reconstructed_from_contact_address():
    items = [line("RINA WIJAYA", height=32), line("Account Manager", y=80),
             line("different.person@example.com", y=180)]
    assert resolved(items, "full_name").value == "RINA WIJAYA"


def test_low_score_wrapped_name_stays_in_review():
    items = [line("Bambang", height=40), line("lrawan", y=82, height=30).model_copy(update={"score": .85}),
             line("Regional Sales Manager", y=120)]
    result = resolved(items, "full_name")
    assert result.candidate == "Bambang lrawan"
    assert result.value is None
    assert {"low_ocr_score", "uncertain_leading_character"} <= set(result.reasons)


def test_the_mailbox_settles_a_capital_i_read_as_l():
    # The address is printed in lowercase, where i and l differ.
    items = [line("Bambang", height=40), line("lrawan", y=82, height=30, score=.85),
             line("Regional Sales Manager", y=120), line("b.irawan@contoh.co.id", y=200)]
    result = resolved(items, "full_name")
    assert result.value == "Bambang Irawan"
    assert result.assignment == "layout"
    # The evidence still shows what was read.
    assert "lrawan" in {item.text for item in result.candidates[0].evidence}
    # A line the mailbox does not spell out keeps its own doubt.
    items = [line("Bambang lrawan", height=40, score=.85), line("Regional Sales Manager", y=120),
             line("b.irawan@contoh.co.id", y=200)]
    result = resolved(items, "full_name")
    assert result.candidate == "Bambang Irawan"
    assert result.value is None and result.reasons == ["low_ocr_score"]


def test_a_well_read_name_that_starts_with_a_lowercase_l_is_still_held():
    items = [line("lndra Kusuma", height=40), line("Sales Manager", y=90)]
    result = resolved(items, "full_name")
    assert result.value is None
    assert result.reasons == ["uncertain_leading_character"]
    assert resolved([line("Lina Kusuma", height=40), line("Sales Manager", y=90)], "full_name").value == "Lina Kusuma"


def test_the_mailbox_says_which_line_is_the_name_without_a_title():
    items = [line("Consulting & Advisory", y=30, height=44), line("Gita Gunawan", y=200, height=36),
             line("FINANCIAL & CONSOLIDATION", x=700, y=60), line("PT Contoh Jaya Sejahtera", y=300),
             line("gita.gunawan@contohjaya.com", y=340)]
    result = resolved(items, "full_name")
    assert result.value == "Gita Gunawan"
    assert result.assignment == "contact"
    assert len(result.candidates) == 1


@pytest.mark.parametrize("address,name", [
    ("budi.santoso@contoh.co.id", "Budi Santoso"), ("santoso.budi@contoh.co.id", "Budi Santoso"),
    ("bsantoso@contoh.co.id", "Budi Santoso"), ("budi.s@contoh.co.id", "Budi Santoso"),
    ("budi_santoso88@contoh.co.id", "BUDI SANTOSO"), ("dharmawan.c@contoh.co.id", "Dharmawan C. G."),
])
def test_how_a_mailbox_carries_a_name(address, name):
    assert resolved([line(name, height=36), line(address, y=200)], "full_name").value == name


@pytest.mark.parametrize("address,printed", [
    ("budi@contoh.co.id", "Budi Santoso"), ("showroom@contoh.co.id", "Showroom Contoh"),
])
def test_one_word_of_a_line_is_not_enough_without_a_title(address, printed):
    # "showroom@" would make a person of the showroom. The line is offered, not accepted.
    result = resolved([line(printed, height=36), line(address, y=200)], "full_name")
    assert result.value is None
    assert result.candidate == printed
    # Under a title the line is the name already, and one word confirms it.
    items = [line("Budi Santoso", height=36), line("Sales Manager", y=84, height=22), line("budi@contoh.co.id", y=200)]
    assert resolved(items, "full_name").value == "Budi Santoso"


@pytest.mark.parametrize("address", ["info@contoh.co.id", "sales.jkt@contoh.co.id", "b.s@contoh.co.id",
                                     "dewi.lestari@contoh.co.id", "santo@contoh.co.id"])
def test_a_mailbox_that_is_not_this_name_settles_nothing(address):
    result = resolved([line("Budi Santoso", height=36), line(address, y=200)], "full_name")
    assert result.value is None
    assert "unlabeled_name_requires_review" in result.reasons


def test_a_shop_mailbox_does_not_rename_the_person():
    # "contohmedia@gmail.com" spells the logo; the title stands under the person.
    items = [line("Contoh Media", x=60, y=20, width=400, height=70), line("Budi Santoso", x=700, y=40, height=36),
             line("Sales Manager", x=700, y=84, height=22), line("contohmedia@gmail.com", x=700, y=300)]
    result = resolved(items, "full_name")
    assert result.value == "Budi Santoso"
    assert result.assignment == "layout"


def test_a_mailbox_that_may_be_the_shop_itself_accepts_no_name():
    # At a free mail host a mailbox is a person's or a shop's: one candidate, under review.
    result = resolved([line("Gita Gunawan", height=36), line("gita.gunawan@gmail.com", y=200)], "full_name")
    assert result.value is None
    assert result.candidate == "Gita Gunawan"
    assert result.reasons == ["unlabeled_name_requires_review"]
    # So is a mailbox that repeats the name of its own host.
    result = resolved([line("Contoh Media", height=36), line("contohmedia@contohmedia.com", y=200)], "full_name")
    assert result.value is None


def test_a_title_under_one_line_and_a_personal_mailbox_for_another_stay_in_review():
    items = [line("CONTOH", y=40, height=36), line("Sales Manager", y=84, height=22),
             line("Budi Santoso", x=700, y=300, height=30), line("budi.santoso@contoh.co.id", x=700, y=360)]
    result = resolved(items, "full_name")
    assert result.value is None
    assert "multiple_person_blocks" in result.reasons
    assert {item.value for item in result.candidates} == {"CONTOH", "Budi Santoso"}


def test_two_people_with_a_mailbox_each_stay_in_review():
    items = [line("Andi Wijaya", height=36), line("andi.wijaya@contoh.co.id", y=90),
             line("Dewi Lestari", x=700, height=36), line("dewi.lestari@contoh.co.id", x=700, y=90)]
    result = resolved(items, "full_name")
    assert result.value is None
    assert "multiple_person_blocks" in result.reasons
    assert {item.value for item in result.candidates} == {"Andi Wijaya", "Dewi Lestari"}


def test_a_letterspaced_logo_is_not_a_person():
    items = [line("A B C D", x=700, height=40), line("Dewi Lestari", height=36)]
    assert [item.value for item in business.parse(items).fields["full_name"]] == ["Dewi Lestari"]


def test_a_domain_without_www_is_a_website_when_the_card_mails_from_it():
    items = [line("rina.wijaya@contoh.co.id", y=40), line("contoh.net.id", y=80)]
    assert contacts(items, "websites") == [("https://contoh.net.id", [])]
    assert resolved(items, "websites").value == "https://contoh.net.id"
    # Alone, or beside another host, it stays a candidate.
    assert contacts([line("contoh.net.id")], "websites") == [
        ("https://contoh.net.id", ["bare_domain_requires_review"])]
    assert contacts([line("rina@lain.co.id", y=40), line("contoh.net.id", y=80)], "websites")[0][1] == [
        "bare_domain_requires_review"]


@pytest.mark.parametrize("misread", ["rina.wocontoh.co.id", "rinaocontoh.co.id", "S.Kom", "contoh.kom"])
def test_an_address_whose_at_sign_was_read_as_a_letter_is_not_a_website(misread):
    items = [line("info@contoh.co.id", y=40), line(misread, y=80)]
    assert contacts(items, "websites") == [(f"https://{misread}", ["bare_domain_requires_review"])]


def people(*extra):
    return [line("Budi Santoso", x=700, y=40, height=36), line("Sales Manager", x=700, y=84, height=22), *extra]


def test_a_stacked_logotype_is_the_company_its_domain_names():
    items = people(line("SINAR", x=60, y=300, width=160, height=50), line("JAYA", x=60, y=356, width=130, height=50),
                   line("ABADI", x=60, y=412, width=150, height=50),
                   line("Digital Printing Solutions", x=20, y=470, width=400, height=30),
                   line("budi@sinarjaya.com", x=700, y=300))
    result = resolved(items, "company")
    assert result.value == "SINAR JAYA ABADI"
    assert result.assignment == "contact"
    assert not result.reasons


def test_a_logo_set_in_two_sizes_is_one_name_when_the_domain_spells_all_of_it():
    items = people(line("Samudra", x=60, y=300, width=300, height=70), line("MARINE", x=120, y=376, width=180, height=22),
                   line("budi@samudramarine.id", x=700, y=300))
    assert resolved(items, "company").value == "Samudra MARINE"
    # A word under the logo that the domain does not spell is not taken along.
    items = people(line("Samudra", x=60, y=300, width=300, height=70), line("LOGISTIK", x=120, y=376, width=180, height=22),
                   line("budi@samudra.co.id", x=700, y=300))
    assert resolved(items, "company").value == "Samudra"


def test_a_logo_mark_read_as_strokes_is_not_part_of_the_name():
    items = people(line("iicontohmedia", x=60, y=20, width=420, height=110, score=.95),
                   line("budi@contohmedia.com", x=700, y=300), line("www.contohmedia.com", x=700, y=340))
    result = resolved(items, "company")
    assert result.value == "contohmedia"
    assert result.candidates[0].evidence[0].text == "iicontohmedia"
    # Real letters in front of the domain's name are not dropped: the role stays uncertain.
    items = people(line("Mycontohmedia", x=60, y=20, width=420, height=110), line("budi@contohmedia.com", x=700, y=300))
    result = resolved(items, "company")
    assert result.candidate == "Mycontohmedia"
    assert result.reasons == ["unlabeled_company_requires_review"]


def test_a_free_mail_host_names_no_company():
    items = people(line("Proton", x=60, y=20, width=300, height=90), line("budi@proton.me", x=700, y=300))
    assert resolved(items, "company").reasons == ["unlabeled_company_requires_review"]


def test_a_logo_mark_several_rows_tall_is_not_print_of_one_of_them():
    # The mark beside a stacked logotype is read as a few letters, as tall as all its rows.
    items = people(line("NNP", x=60, y=290, width=260, height=180, score=.48),
                   line("SINAR", x=300, y=300, width=160, height=50), line("JAYA", x=300, y=356, width=130, height=50),
                   line("ABADI", x=300, y=412, width=150, height=50), line("budi@sinarjaya.com", x=700, y=300))
    assert resolved(items, "company").value == "SINAR JAYA ABADI"


def trading(*extra, host="contoh-net.co.id", legal="PT. LENTERA GROUP"):
    """A person, a legal company name and the card's own addresses; the tests add the print around them."""
    return people(line(legal, x=60, y=460, width=330, height=30),
                  line(f"budi@{host}", x=700, y=300), line(f"www.{host}", x=700, y=340), *extra)


def test_a_trading_name_beside_the_legal_name_is_the_company_alias():
    items = trading(line("Contoh-net", x=60, y=40, width=420, height=110),
                    line("CONTOH-NET INDONESIA", x=60, y=420, width=380, height=30))
    alias = resolved(items, "company_alias")
    # The name written out, not the logo that repeats part of it.
    assert alias.value == "CONTOH-NET INDONESIA"
    assert alias.assignment == "contact"
    assert not alias.reasons
    assert resolved(items, "company").value == "PT. LENTERA GROUP"
    assert resolved(items, "full_name").value == "Budi Santoso"


def test_a_logo_is_the_alias_when_the_name_is_not_written_out():
    items = trading(line("Contoh-net", x=60, y=40, width=420, height=110))
    assert resolved(items, "company_alias").value == "Contoh-net"
    # Read with spaces between its letters, it is still one word.
    items = trading(line("A B C D", x=60, y=40, width=420, height=110), host="abcd.co.id")
    assert resolved(items, "company_alias").value == "ABCD"


@pytest.mark.parametrize("printed,host", [
    # The legal name's own short forms.
    ("LENTERA", "lentera.co.id"), ("Lentera Indonesia", "lentera.co.id"), ("Lentera", "lenteragroup.com"),
    # Names the card's domain does not spell: a partner, a tagline.
    ("Mitra Abadi", "contoh-net.co.id"), ("Solusi Tepat Anda", "contoh-net.co.id"),
    # The domain spells only how the line starts: a department, not a name.
    ("CONTOH-NET Customer Care", "contoh-net.co.id"), ("Contoh-net Peduli", "contoh-net.co.id"),
])
def test_what_is_not_a_second_company_name(printed, host):
    items = trading(line(printed, x=60, y=40, width=420, height=60), host=host)
    parsed = business.parse(items)
    assert "company_alias" not in parsed.fields
    assert [item.value for item in parsed.fields["company"]] == ["PT. LENTERA GROUP"]


def test_a_short_name_is_recognised_through_a_lookalike_letter():
    # The capital I of the legal name was read as a lowercase l; the logo was read correctly.
    items = trading(line("INTIRAYA", x=60, y=40, width=420, height=60), host="intiraya.co.id",
                    legal="PT. lNTIRAYA ABADI")
    assert "company_alias" not in business.parse(items).fields


def test_an_alias_needs_a_legal_or_labelled_company_name():
    # Without one, the name the domain spells is the company itself.
    items = people(line("CONTOH-NET INDONESIA", x=60, y=40, width=420, height=60),
                   line("budi@contoh-net.co.id", x=700, y=300))
    parsed = business.parse(items)
    assert [item.value for item in parsed.fields["company"]] == ["CONTOH-NET INDONESIA"]
    assert "company_alias" not in parsed.fields
    # A labelled company name counts as much as "PT ...".
    items = people(line("Company: Lentera Abadi", x=60, y=460, width=330, height=30),
                   line("CONTOH-NET INDONESIA", x=60, y=40, width=420, height=60),
                   line("budi@contoh-net.co.id", x=700, y=300))
    assert resolved(items, "company_alias").value == "CONTOH-NET INDONESIA"
    assert resolved(items, "company").value == "Lentera Abadi"


def test_a_line_that_may_be_the_persons_name_is_not_taken_as_the_alias():
    # No title and a shared mailbox: "Rina Wijaya" is still only a candidate for the name.
    items = [line("Rina Wijaya", x=700, y=40, height=36), line("PT. LENTERA GROUP", x=60, y=460, width=330, height=30),
             line("info@rinawijaya.com", x=700, y=300)]
    parsed = business.parse(items)
    assert [item.value for item in parsed.fields["full_name"]] == ["Rina Wijaya"]
    assert "company_alias" not in parsed.fields


def test_two_reads_that_differ_on_the_alias_leave_it_in_review():
    first = trading(line("CONTOH-NET INDONESIA", x=60, y=420, width=380, height=30))
    second = trading(line("CONTOH NET INDONESIA", x=60, y=420, width=380, height=30))
    observations = []
    for pid, items in (("p1", first), ("p2", second)):
        observations.extend(business.parse([item.model_copy(update={"pass_id": pid}) for item in items])
                            .fields.get("company_alias", []))
    result = business.resolve_field(observations, .93, True)
    assert result.value is None
    assert {item.value for item in result.candidates} == {"CONTOH-NET INDONESIA", "CONTOH NET INDONESIA"}


def test_two_complete_phone_boxes_on_one_row_stay_separate():
    parsed = business.parse([line("+62 812 3456 7890", width=240),
                             line("+62 813 2345 6789", x=290, width=240)])
    assert [item.value for item in parsed.fields["phones"]] == ["+6281234567890", "+6281323456789"]


@pytest.mark.parametrize("contact", ["suite@example.com", "wisma@example.com", "https://tower.example.com"])
def test_address_keywords_in_contacts_are_not_address_lines(contact):
    parsed = business.parse([line(contact)])
    assert "address" not in parsed.fields
    assert parsed.fields.get("emails") or parsed.fields.get("websites")
    assert business.contact_text(contact)


def test_legal_company_with_building_keyword_is_not_an_address():
    items = [line("PT WISMA CONTOH"), line("Jl. Melati No. 10", y=100)]
    assert resolved(items, "company").value == "PT WISMA CONTOH"
    assert resolved(items, "address").value == "Jl. Melati No. 10"


def test_two_explicit_addresses_remain_separate():
    items = [line("Alamat: Jl. Melati No. 10", y=20), line("Alamat: Jl. Mawar No. 20", y=50)]
    assert resolved(items, "address").status == "review"
    assert len(resolved(items, "address").candidates) == 2


def kinds(*printed, region="ID"):
    items = [line(text, y=40 + 40 * row) for row, text in enumerate(printed)]
    return [(item.value, item.kind) for item in business.parse(items, region).fields.get("phones", [])]


@pytest.mark.parametrize("printed,expected", [
    # The number tells a mobile from a landline: in Indonesia every 08 number is a mobile.
    ("0812 3456 7890", ("+6281234567890", "mobile")),
    ("+62 21 2345 6789", ("+622123456789", "landline")),
    ("M: +62 812 3456 7890", ("+6281234567890", "mobile")),
    ("WA 0812 3456 7890", ("+6281234567890", "mobile")),
    ("T. (021) 2345 6789", ("+622123456789", "landline")),
    ("Kantor: 021 2345 6789", ("+622123456789", "landline")),
    # Only the label tells a fax line from a telephone line.
    ("F: (021) 2345 6789", ("+622123456789", "fax")),
    ("Fax.(62-21) 2345 6789", ("+622123456789", "fax")),
    # Where the label and the number disagree, the number decides.
    ("HP: 021 2345 6789", ("+622123456789", "landline")),
    ("T: 0812 3456 7890", ("+6281234567890", "mobile")),
])
def test_each_phone_number_has_a_kind(printed, expected):
    assert kinds(printed) == [expected]


def test_numbers_sharing_a_label_share_its_kind():
    assert kinds("Fax: (021) 2345 6789, 2345 6780") == [("+622123456789", "fax"), ("+622123456780", "fax")]
    assert kinds("P: +62 21 2345 6789 / 0812 3456 7890") == [("+622123456789", "landline"),
                                                              ("+6281234567890", "mobile")]


def test_without_a_number_type_only_the_label_tells():
    # A national US number can be a mobile or a landline.
    assert kinds("(423) 220-0983", region="US") == [("+14232200983", None)]
    assert kinds("M: (423) 220-0983", region="US") == [("+14232200983", "mobile")]
    # A number that could not be read keeps the label's kind for review.
    assert kinds("M: +62 812 3456 789O") == [("+62 812 3456 789O", "mobile")]


def test_the_reads_of_one_number_settle_its_kind():
    def read(text, pid):
        return business.parse([line(text, pid=pid)]).fields["phones"]

    observations = read("F: (021) 2345 6789", "p1") + read("(021) 2345 6789", "p2")
    result = business.resolve_contacts(observations, .93, True, {})[0]
    assert result.value == "+622123456789"
    assert result.phone_type == "fax"
    result = business.resolve_contacts(read("0812 3456 7890", "p1") + read("0812 3456 7890", "p2"), .93, True, {})[0]
    assert result.phone_type == "mobile"
