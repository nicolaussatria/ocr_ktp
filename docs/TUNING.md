# Tuning the recogniser on degraded cards

This page records how the accuracy work was measured. It uses synthetic, degraded
sheets only — not photographs of real identity documents — so it cannot state a
real-world accuracy percentage. It shows which signals moved under controlled,
repeatable camera-like conditions, and how to rerun the same measurement.

## v1.7 — business cards photographed by hand

### The report

Business cards came back with wrong or missing values when photographed the way people
photograph them: held in a hand over a keyboard, in front of a screen, on top of the
other cards just scanned. Seventeen such phone photographs of 14 Indonesian cards were
supplied, 12-megapixel, the card filling about a third of the frame. Earlier business
work had used hand-made crops of single cards, which hide the problem.

### What was wrong, and what changed

The v1.6 code on these photographs accepted 101 of 136 printed values correctly and 10
wrongly. Every wrong value had one of four causes.

1. **Print that is not on the card was read as the card.** A telephone number and a
   website came from the card lying behind; a job title from another person's card. The
   silhouette-based card finder of v1.6 needs the whole outline on a plain surface and
   found none of the 17 cards. The card is now located around its own print: the edges
   are straight segments around the largest group of lines sharing one direction
   (`card_ocr/locate.py`). All 17 were outlined, in 25 to 60 ms each.
2. **The tilt was measured on the wrong card.** With one card in front at 1 degree and
   two behind at -25, the median tilt of all lines is -25, and the levelled re-read
   turned the card in front by about 26 degrees. Rows then merged: a company name with the
   address under it, a title in the wrong order. The direction is now the one that most
   of the print shares by area, and the flattened view is level by construction.
3. **The card was read at a third of its recorded detail.** The whole photograph is
   reduced to 2000 pixels, which leaves a held card about 1400 pixels wide with print
   25 to 47 pixels high. The flattened view is cut from the full-size upload: 2000 pixels
   across the card, print 46 to 73 pixels high. The small-print retries no longer run
   on these photographs, so the request is not slower.
