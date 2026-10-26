# Business-card improvements (v1.4, tuned in v1.5, photographed cards in v1.7)

## v1.8 — mobile, landline and fax numbers

A contact form usually asks for the company address, the person's title and a mobile
number. The first two are `address` and `job_title`; the printed address on a business
card is the company's. Telephone numbers used to come back as one list, with nothing to
tell the mobile number from the office line or the fax. Each number now has a type:

| JSON path | Meaning |
| --- | --- |
| `fields.phones[].phone_type` | `mobile`, `landline`, `fax`, or `null` when nothing tells |
| `data.mobile_phones` | The accepted numbers of type `mobile`, in printed order |

`data.phones` is unchanged and still holds every accepted number.

How the type is decided:

- **The number tells a mobile from a landline.** In Indonesia every `08` / `+62 8`
  number is a mobile, so a mobile number is found even with no label or with a
  pictogram the recogniser cannot read. Where a label and the number disagree
  (`HP: 021 ...`), the number decides.
- **Only the label tells a fax from a telephone line**: `F`, `Fax`, `Faks`. A fax
  number marked only by a fax pictogram comes back as `landline`.
- Where the number type is not fixed by its numbering (a national US number, a number
  that could not be read), the label decides: `M`, `Mobile`, `HP`, `Handphone`, `WA`,
  `Ponsel` mean mobile; `T`, `P`, `Tel`, `Telp`, `Phone`, `Kantor`, `Office` mean
  landline. Without a label the type is `null`.
- `Kantor`, `Office`, `Direct`, `Mob`, `Ponsel` and `Seluler` are now recognised as phone
  labels, so `Kantor: 021 ...` is read as a telephone number at all.

On the 17 photographs all 41 printed numbers got the right type, and `mobile_phones`
held exactly the card's mobile number on every photograph. The accepted values
themselves did not change (136 of 136 correct, none wrong).

### v1.8 — a second company name

Some cards print two company names: the name the business trades under and the legal
entity behind it, for example `CONTOH-NET INDONESIA` over `PT. LENTERA GROUP`, with the
email address and the website at `contoh-net.co.id`. `company` keeps the legal or
labelled name. The other name now has a field of its own:

| JSON path | Meaning |
| --- | --- |
| `data.company_alias` | The accepted second name, or `null` |
| `fields.company_alias` | Its result and evidence; `status` is `missing` on a card with one name |

How it is decided:

- **The card has a legal or labelled company name**: `PT ...`, `CV ...`, `... Group`,
  `Company: ...`. Without one, the name the domain spells is the company itself, as in
  v1.7, and there is no alias.
- **The card's own domain spells the alias.** The domain is the host of a printed email
  address or website, never a free mail host. It has to spell every word, apart from
  what a company adds to its own name (`Indonesia`, `Group`, `Global`, `International`,
  ...). For `budi@contoh-net.co.id`, `CONTOH-NET INDONESIA` is an alias.
  `CONTOH-NET Customer Care` is a department, and a partner's logo or a tagline is not
  spelled by the domain at all; none of them is reported.
- **It is another name.** A short form of the legal name is not an alias: `CONTOH` or
  `Contoh Indonesia` beside `PT Contoh Lentera Abadi`.
- Where the name is printed twice, in the logo and written out, the fullest form is
  reported: `CONTOH-NET INDONESIA`, not the logo `Contoh-net`. A logo read with spaces
  between three or four letters is closed up (`A B C D` becomes `ABCD`).
- A line that is still only a candidate for the person's name is left to `full_name`.
- In `accurate` mode two passes have to read the same alias, as for every other value;
  two different reads stay in review as candidates. `assignment` is `contact`. A card
  without an alias is not sent to review for it.

A trading name that the domain does not spell is not reported: a company that mails
from an abbreviation of its name, or a card with no email address or website. Nothing
tells such a line from a slogan, so it is left out instead of guessed.

On the 17 photographs one card prints a second company name this way. It was accepted
in `accurate` and `fast` mode and with `document_type=auto`, and no alias was reported
for the other 16 photographs.

## v1.7 — cards photographed by hand

A phone photograph of a business card shows more than the card: the hand holding it, a
keyboard, a screen, other cards underneath. v1.6 read all of it as one card. On 17 such
photographs of 14 Indonesian cards it accepted a telephone number and a website from
the card lying behind, another person's job title, and company names with the address
row glued on. v1.7 finds the card first.

### What the service does now

