# Accuracy, review policy, and evaluation

This release is a working extraction service with conservative acceptance rules.
No real-world KTP or business-card accuracy percentage has been measured. The supplied
fixtures are plain synthetic test sheets, not photographs of real identity documents.

## What the numbers mean

`ocr_score` is the model's recognition confidence for the supporting text box(es),
averaged over the printed characters of each box. Word breaks and the colon between
a label and its value are not counted; they are the characters this recogniser doubts
most, and no value contains them. A NIK is scored by its **weakest digit** instead of
an average, so one doubted digit cannot hide among fifteen confident ones. A field uses
the weakest of its value boxes. Across passes, a value is scored by the weaker of the
two strongest agreeing reads, listed in `supporting_passes`; a further, less confident
read of the same value does not lower it. Other reads and candidates remain in
evidence; scores are not converted into probabilities. `raw_ocr[].score` is still the
recogniser's own mean over the whole line.
It is not a calibrated field-correctness probability. A score of 0.99 does not establish
a 99% chance that every character, field assignment, or the entire document is correct.

Business cards in accurate mode require two qualifying processing passes. Original,
contrast-enhanced, levelled and optional magnified images use the same model, so their
errors are correlated. Agreement can still be wrong. Layout role selection is a heuristic separate
from the model's OCR score. A high recognition score cannot prove that a line is a name.

The retained v1.3 KTP policy also permits one-read fields above
`OCR_SINGLE_PASS_THRESHOLD` (default 0.99), except NIK. Setting it to 1.0 removes that
exception for scores below 1.0; an exact score of 1.0 can still qualify. Use
`OCR_STRICT_NIK_CROSS_CHECK=true` and `OCR_NIK_CORROBORATES_GENDER=false` when you require
printed date/gender acceptance independently of NIK corroboration. These KTP settings
do not relax the business-card two-read rule.

Validation catches structural errors, not all OCR mistakes. A wrong-but-plausible
16-digit NIK, email, or phone number can pass format validation and remain wrong.
The service never claims government verification or contact ownership.

## KTP rules

NIK must have 16 ASCII digits. Spaces and grouping punctuation can be normalized.
OCR substitutions such as `O` to `0` produce a suggested candidate with
`character_substitution_requires_review`; they never become silently accepted values.
Missing digits are not invented, and the field is never parsed as an integer.
An accepted NIK needs two agreeing reads whose weakest digit each reaches
`OCR_NIK_THRESHOLD` (default 0.98).

KTP readings agree when their letters and digits match. Spacing never decides
agreement; punctuation does when it differs. If no single punctuation form was read
twice, the field is withheld with `punctuation_differs` (`NO.5A` and `NO 5A` are
different addresses). Word breaks come from three sources: the recogniser's decoded
spaces, breaks it rated but did not decode (see `docs/PARSER_FIXES.md`), and blank
pixel columns on long lines. A spacing error can still reach an accepted value.

This recogniser reads a plain capital `I` in a block code as the digit `1`, confidently
and consistently. An address whose one-character block code reads `1` (or `l`) before a
dash or slash, or `I`/`l` after one, is withheld with `ambiguous_block_character`,
however many passes agree.