4. **Parser rules did not cover what these cards print**: titles such as `GM of
   Commercial` and `Senior Solutions Consultant`, `Jl` without a full stop in the middle
   of an address line, a pictogram read as a character in front of a telephone number,
   a second landline number sharing the first one's area code, a company named only by
   its logo, a name with no title under it. The rules are listed in
   [BUSINESS_CARDS.md](BUSINESS_CARDS.md#v17--cards-photographed-by-hand).

A fifth problem appeared when the photographs were turned for testing. A card
photographed sideways or upside down is still read, each line turned on its own by the
line classifier, with its layout upside down: 31 wrong values on the 17 photographs
turned by a quarter. The engine now reports which lines the classifier turned. Over
confident lines of four characters or more, by area, it turned 0.00 to 0.02 of upright
print and 0.94 to 1.00 of print standing on its head, so the orientation is read off
the first pass and the upload is turned once.

### Measured effect

Same 17 photographs, development machine (Apple Silicon CPU, two inference threads).
"Wrong accepted" counts accepted values that differ from the printed value.

| 17 hand-held photographs, 136 values | v1.6 | v1.7 |
| --- | --- | --- |
| Accepted and correct (accurate) | 101 | **136** |
| Wrong accepted (accurate) | 10 | **0** |
| Documents with status `ok` (accurate) | 1 / 17 | 16 / 17 |
| Accepted and correct (fast) | 102 | **136** |
| Wrong accepted (fast) | 15 | **0** |

The one document still in review prints no company name. Per-field figures are in
[BUSINESS_CARDS.md](BUSINESS_CARDS.md#measured-on-the-17-photographs).

The same photographs were then altered, to see how much of this depends on how they
were taken. v1.7, accurate mode:

| Copies of the 17 photographs | Accepted and correct | Wrong accepted |
| --- | --- | --- |
| Turned a quarter clockwise | 135 / 136 | 0 |
| Turned upside down | 134 / 136 | 0 |
| Turned a quarter anticlockwise | 135 / 136 | 0 |
| Reduced to 1600 pixels, JPEG quality 70 | 134 / 136 | 0 |
| Reduced to 1024 pixels, JPEG quality 60 | 132 / 136 | 0 |

The values not accepted on the copies are held for review, not wrong: a second read
missing, or two reads disagreeing on one character. The outline itself was also
exercised on copies rotated by 12, -25 and 38 degrees and at half size, and is tested on
drawn scenes (`tests/test_locate.py`): a card on a larger rectangle, a two-colour card,
a footer band, two cards side by side.

Timing, back to back on the 17 photographs, twice each: accurate mode v1.6 87 s and
87 s, v1.7 78 s and 76 s (about 4.5 s a photograph instead of 5.1 s). The extra read of
the flattened card costs less than the levelled re-reads and small-print retries it
replaces. Fast mode: v1.6 34 s and 35 s, v1.7 37 s and 38 s (about 2.2 s instead of
2.0 s), for finding and flattening the card.

### Checks against earlier results

- **Synthetic corpus** (120 images, 1560 fields), accurate mode, final code: identical
  to v1.6 on the same machine, 1550 accepted correct and none wrong (KTP 1246 of 1250,
  business cards 304 of 310). Fast mode was last measured identical to v1.6 (1483
  correct, none wrong) before the last changes to the outline and name rules, and was
  not measured again.
- **Earlier real photographs**, also measured before those last changes and not again:
  the five KTP images returned the same values as v1.6 when a KTP was requested.
  In automatic mode the KTP photographed sideways, which v1.6 took for a business card,
  is turned and returns the same 18 values as when a KTP is requested. On the nine
  business-card images one accepted value changed: the second landline number of a
  pair printed with one area code.

### Two rules that had to be tightened

Both read well on the 17 photographs and were wrong elsewhere. They are recorded
because the tests that now pin them look arbitrary without the reason.

- *Accept a domain printed without `www.` when it has a public ending.* On a small image
  an email address whose `@` was read as `o` became such a domain and was accepted as a
  website. A bare domain is now accepted only when its name is the host of an email
  address on the same card.
- *A line that the email mailbox spells is the person's name.* A shop's own mailbox
  (`contohmedia@gmail.com`) spells the logo, and `showroom@` spells "Showroom Contoh".
  Without a title under the line, the mailbox now has to be at the company's own host
  and touch two words of the line; otherwise the line is offered for review.

### Tradeoffs and limits

- These 17 photographs were used to develop the changes; there is no held-out set of
  hand-held photographs. The altered copies vary the capture, not the cards.
- A photographed business card costs three reads in accurate mode (the photograph, the
  flattened card, its contrast-enhanced twin) and one in fast mode. A card that has to
  be turned upright costs one more in either mode.
- The outline needs three partly visible straight edges. Without one the whole
  photograph is read, with only cut-off and turned print left out.
- Whole lines of the card's own size and direction beside the outline are taken for a
  second card, and the photograph is then read whole, as in v1.6.
- `OCR_SHARED_AREA_CODE` now defaults to completing a second landline number. v1.4 to
  v1.6 kept that number as a review candidate on principle; set it to `false` for that.

## v1.6 — real e-KTP layouts and photographed cards

### The report

On real KTP photos `data.nik` and `data.address` were often `null`. The v1.5 corpus could
not show why: its KTP sheets print every row as `NIK : 9901...` with single spaces, and
the recogniser returns such a row as one box. A real e-KTP prints its colons in an
aligned column, the NIK in a larger bold font, and the data over a patterned blue
ground, next to a photo block whose issuing place and date share rows with the fields.

### What was added to the corpus

- Three e-KTP-style KTP sheets (`ktp_ektp_single`, `ktp_ektp_wrapped` with a two-line
  address, `ktp_ektp_student`) with the aligned colon column, larger NIK, indented
  RT/RW rows, a guilloche-like ground and a photo block.
- Two business layouts: `business_icons` (brand column, contact lines led by
  pictograms) and `business_dark` (light print on a dark card, `T.`/`M.`/`E.`/`W.`
  labels).
- One condition, `on_table`: the card photographed on a desk at an angle, filling
  about 60% of the frame, with rounded corners, a shadow and JPEG compression.

12 layouts under 10 conditions give 120 images and 1560 annotated fields. Rebuild it
with `python -m scripts.stress test-output/stress`.

### What was wrong, and what changed

The first run of the v1.5 code on this corpus reproduced the report: on the e-KTP
sheets `full_name` and `address` were `not_found`, and 8 values were accepted wrong.
Details of each cause are in [PARSER_FIXES.md](PARSER_FIXES.md#e-ktp-layout-and-scoring-v16).

1. **Label and value split apart.** Aligned colons put "NIK", "Nama" and "Alamat" 8–10
   glyph heights from their values; the two boxes were split as separate columns and
   the value was dropped. The parser now measures the value column and rejoins them.
2. **Fullwidth colons inside values.** The recogniser returns `：` for a printed colon,
   so `：BANDUNG` was accepted as a birth place. Text is NFKC-normalized before parsing.
3. **Scores measured the wrong characters.** Per-character confidences show the doubted
   characters are word breaks and the colon, not the value. Boxes are now scored on
   their printed characters, and the NIK on its weakest digit.
4. **More agreeing reads lowered the score.** A field is now scored by its two
   strongest agreeing passes instead of the minimum over all of them.
5. **Respacing.** The word-break threshold sat inside the letter-gap range and created
   `SITI N URHALIZA`; it is now relative to the line's own letter gaps. Respacing can no
   longer drop punctuation, never splits digits, and now also covers business cards
   (except contact lines) and lines with digits.
6. **Photographed cards.** When the card outline is visible on a background, the card
   is flattened to a front view at detector resolution before reading
   (`OCR_CARD_DETECTION`, both modes). The card was found on 10 of the 12 `on_table`
   images and on the three tilted or perspective shots of the dark card. It never
   triggered on a sheet that fills the frame. The other two table photos were read
   from the whole image as before.
7. **Fast mode on tilted photos.** Fast mode has one read and no levelled re-read, so
   rows of a tilted card merged. Its boxes are now moved into the levelled frame
   before parsing (no extra read).

Measured along the way, on the same corpus: changes 1, 2, 4 and the word-break
threshold took accepted-correct values from 1430 to 1505 and wrong values from 8 to 1.
(That threshold later proved too strict for photographed print; see "Real photographs".)
Adding card detection and business respacing then exposed the punctuation loss in
respacing (`Jabatan : MarketingManager` became `Jabatan Marketing Manager`), which
cost `business_labeled_small` 11 fields until it was fixed. Character scoring brought
the run to 1545 correct with none wrong.

### Measured effect

Same 120 images, development machine (Apple Silicon CPU, two inference threads).
"Wrong accepted" counts accepted values that differ from the printed value: the
errors an application would not notice.

| Metric (accurate mode) | v1.5 | v1.6 |
| --- | --- | --- |
| Wrong accepted values | 8 | 0 |
| Accepted values that are correct | 1430 / 1560 | 1549 / 1560 |
| Correct candidate proposed (accepted or in review) | 1499 / 1560 | 1560 / 1560 |
| Documents requiring review | 62 / 120 | 30 / 120 |

| Field | v1.5 | v1.6 |
| --- | --- | --- |
| `nik` | 57/70 | 66/70 |
| `full_name` | 102/120 | 118/120 |
| `address` | 86/100 (2 wrong) | 100/100 |
| `birth_place` | 66/70 (4 wrong) | 70/70 |
| `blood_type` | 39/70 | 70/70 |
| `religion` | 62/70 | 70/70 |
| `marital_status` | 64/70 | 70/70 |
| `nationality` | 51/70 | 70/70 |
| `job_title` | 48/50 (1 wrong) | 49/50 |
| `company` | 49/50 | 49/50 |

| Layout / condition | v1.5 | v1.6 |
| --- | --- | --- |
| `ktp_standard` | 178/180 | 178/180 |
| `ktp_female_wrapped` | 178/180 | 180/180 |
| `ktp_photo_column` | 170/170 | 169/170 |
| `ktp_small_print` | 172/180 | 179/180 |
| `ktp_ektp_single` | 137/180 (4 wrong) | 180/180 |
| `ktp_ektp_wrapped` | 145/180 (1 wrong) | 180/180 |
| `ktp_ektp_student` | 153/180 (2 wrong) | 180/180 |
| `business_left` | 67/70 | 70/70 |
| `business_centered` | 48/50 | 49/50 |
| `business_labeled_small` | 58/60 (1 wrong) | 60/60 |
| `business_icons` | 70/70 | 70/70 |
| `business_dark` | 54/60 | 54/60 |
| `clean` | 138/156 (2 wrong) | 156/156 |
| `tilt4` | 143/156 (3 wrong) | 156/156 |
| `tilt8` | 146/156 (1 wrong) | 155/156 |
| `perspective` | 148/156 | 155/156 |
| `blur1.4` | 144/156 | 154/156 |
| `jpeg55` | 141/156 | 156/156 |
| `backlight` | 135/156 | 150/156 |
| `downscale60` | 145/156 (1 wrong) | 156/156 |
| `photo` | 147/156 | 156/156 |
| `on_table` | 143/156 (1 wrong) | 155/156 |

| Metric (fast mode) | v1.5 | v1.6 |
| --- | --- | --- |
| Wrong accepted values | 28 | 0 |
| Accepted values that are correct | 1242 / 1560 | 1483 / 1560 |

Timing: absolute latencies drifted by 15–20% over the session as the machine's load
changed, so v1.5 and v1.6 were timed back to back on the same six documents, twice each
(two KTP, a small-print KTP, a tilted KTP, two business cards). v1.5 took 49–52 s for the
twelve requests; v1.6 took 40–46 s. Breaks the recogniser rated and the extended
respacing cost 0.2–0.6 s per document; reading flattened card views and levelled tilted
pages saves more than that on these photos.

The 11 remaining accurate-mode misses are all withheld values, not wrong ones:

- 4 NIKs whose weakest digit stays below 0.98 in one of the two best reads (`ktp_standard`
  under perspective and blur, `ktp_photo_column` under an 8° tilt, `ktp_small_print`
  under blur). The candidate is correct in every case. The v1.5 line mean had accepted
  three of these; the weakest-digit rule deliberately does not.
- 6 fields of `business_dark` under `backlight`: the global contrast check flags the
  image, and every field is routed to review by policy.
- 1 business name on an `on_table` photo: only one read paired the name with the job
  title below it, and the other read's unlabelled name guess (the sheet's watermark
  line) keeps the field in review.

### Real photographs

Synthetic sheets cannot show everything a phone camera does, so the same code was run on
four consented KTP photos: a tight crop with glare, a card small on fabric, a card turned
by a quarter (also saved as WebP), and a card held in a hand. That makes 5 images and 90
annotated fields, plus a photo without a card. Their transcriptions and results are not
part of this repository.

| Real KTP photos, 90 fields | v1.5 | v1.6 first pass | v1.6 |
| --- | --- | --- | --- |
| Accepted and correct (accurate) | 50 | 47 | **85** |
| Wrong accepted (accurate) | 1 | 4 | **0** |
| Images answered with an error (accurate) | 2 | 2 | 0 |
| Accepted and correct (fast) | 43 | – | **76** |
| Wrong accepted (fast) | 2 | – | **0** |

The first v1.6 pass, tuned only on synthetic sheets, accepted four values without their
printed spaces: its word-break threshold was too strict for photographed print. The
second pass (see [PARSER_FIXES.md](PARSER_FIXES.md#photographed-ktps-v16-second-pass))
calibrated word breaks on both kinds of print. It also anchored rows on the label column,
turned a sideways card instead of rejecting it, required punctuation to agree, and held
an ambiguous block code for review. In fast mode v1.5 accepted one address with its
block code `I-1` misread as `1-1`; v1.6 holds that value for review in both modes.

The five remaining accurate-mode misses are withheld: a lone `-` blood group the text
detector never finds (three images), an address whose two reads disagree on one full
stop, and the address with the ambiguous block code. Nine business-card images, without
annotations, were compared value by value: all 72 values v1.5 accepted are unchanged.
The first v1.6 pass had lost every field on a front-and-back mockup, by cropping to the
back of the card; photos showing two cards are no longer cropped.

### Tradeoffs and limits

- The NIK rule is stricter on digits and looser on punctuation. A NIK is accepted only
  when two reads agree and each read's weakest digit reaches `OCR_NIK_THRESHOLD`.
- Scores no longer count word breaks. Spacing is settled by the recogniser's rated
  breaks (confirmed by the pixel gap), pixel respacing of long lines, and
  spacing-insensitive agreement. A spacing-only error can still reach an accepted
  value; none remained on either set. The break rules were calibrated on four real
  cards and the synthetic sheets, which is a small sample for print this varied.
- Card detection needs all four edges on a surface of a different colour. A card held
  in a hand, cut off, on a similar-coloured surface, or next to a second card is read
  from the whole photo. A flattened view that does not classify costs one extra read
  before the fallback. None of the four real KTP photos met those conditions.
- An address block code read as `1` before a dash or slash is never accepted
  automatically, even when it is right: on printed samples from 17 to 44 pixels of cap
  height, a line reading `I-1` alone always came back as `1-1`, while the same code after `BLOK`
  read correctly. A wrapped address line loses that neighbouring word, and no
  magnification or closer photograph recovers it.
- Fast mode turns a sideways KTP (two extra reads) instead of answering with an error.
- The e-KTP sheets reproduce the layout, not the real card. The real card also has a
  hologram, a printed photo, wear, glare and its own fonts. Measure consented samples of
  your own with `scripts/evaluate.py` ([ACCURACY.md](ACCURACY.md)) before relying on these
  figures or changing thresholds.

## v1.5 — tilted pages, small print and lookalike labels

### Method

In v1.5, `scripts/stress.py` drew seven synthetic sheets (four KTP layouts, three
business layouts) with known printed values; the figures in this section are for those
63 images. v1.6 added five layouts and the `on_table` condition, and regenerating the
corpus produces all 120 images. Each sheet is rendered under these conditions:

| Condition        | Simulates                                          |
| ---------------- | -------------------------------------------------- |
| `clean`          | a flat, sharp capture (control)                    |
| `tilt4`, `tilt8` | a page rotated by 4 and 8 degrees                  |
| `perspective`    | the card photographed at an angle                  |
| `blur1.4`        | slight misfocus                                    |
| `jpeg55`         | messaging-app compression                          |
| `backlight`      | a shadow gradient across the card                  |
| `downscale60`    | a card that fills too little of the frame          |
| `photo`          | tilt + perspective + blur + shadow + JPEG together |
| `on_table`       | the card on a desk, at an angle (v1.6)             |

`scripts/evaluate.py` then posts every image through the real pipeline and reports,
per field and per tag, the metrics that matter for a review-based service:

- **wrong accepted** — accepted values that differ from the printed value: silent
  errors. This is the metric to hold at zero.
- **accepted / acceptance coverage** — how often a field can be used without a human.
- **correct final** — accepted values that are correct (coverage without errors).
- **documents requiring review** — the manual correction workload.

Reproduce the measurement (takes a few minutes on CPU; the corpus is deterministic):

```bash
python -m scripts.stress test-output/stress
python -m scripts.evaluate test-output/stress/manifest.json --output test-output/stress/evaluation.json
```

The report contains a `tags` section with the same field metrics per condition, so a
change can be read against the condition it targets. Use the same corpus for the
baseline and the changed code.

### What changed

1. **Labelled street prefixes were not canonicalized.** "Alamat : JI. Raya Bogor ..."
   was accepted with the recogniser's `JI.` misread, because the v1.5 `Jl.` correction
   ran only on the pattern-matched path. The labelled path now applies the same fixed
   correction.
2. **A single misread glyph in a KTP label lost the field.** "Berlaky Hingga" stopped
   the literal label pattern, so `valid_until` was `not_found`. Labels now accept the
   documented lookalike characters (`l/I/1`, `u/y`, `o/0`, `s/5`, `b/8`, `z/2`); the
   printed value itself is still read from the untouched text.
3. **Closed printed categories fold the same lookalikes.** `LAK1-LAK1` is
   `LAKI-LAKI`, blood group `0` is `O`, `BELUMKAW1N` is `BELUM KAWIN`. Undocumented
   misreads such as `LAKHLAKI` remain unrecognized and withheld.
4. **Indonesian phone labels are contacts.** `Telepon`, `Telp`, `Tlp`, `HP`,
   `Handphone`, `Kontak`, `WA`, `WhatsApp`, `Faks`, and an optional `No.` prefix no
   longer hide an otherwise clear number.
5. **A tilted page is re-read from a levelled view.** A rotated line produces a
   rotated, height-inflated detection box, which breaks row clustering and column
   splitting: adjacent rows merge and a misread label row can be swallowed by the
   field above it. In `accurate` mode the pipeline measures the median tilt of the
   detected lines and, above about a degree, re-reads a levelled view; the tilted read
   stays in `raw_ocr` without contributing evidence. Disable with
   `OCR_DESKEW_RETRY=false`.
6. **Small print is retried for KTP as well as business cards.** When the median
   detected glyph height is below `OCR_SMALL_TEXT_HEIGHT_PX` (default 28), accurate
   mode adds two magnified crop reads. 24 pixels ran short of a second read on several
   small-print sheets; 32 pixels bought no further correct fields but more passes.

The first four changes are parser policy and are described in
[PARSER_FIXES.md](PARSER_FIXES.md). The last two are pass-selection changes in the
pipeline and add reads only when their trigger conditions hold.

### Native crash found while measuring (macOS arm64)

Running the degraded corpus exposed a process-killing fault unrelated to parsing:
`opencv-python 5.0.x` ships the KleidiCV NEON HAL on Apple Silicon, and its resize
kernel segfaults (`EXC_BAD_ACCESS` in `kleidicv_neon_resize_generic_stripe_u8`) when
the same large frame is resized repeatedly. RapidOCR's detection preprocessing calls
`cv2.resize` on every pass, so the fault could kill a long-running server. It was
reproduced deterministically with the bundled models, and neither
`cv2.setUseOptimized(False)` nor `cv2.setNumThreads(0)` prevents it.

The project now pins `opencv-python==4.11.0.86`, the newest line without KleidiCV that
still accepts the pinned numpy. A minimal regression check alternates a magnified frame
and its contrast-magnified twin: with 4.11 it completes twenty large-frame passes where
5.0 faulted four times out of four. Remove the pin when the upstream HAL fault is fixed
and that check stays clean.

### Measured effect

The table compares the v1.4 code and the tuned code on the same 63 images, on the
development machine (CPU, two inference threads). "Wrong accepted" counts accepted
values that differ from the printed value: the errors an application would not notice.

| Metric                              | v1.4 baseline | tuned    |
| ----------------------------------- | ------------- | -------- |
| Wrong accepted values               | 22            | **0**    |
| Accepted values that are correct    | 1476          | **1576** |
| Fields accepted (of 1602 evaluated) | 1498          | **1576** |
| Documents requiring review          | 20 / 63       | 24 / 63  |
| Median latency                      | 2.3 s         | 3.0 s    |
| p95 latency                         | 3.5 s         | 5.8 s    |

Per-condition field results (`correct / evaluated`, wrong accepted in parentheses):

| Condition                       | v1.4      | tuned     |
| ------------------------------- | --------- | --------- |
| `clean`                         | 85/89 (1) | 88/89 (0) |
| `tilt4`                         | 85/89 (1) | 88/89 (0) |
| `tilt8`                         | 64/89 (3) | 87/89 (0) |
| `perspective`                   | 85/89 (1) | 88/89 (0) |
| `blur1.4`                       | 86/89 (1) | 88/89 (0) |
| `jpeg55`                        | 82/89 (1) | 87/89 (0) |
| `backlight`                     | 81/89 (1) | 88/89 (0) |
| `downscale60`                   | 85/89 (1) | 87/89 (0) |
| `photo`                         | 85/89 (1) | 87/89 (0) |
| small-print business (9 sheets) | 36/54 (9) | 54/54 (0) |
| small-print KTP (9 sheets)      | 138/162   | 154/162   |

Latency follows the number of reads: a normal card keeps two (~1–3 s here), a tilted
page adds one levelled re-read, small print adds two magnified reads (four or five
reads in total, ~5 s). `fast` mode is unchanged at one read. The baseline column also
includes the OpenCV downgrade described above, so part of the latency difference is
the dependency change, not only the extra passes.

Documents requiring review did not fall even though coverage rose: the small-print
warning now applies to KTP as well as business cards, so those documents are flagged
for a human look even when every field was accepted. That is a deliberate policy
choice — small print is where the recogniser is least certain, and a review costs less
than a silent error. Disable the retry with `OCR_SMALL_TEXT_RETRY=false` to restore the
v1.4 review profile (and to lose the fields the extra reads recovered).

### Tradeoffs and remaining limits

- Small print and tilted pages need more reads: latency rises only for those
  documents. Flat, fully legible cards keep the two-read path.
- A NIK whose best agreeing reads stay below `OCR_NIK_THRESHOLD` remains a review
  candidate even when the candidate string is correct. Extra passes raise the weakest
  read only when the glyphs actually allow it; the acceptance policy deliberately
  keeps the minimum score, so a confident filter is never invented.
- Quality warnings (`low_resolution`, `possible_blur`, ...) still route a document to
  review regardless of field acceptance. The degraded corpus keeps that behavior; it
  is a policy decision, not an OCR failure.
- The corpus is synthetic. Real cards add glare, fingerprints, print wear, unusual
  fonts and non-standard layouts. Measure your own consented samples with
  `scripts/evaluate.py` as described in [ACCURACY.md](ACCURACY.md) before changing
  thresholds or treating accepted values as final.