1. **The card is found around its own print.** The first read shows where the print is
   and how it is turned. The four edges of the card are then looked for around it; the
   card is cut from the full-size upload, flattened and read again. Print outside the
   outline is never evidence. This works for a card held in a hand, lying on other
   cards, or in front of a keyboard or a screen, including two-colour cards and cards
   with a footer band. It needs at least three edges partly visible.
2. **A card photographed sideways or upside down is set upright.** The recogniser turns
   each line on its own, so such a card used to be read with its layout on its head.
   Which lines it turned says how the card lies; the upload is turned and read once more.
3. **Without an outline, less of the background is read as card.** Print cut off by
   the edge of the photograph and print turned against the card's own direction are
   left out.
4. **More roles are titles.** `GM`, `VP`, `Head of ...`, `Staff ...`, `Analyst`,
   `Koordinator` and similar. A role that also names what the company sells is still a
   role (`Senior Solutions Consultant`, `Customer Service Officer`); `IT Services and
   Software Solutions` is not.
5. **The email address confirms the name.** A printed line that the mailbox spells
   (`budi.santoso@`, `b.santoso@`, `bsantoso@` for "Budi Santoso") is the person's name,
   also without a title under it, when the address is at the company's own host. The
   mailbox is printed in lowercase, where `i` and `l` differ, so it also settles a
   capital `I` read as `l`. The value is always the printed line.
6. **The card's own domain confirms the company.** A card without a "PT ..." line names
   its company in the logo and in the domain of its addresses. A logotype the domain
   spells is accepted as the company, as printed, with `assignment: "contact"`.
7. **Phones.** A pictogram in front of a number, which the recogniser returns as a CJK
   character, no longer hides the number. `(021) 5551234, 5551235` and
   `+62 21 3042 1111 / 3042 1112` print the area code once: the second landline number
   is completed with it and accepted. See "Shared area code" below.
8. **Websites.** A domain printed without `www.` is accepted when it is the host of an
   email address on the same card (`contoh.net.id` beside `@contoh.co.id`). Alone it
   stays a review candidate, as before.
9. **Streets.** `Jl` printed after the building and without a full stop (`Unit A, Jl
   Melati No 69`) comes back as `JI`; it is written out there as it already was at the
   start of a line. Elsewhere in a line it is held for review, and so is a numeral read
   with a lowercase `l` (`Melati ll No. 29`).

### Measured on the 17 photographs

Accurate mode, 136 printed values (name, title, company, address, every email,
telephone number and website). "Wrong" counts accepted values that differ from the
print: the errors an application would not notice.

| Field | v1.6 correct | v1.6 wrong | v1.7 correct | v1.7 wrong |
| --- | ---: | ---: | ---: | ---: |
| Full name | 10 / 17 | 0 | 17 / 17 | 0 |
| Job title | 10 / 16 | 1 | 16 / 16 | 0 |
| Company | 9 / 16 | 2 | 16 / 16 | 0 |
| Address | 7 / 17 | 5 | 17 / 17 | 0 |
| Emails | 21 / 21 | 0 | 21 / 21 | 0 |
| Phones | 37 / 41 | 1 | 41 / 41 | 0 |
| Websites | 7 / 8 | 1 | 8 / 8 | 0 |
| **All** | **101 / 136** | **10** | **136 / 136** | **0** |