The birth component is checked for calendar plausibility. The date and gender are
also compared with the corresponding printed fields. For the encoded day, female
dates use the day plus 40, as described by [Dispendukcapil Kota Mojokerto](https://dispenduk.mojokertokota.go.id/home/berita/Arti-kode-angka-dalam-NIK-E-KTP).
The service does not infer a missing birth year or century from the NIK. The v1.3
default accepts matching printed date/gender candidates as cross-checks even if they
remain under review. Its optional NIK-to-gender corroboration can accept an already
read canonical gender after checking a NIK that passed policy. It does not repair an
unrecognized gender word. This behavior is a coverage/strictness tradeoff, not identity
verification; the strict settings above require more human review.

An NIK's administrative prefix is **not checked against a government region database**.
The prefix is not compared with the card's current address: somebody can move while
keeping the same NIK. The synthetic test prefix `99` deliberately does not represent
a real province. Tests verify extraction and date consistency, not NIK authenticity.

NIK, full name, birth date, gender, and street address are required by the default
document review policy. Adapt this list to your form's needs. Missing optional fields
remain null even if the document has `status=ok`.

The parser handles common printed Indonesian labels and same-row gender/blood fields.
It does not fuzzy-match every damaged or unusual label. Unreadable labels may cause
missing fields, which is preferable to assigning unrelated text to a confident field.
Multiline address continuation is retained. It requires review when no labelled row
closes the block, or when the block absorbed more than one wrapped line.

## Business-card rules

Emails are checked for syntax only, with DNS/deliverability lookups disabled.
Phone normalization uses phonenumbers' metadata; it does not call or check whether a
number is active. `phone_region` overrides `OCR_DEFAULT_PHONE_REGION=ID` per request.
With default ID, numbers without a visible leading zero or `+country` remain review
candidates. This avoids silently assigning Indonesian country codes to foreign
national numbers. One printed convention is followed: in `(021) 5551234, 5551235` the
second landline number takes the area code printed for the first, when it has as many
digits as the first's subscriber number and the result is a valid number
(`OCR_SHARED_AREA_CODE=false` keeps it as printed, for review). Other partial numbers
do not inherit anything from their neighbors.
Postcodes in address lines are excluded from telephone extraction. See the
[upstream parsing FAQ](https://github.com/google/libphonenumber/blob/master/FAQ.md).

Website strings are parsed and normalized without network access. The service never
derives a person's name from an email username, nor a company from an email domain:
both values are always a line the card prints. An address can confirm such a line.
A line that a mailbox at the company's own host spells (`budi.santoso@`, `b.santoso@`)
is the person's name, and a logotype that the card's own domain spells is the company;
`assignment` is then `contact`. A mailbox at a free mail host, a shared mailbox such as
`info@`, and a mailbox that touches only one word of the line confirm nothing alone.
Bare domains without a website label require review because initials or qualifications
can resemble domain names, and so can an address whose `@` was misread; a bare domain
is accepted only when it is the host of an email address on the same card.
Scheme-prefixed and `www.` addresses are clearer evidence.

A unique plausible name closely above a recognized job title can qualify as a name.
Explicit company prefixes/suffixes, recognized job terms and street patterns can
qualify other roles after two clear reads. Separate columns and large logos are
handled without joining unrelated rows. Aligned address continuations are retained.
`assignment` tells you whether a role came from a label, pattern, layout, printed
contact, or weaker heuristic. This is not a trained entity classifier.

Isolated brands, multiple person blocks, placeholder company names, damaged prefixes,
and ambiguous contacts remain review candidates. Some company name variants and
multiline extents still need human correction. Do not equate an accepted pattern or
layout assignment with an independently verified identity.

Names, companies, job titles and addresses agree when two readings differ only in word
breaks; punctuation still has to match. Contact details use exact text comparison. Two
high-score conflicting readings cannot be collapsed by removing punctuation. `@handle` is separate from email.
Magnified retries can reveal previously missing text, but may also introduce new
conflicts. This is preferable to concealing a conflicting contact behind an accepted
partial reading.

Latin-script Indonesian/English cards are the target parsing scope. The underlying
model recognizes other scripts too, but the parser's labels, phone assumptions, and
entity heuristics are not validated for all languages.

## Capture guidance

- Place one card nearly flat and parallel to the camera. Either crop tightly to the card,
  or keep its edges visible so the service can find and flatten the card itself. A
  business card may be held in a hand; keep fingers off the print and off as much of
  the edges as possible, and keep other whole cards out of the picture.
- Keep all edges and text visible. Aim for at least 1,400 pixels across the card.
- Use even light; avoid flash reflection, shadows, blur, and fingers over the text.
- Upload the original capture or a high-quality JPEG. Avoid messaging-app screenshots
  or repeatedly compressed images.
- Review proposed values beside the image. Retake unreadable regions; a stronger
  model cannot recover information that is absent from the pixels.

The service applies EXIF orientation, bounded resizing, text-line orientation
classification, and limited 90/270-degree fallback probes (also tried when a KTP was
requested and the upright read does not look like one). In accurate mode it also
measures the tilt of the detected text lines and re-reads a levelled view when the page
is visibly rotated (disable with `OCR_DESKEW_RETRY=false`). When the card outline is
visible on a background, in either mode, it reads a flattened, magnified view of the
card instead of the whole photo (disable with `OCR_CARD_DETECTION=false`). For a KTP
that needs all four edges visible against a surface of a different colour; a KTP held
in a hand, cut off by the frame, or photographed on a similar-coloured surface is read
from the whole image as before. A business card is also found around its own print
after the first read, which works in a hand and among other things as long as three
of its edges are partly visible, and a business card photographed sideways or upside
down is set upright first. A photo showing two whole cards (a front-and-back mockup)
is read whole. Blur/contrast checks are
global heuristics and may miss localized glare or damage. Business cards and KTP report
median detected text height and retry a magnified text crop below
`OCR_SMALL_TEXT_HEIGHT_PX` (default 28 pixels) in accurate mode. This does not recreate
lost pixels or detect each card in a multi-card mockup. Pre-crop and deskew cards
in your capture flow when possible. Send `rotation` when the user rotates an image.

## Measure before choosing thresholds

Collect consented images representative of the actual cameras and cards you will use:
different phones, older KTP print, glare, rotation, low light, business layouts,
fonts, and long names. Include negative inputs that are not cards. Keep separate
development and held-out test sets, and keep the same person's/card's repeated images
in the same split to avoid leakage.

Create a local JSON manifest; image paths are relative to the manifest:

```json
[
  {
    "image": "photos/001.jpg",
    "document_type": "ktp",
    "expected": {
      "nik": "COPY_THE_EXACT_PRINTED_VALUE",
      "full_name": "COPY THE EXACT PRINTED NAME",
      "birth_date": "1990-08-15"
    }
  }
]
```

The placeholder is not a usable KTP label. Transcribe the real, consented sample.
Use the API's normalized representation for ground truth: dates in ISO, contacts as
arrays, phones in E.164, and strings for NIK/RT/RW. List all fields that matter,
including absent ones with `null` or `[]`, so false extractions can be assessed.
The evaluator only scores the fields explicitly annotated in `expected`.

```bash
python -m scripts.evaluate private-dataset/manifest.json --output evaluation.json
```

Measure these together:

| Metric                                  | Why it matters                                                   |
| --------------------------------------- | ---------------------------------------------------------------- |
| Wrong accepted values / accepted values | The silent error rate among values your app may use              |
| Accepted precision                      | One minus that silent error rate                                 |
| Acceptance coverage                     | How much of the annotated input can be used without field review |
| Candidate exact match                   | Whether the proposed candidate is correct even when withheld     |
| Whole-document review count             | The manual correction workload                                   |
| Error rate and p50/p95 latency          | Operational behavior on the chosen dataset/hardware              |

For contact arrays, this evaluator compares the entire array as an unordered set of
strings; a correct partial list is not counted as an exact full-field match. Report
separate contact-level precision/recall if that distinction matters to your workflow.
The evaluator writes aggregated statistics and model hashes without names or NIK values.
The local input manifest itself contains PII and should remain private.

Tune thresholds on the development set and report final numbers on the untouched test
set. Raising thresholds usually increases review workload; lowering them can increase
silent errors. The initial thresholds in this project are not derived from your data.
If silent errors remain high, improve capture quality, evaluate alternative crop strategies,
or fine-tune a recognizer/entity model on consented training data. Treat each model
change as a new version and rerun the same held-out evaluation.