In `fast` mode v1.6 accepted 102 values correctly and 15 wrongly; v1.7 accepts 136 and
none wrongly. Sixteen of the 17 documents are `ok` in accurate mode (one in v1.6); the
last is a card that prints no company name. The same photographs turned by a quarter or
upside down, and reduced to 1600 and 1024 pixels as a messaging app would send them,
are covered in [TUNING.md](TUNING.md#v17--business-cards-photographed-by-hand).

These photographs were used to develop the changes. They are not a held-out test
set, the figures are not a general accuracy percentage, and the photographs, their
transcriptions and the extracted values are not part of this repository.

### What changes for a client

The endpoint, the JSON keys and `schema_version` are unchanged. Flutter still reads
accepted values from `data` and candidates from `fields`.

- `fields.<field>.assignment` has a fifth value, `contact`: the role was settled by a
  printed email address or domain.
- `processing.passes` for a photographed business card is `original`, `card`, `clahe`.
  The `original` read locates the card and supplies no evidence. `to_input` maps every
  pass onto the decoded upload as before. A card that had to be turned shows two
  `original` passes with different `rotation_clockwise`.
- New review reasons: `ambiguous_numeral_requires_review` on an address, and
  `uncertain_leading_character` on a name that starts a word with a lowercase `l`
  before a consonant and has no email address to settle it.
- Send one card per photograph. It does not have to be cropped. A photograph that
  shows two whole cards side by side (a front-and-back picture) is not cropped to one
  of them and is read as before.

### Shared area code

Until v1.6 a second number printed without its area code stayed a review candidate in
its printed form. v1.7 completes it, because the printed convention leaves no doubt,
under these conditions: the first number of the same line is a valid landline number
with an area code, the second has exactly as many digits as the first's subscriber
number, carries no prefix of its own, and the result is a valid number. A mobile number
is never completed this way. Set `OCR_SHARED_AREA_CODE=false` to keep the earlier
behaviour.

### Limits

- The outline needs straight card edges. A card bent strongly, cut off on two sides, or
  on a surface of the same colour with no visible edge is read from the whole
  photograph, with only the cut-off and turned print left out.
- Other print of the same size and direction beside the card (a second card laid next
  to it) stops the cropping: the service cannot know which card is meant.
- A name without a title is accepted only when a mailbox at the company's own host
  spells at least two of its words. `budi@gmail.com` may be a person or a shop, so the
  line it spells is offered as the single candidate, not accepted.
- Agreeing reads can still share a wrong character. Accepted values are not proof of
  correct transcription.

## Layouts handled since the first Indonesian samples

The parser rules added for the first set of Indonesian cards, read from hand-made
crops, are unchanged in v1.7:

- Names wrapped over two closely spaced rows, single-word names anchored by a title,
  and right-aligned name/title blocks.
- Wrapped titles such as `SENIOR INFORMATION TECHNOLOGY` followed by `MANAGER`. Office
  headings and service lists are kept out of the person and title candidates.
- Building, floor, street, city and country lines as one address, including
  right-aligned blocks, `Head Office` building names and numbered estate addresses
  followed by a city and postcode. Separately labelled addresses stay separate.
- `M`, `P`, `T`, `F`, `Ph.`, `Mobile`, `WA` and other phone labels with or without a
  colon, including a label in its own OCR box. `(62-21)` supplies the printed country
  code when `phone_region=ID`.
- Telephone text appended to an address line, with the phone returned separately.
- A large logo beside a `PT ...` company name, a wrapped `INDONESIA` company suffix, and
  `Member of ... Group` affiliations, which do not replace the employer.

HEIC is not an upload format of this release: export or convert to JPEG, PNG or WebP
before sending from Flutter. Changing the file name does not convert the image.

Regression tests for all of the above are in `tests/test_business_indonesia.py`, built
from made-up names, addresses and contacts. No photograph was uploaded to a remote
service for testing.

## Earlier changes

This release uses the supplied v1.3 project as its base. The free RapidOCR / ONNX
models and local/Gradio setup are unchanged. No paid OCR service or LLM is needed.
The v1.3 KTP parser, respacing and configuration remain in place.

## What changed

- **Separate columns and typography.** A large logo no longer causes several small
  text rows to merge. A telephone box in one column no longer swallows the company
  or street address in another.
- **Identify roles before choosing a person.** Company prefixes/suffixes include
  `PT.`, `CV`, `Co`, `Corp`, `Group`, `Ltd`, and others. Jobs include Indonesian
  `Agen` and `Komisaris`, plus `Real Estate Agent`, `Commissioner`, and `Specialist`.
  Company and job lines are excluded from the pool of person-name candidates.
- **Use name/title layout.** One plausible person line closely above a recognized
  job title can qualify as a name. Multiple plausible person blocks remain in review.
  An isolated brand can be proposed as a company, but its role remains under review.
- **Read street blocks.** `Jl.`, common street abbreviations such as `St.`, and aligned
  continuation lines are retained. Contacts stop address continuation. Postcodes are
  not collected as phone numbers. A damaged street prefix remains reviewable.
- **Keep phone details.** Multiple comma/pipe-separated numbers and extensions such
  as `ex 123` are supported. Invalid or ambiguous number-shaped text remains a printed
  review candidate. (Until v1.6 a second short number never took the area code of the
  first; see "Shared area code" above for what v1.7 does.)
- **Separate social handles.** `@handle` is returned in `social_handles`, not mistaken
  for a malformed email. The platform/account is not inferred or verified.
- **Label and street handling.** `Telepon`, `Telp`, `HP`, `Handphone`, `Kontak`, `WA`,
  `WhatsApp` and `Faks` are recognized phone labels, with an optional `No.` prefix. A
  labelled address gets the same `Jl.` prefix correction as a pattern-matched one, so
  a recogniser reading `JI.` no longer hides behind the label path.
- **Retry small print.** If the median detected text height is below
  `OCR_SMALL_TEXT_HEIGHT_PX` (default 28 pixels), accurate mode adds two magnified crop
  readings. The retry now applies to KTP too. The model is reused, with bounded
  dimensions and no per-request download. Set `OCR_SMALL_TEXT_RETRY=false` to disable;
  the retained `OCR_BUSINESS_RETRY=false` also turns it off.

## Country selection matters

A national number such as `(423) 220-0983` must not silently become an Indonesian
`+62` number. In default `ID` mode, numbers lacking a visible `+country` or Indonesian
leading zero stay as review candidates. Select the number's country for normalization:

```bash
curl http://127.0.0.1:7860/v1/ocr/business_card \
  -F "file=@/absolute/path/to/card.jpg" \
  -F "mode=accurate" \
  -F "phone_region=US"
```

This is also available in Gradio under **Image and output options → Phone country**.
The four client examples accept optional `phoneRegion`. REST field names are identical
for JavaScript, Flutter, native iOS and native Android. The evaluator accepts an
optional `phone_region` in each manifest entry, so a mixed-country dataset can be tested.

`processing.phone_region` records the choice. Explicit international numbers such as
`+62 ...` retain their printed country code regardless of that setting. Number-range
validation does not establish that the number is assigned or reachable. See
[libphonenumber's parsing and validation FAQ](https://github.com/google/libphonenumber/blob/master/FAQ.md).

## Acceptance and compatibility

Business `accurate` mode now requires two qualifying reads even when the v1.3 KTP
`OCR_SINGLE_PASS_THRESHOLD` setting is enabled. Two agreeing high-score reads can
outweigh a weak or invalid alternative; a competing valid high-score reading still
forces review. Full names, emails, phone numbers and addresses are compared without
removing their meaningful punctuation. Two repeated OCR errors can still agree.

Existing endpoints and the `data` / `fields` shape remain compatible. Additive fields:

| JSON path                                       | Meaning                                                       |
| ----------------------------------------------- | ------------------------------------------------------------- |
| `data.social_handles` / `fields.social_handles` | Printed handles and their review results                      |
| `fields.<field>.assignment`                     | `label`, `pattern`, `layout`, `contact` (v1.7) or `heuristic` |
| `fields.phones[].phone_type` (v1.8)             | `mobile`, `landline`, `fax`, or `null`                        |
| `data.mobile_phones` (v1.8)                     | Accepted numbers of type `mobile`                             |
| `data.company_alias` / `fields.company_alias` (v1.8) | A second company name the card's own domain spells       |
| `fields.<field>.candidates[].supporting_passes` | Passes supporting that candidate                              |
| `quality.text_height_px`                        | Median detected text height in the pixels of the view read    |
| `processing.phone_region`                       | Country used for national phone numbers                       |
| `processing.passes[].to_input`                  | 3×3 transform from pass coordinates to decoded input          |

For contact lists, assignment and candidates belong to each entry. KTP assignment
metadata is null. The response `schema_version` remains `1.0` because these additions
are optional; the application version is `1.4.0`. Gradio's generated `extract` endpoint
has a sixth input, `phone_region` (empty string uses the default). Existing five-argument
Gradio clients must add that input; the REST country field remains optional.

Only accepted values appear in `data`. Never copy a review candidate into an accepted
record automatically. Show it beside the source image in your application's correction
form. A missing optional field does not always set document-level review, so enforce
your application's own required fields.

## Checks on the supplied examples

The six supplied images were run through the actual pinned OCR engine before and after
the changes. They were used during development, not held out as an independent test set.
No general accuracy percentage is claimed. Results and measured timings are recorded
in `TEST_REPORT.md`.

The JSON example with a company ending in `Co` and the title `Agen Real Estate` is
covered by a synthetic geometry regression test. Its corresponding image was not among
the six new image attachments, so an image-to-JSON claim is not made for that example.

Some supplied files are front/back mockups or photographs of several cards. The API
still accepts one image and returns one field collection; it does not reliably detect
or isolate every card, associate two sides, or read text covered by another card.
Crop one card/side before uploading, especially for small stacked-card photographs.
Template words and example telephone numbers are not evidence of a real business.
