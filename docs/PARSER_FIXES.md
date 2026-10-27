# KTP parser history retained from v1.3

The v1.4 business-card update retains the v1.3 KTP parser and its defaults.
The regression suite exercises these KTP features:

- Split the issuing-place/date column under the portrait from the field column.
- Retain nearby, aligned wrapped name lines and review ambiguous address continuations.
- Recognize merged labels/headers such as `RTRW`, `PROVINSI...`, and `TGILAHIR`.
- Normalize printed categories such as `BELUMKAWIN` and `SEUMURHIDUP`.
- Keep label boxes as evidence while scoring the separately detected value boxes.
- Restore some dropped word breaks using visible blank columns and OCR crop reads.
- Preserve suspect digits, dates, and inconsistent NIK/printed-field readings for review.

These rules are intended for common KTP layouts. They are not an authenticity check,
and one development photograph cannot establish an accuracy percentage.

## Retained settings

| Setting                       | v1.3 / v1.4 default | Behavior                                                                                                                           |
| ----------------------------- | ------------------- | ---------------------------------------------------------------------------------------------------------------------------------- |
| `OCR_SINGLE_PASS_THRESHOLD`   | `0.99`              | KTP fields other than NIK can qualify from one reading at this score. Business accurate mode always requires two qualifying reads. |
| `OCR_STRICT_NIK_CROSS_CHECK`  | `false`             | `true` requires accepted printed date and gender fields before NIK acceptance.                                                     |
| `OCR_RESPACE_WORDS`           | `true`              | Re-read words separated by detected pixel gaps on KTP. Business contact strings are not respaced.                                  |
| `OCR_NIK_CORROBORATES_GENDER` | `true`              | A NIK that passed policy can corroborate an already-read canonical printed gender.                                                 |

Respacing does not resolve all missing word breaks and may still split words
incorrectly. The KTP consensus key tolerates spacing/punctuation differences, as in
v1.3. Business fields use a separate, exact-text resolver in v1.4 so meaningful contact
punctuation cannot disappear during agreement checks.

Review the policy details and limitations in `ACCURACY.md`, and use a separate labeled
test set before changing thresholds or treating OCR output as final data.

## Address fixes (v1.5)

Two reported responses left `data.address` null. They had different causes.

**Business card — the street prefix was flagged forever.** The recogniser returned
"JI. Raya Ciawi Km.8, ..." because the lowercase l of "Jl." and a capital I are the same
glyph. `uncertain_street_prefix` was attached and never cleared, and because every
reading then counted as unreliable, a second reading of the same line automatically
raised `conflicting_readings` on top. One cause, two blocking reasons.

`ADDRESS_RE` has already decided the line opens with the Indonesian street abbreviation,
and that abbreviation is fixed, so `_canonical_street()` now writes the two ambiguous
characters out as "Jl." (or "JL." on an all-capitals line) and drops the issue. Spacing,
the rest of the line and the raw reading in the evidence boxes are untouched. A prefix
that is guesswork rather than a known glyph confusion — "H. Meruya Ilir Raya" — stays
flagged, and that card's address is still withheld.

**Business card — a minority misread vetoed the majority.** Three passes read "Bogor",
one read "Bogoc", and any rival at all raised `conflicting_readings`. A rival is now
dismissed only when it is both outvoted and a near-duplicate of the winner (90%
character similarity, i.e. the same printed line read slightly differently). A rival
holding a genuinely different value still blocks however few passes back it — a test
already pinned that case, and it caught the first, over-broad version of this change.

**KTP — every wrapped address was flagged.** `multiline_address_requires_review` was
added unconditionally. On a KTP the extent is not actually a guess: between "Alamat"
and the next labelled row there is no other field the wrapped line could belong to. The
flag is now raised only when the block is _not_ closed by a recognised label row, or
when it absorbed more than one wrapped line.

Fixing that exposed a worse bug underneath: only ever one wrapped line was appended, so
a three-line address was silently truncated. Until now the unconditional flag had hidden
it behind a review. The block now stays open across further lines, measuring each from
the one above.

**KTP — the photo column merged into a two-box row.** `marital_status` came back as
"KAWIN KOTABANJARMASIN". Column splitting compares a row's gaps against each other,
which needs three boxes; with two it did nothing. A two-box row now also splits on an
isolated gap wider than 8x the glyph height — measured across cards, a label-to-value
gap runs 3.6 to 5.9x, and the jump to the photo column runs 10 to 14x.

Replaying the reported KTP from its own evidence boxes: 16 of 17 fields accepted with
the correct value, address included, up from 12. Across the six business cards, four now
have an accepted address.

**Still withheld, correctly.** On the earlier test KTP the address candidate reads
block "1-1" where the card prints "I-1", and only one pass produced it. On the
low-resolution Nusantara card the street prefix is a genuine guess. Both stay in review.

## Tuning pass (v1.5)

The label and category rules below were tightened after a degraded-corpus measurement
(see `docs/TUNING.md`). The values are still taken from the untouched text; only the
fixed printed words around them became tolerant of documented glyph confusions.

**KTP — one misread glyph in a label used to lose the whole field.** "Berlaku Hingga"
was read as "Berlaky Hingga" and the literal label pattern stopped matching, so
`valid_until` was `not_found`. A label is a fixed printed word; every label now accepts
the same lookalike characters the parser already documented for `Tgl.` (`l/I/1`,
`u/y`, `o/0`, `s/5`, `b/8`, `z/2`). The value after the label is untouched.

**KTP — closed printed categories fold the same lookalikes.** `LAK1-LAK1` is the printed
category `LAKI-LAKI`; blood group `0` is `O`; `BELUMKAW1N` is `BELUM KAWIN`. Only the
listed categories fold. An undocumented misread such as `LAKHLAKI` still counts as
unrecognized and stays withheld, and open text — names, streets, contacts — is never
folded.

**KTP and business — a labelled address skipped the street-prefix fix.** The v1.5
`JI.` → `Jl.` correction ran only on the pattern-matched path, so a card printing
`Alamat : JI. Raya Bogor ...` accepted the misread silently. The labelled path now
canonicalizes the known glyph confusion the same way; genuinely uncertain prefixes
still raise `uncertain_street_prefix`.

**Business — Indonesian phone labels were not contacts.** `Telepon : 0856 7890 1234`
did not match the label list, which only had English forms, so the number was dropped.
`Telepon`, `Telp`, `Tlp`, `HP`, `Handphone`, `Kontak`, `WA`, `WhatsApp` and `Faks` are
now recognized, with an optional `No.` prefix. Postcodes in address lines remain
excluded, and numbers without a visible country code or leading zero keep their
review reason.

## e-KTP layout and scoring (v1.6)

Reported: on real KTP photos `data.nik` and `data.address` were often null. Earlier
synthetic sheets printed every row as `NIK : 9901...` with single spaces, which the
recogniser returns as one box per row. A real e-KTP prints the colons in an aligned
column and the NIK in a larger font. Rebuilding that layout (see `docs/TUNING.md`)
reproduced the report, with three separate causes.

**KTP — short labels lost their values.** With aligned colons, "NIK", "Nama" and
"Alamat" sit 8–10 glyph heights from their values, so the recogniser returns label and
value as two boxes. The v1.5 two-box column rule split them at 8x, as if the value
were the photo block, and the parser only reads a label that starts a segment, so the
value was dropped. On a wrapped address, the second line was then taken as the whole
address (`label_on_previous_row`). The parser now measures the value column: the
left edge of the value boxes that follow label-only boxes, a median across the card.
A label box is rejoined with the next segment when that segment starts in the value
column (within 4 glyph heights) or starts with a colon. Position decides, so a village
printed "DESA SUKAMAJU" stays a value. The gap after a label-only box no longer counts
as a typical gap either: it is as wide as the jump to the photo block and used to hide
that jump, merging "KATHOLIK" with the issuing place "BANDUNG".

The issuing place under the photo is never taken as the value of a label whose own
value the recogniser missed: the row below a label-only row must also start in the
value column.

**KTP and business — fullwidth colons ended up inside values.** The recogniser's
dictionary is shared with Chinese, and it often returns `：` (U+FF1A) for a printed
colon. `strip(" :")` does not remove it, so `birth_place` was accepted as `：BANDUNG`,
`village` as `：KEPUTIH`, and `blood_type` `：O` was unrecognized. Both parsers now work
on an NFKC-normalized copy of the boxes, with CJK commas and full stops and Unicode
dashes mapped to ASCII. `raw_ocr` keeps the recogniser's own code points. On a KTP,
accents are also folded (`DEWÍ` is `DEWI`): e-KTP data is printed without diacritics.
Business cards keep accents.

**KTP — the colon and word breaks decided the score.** RapidOCR's line score is the mean
confidence of every decoded character. Per-character confidences show the doubted
characters are almost always a space (0.52–0.9) or the colon before the value
(0.61–0.87). Neither is part of a value, and agreement already ignores spacing.
`: KAWIN` scored 0.927 where `KAWIN` alone scores 1.0, so short values such as `WNI`,
`O` and `KAWIN` were withheld on every e-KTP. Boxes are now scored on their printed
characters. The NIK is scored by its weakest digit instead: across 140 NIK reads
the line mean passed 0.98 on 122, while one read at 0.985 overall hid a digit at 0.76.
The weakest-digit rule is stricter on digits and ignores the colon.

RapidOCR 3.9.2 pairs those confidences with a space-free character list when it builds
word boxes, so its word and single-character scores are shifted after the first space.
The engine takes the per-character list before that step and keeps word boxes off.

**KTP — extra agreeing reads lowered the field score.** The resolver took the minimum
score over every read of a value. A small-print NIK read at 0.946 and 0.943 by the
full-image passes and 0.992 and 0.991 by the magnified retries stayed in review,
although the retries exist to settle it. A value is now scored by the weaker of its two
strongest passes, as business fields already were. Two passes must still clear the
threshold, and any other clean reading above it still blocks.

**Respacing — wrong word breaks, and lost punctuation.** The fixed 0.18 break ratio sat
inside the letter-gap range (up to 0.20 between upright strokes such as `N|U`), so
respacing could itself create `SITI N URHALIZA`. A break must now be wider than 0.22 of
the line height *and* clearly wider (1.4x) than the letter gaps of the same line.
Respacing also compared its re-read with letters and digits only, so a dropped colon
went unnoticed: `Jabatan : MarketingManager` became `Jabatan Marketing Manager`, and
the label was lost. Only the break positions are now taken from the re-read. Every
original character is kept, and a break is never placed between two digits. With
that guarantee, lines containing digits (`JL. MERDEKA NO.45`) can be respaced too.

**Business — word breaks and glued street prefixes.** Name, company, title and street
lines are respaced as well; contact lines never are. Scalar fields agree when readings
differ only in spacing (`No.12` / `No. 12`), reporting the reading with the most breaks.
Punctuation must still match. `JI.Gatot Subroto` with no space after the prefix is a
street; an email or domain that happens to start with `ji.` is not.

## Photographed KTPs (v1.6, second pass)

A reported photo still returned `data.address: null`. The v1.6 changes were then
checked against four real, consented KTP photos (one tight crop with glare, one card
small on fabric, one turned by a quarter, one held in a hand on a desk) and six
business-card images. Their transcriptions stay outside this repository. Before this
pass, 47 of 90 annotated KTP fields were accepted correctly and 4 wrongly, and the
turned card returned an error.

**Word breaks the recogniser rated but did not decode.** On photographed e-KTP print
the printed spaces are narrow: `MUSTIKAJAYA`, `PEKALONGANBARAT` and a person's two-word name were
accepted without their spaces. The first v1.6 pass had made this worse: its stricter
pixel threshold (0.22 of the line height, tuned on clean synthetic print) no longer split
two lines that v1.5's 0.18 had split. Pixel gaps alone cannot separate the cases (real
word gaps 0.14–0.27, synthetic letter gaps up to 0.19).

The recogniser's CTC output rates a space at every step, even where a letter wins. At
real dropped breaks that rating was 0.012–0.49. Inside words of photographed and
proportional synthetic print it stayed below 0.002; monospace print reached 0.03
(`A|lamat`), because its letters are spaced wide. So a rated break (0.01 or more) is
kept only where the ink also parts. The blank run between the two characters, located
from the CTC step positions, must reach 0.12 of the line height. It must also exceed the
line's own letter spacing (the 90th-percentile gap between unrated letters): by 1.5x for
a rating of 0.05 or more, by 2x for a weaker one. Every real break measured cleared 1.9x;
`A|lamat` reached 1.7x.

Breaks are only placed between letters, or after a colon or comma, never inside numbers
or after the full stop of an abbreviation. `raw_ocr` shows the text with these breaks.
They are applied to full-line reads only. On a magnified word piece of monospace print
the model rated the break in `Kewarganega|raan` at 0.056, where the gap before the `r`
is as wide as a word space, so the respacer re-reads pieces without them. A break confirmed on the whole line
is passed to the respacer, which keeps it.

**Rows anchored on the label column.** Rows on a photographed card can be only 20 px
apart, and the photo block's issuing place and date sit between them. Grouping boxes in
reading order let that text bridge two field rows ("Status Perkawinan: KAWIN" merged into
the occupation). Complete-linkage grouping fixed that, but then the date could claim a
label while pushing that label's value into a row of its own. Rows now form from the
boxes at the field column's left edge first; every other box joins the anchored row it
lines up with best. A layout without a clear left column (a business card, a sideways
read) keeps reading-order grouping.

**A card turned by a quarter.** The upright read of a sideways KTP found digits that
passed for business-card phone numbers. The 90°/270° probes only ran when nothing was
recognised, so the request failed with `DOCUMENT_TYPE_MISMATCH`. They now also run when a
KTP was requested and the read does not look like one.

**Candidate ranking.** Two passes reading a garbled second address line at 0.55–0.70
outranked one pass reading it at 0.96, so the review form showed the garbled one.
Readings that cleared the threshold now count before readings that merely exist.

**Punctuation is part of an address.** KTP readings group on letters and digits only, and
the resolver displayed whichever member scored highest. One pass read `NO.5A` and
another `NO 5A`; the second was accepted. Readings still group, but when their
punctuation differs and no single form was read twice, the field gets
`punctuation_differs`. The form with more reads, then more marks, is proposed.

**A block code the model reads as a digit.** The reported address prints block `I-1` and a
house number on the wrapped second line. Every pass, and every re-read variant tried (padding,
magnification, contrast, channel selection, denoising, sharpening), returned
`1-1`, most at 0.93–0.99. More passes would only have confirmed it, so none were
added.

Printed samples across sizes and weights show why. A line reading `I-1` on its own comes
back as `1-1` at every size tried, from 17 to 44 pixels of cap height; magnification
cannot recover what the pixels never held, and a closer photograph does not settle it
either. The same characters after the word `BLOK` are read correctly at nearly every
size: the model leans on the neighbouring word. A wrapped address line loses that
neighbour, which is exactly this card. The bias runs one way only — a printed `1-1` was
never read as `I` in any sample.

So a one-character block code read as `1` (or `l`) before a dash or slash raises
`ambiguous_block_character`, as does a lone `I` or `l` after one, and a block code read
as `I` is kept. This address stays in review with its best reading proposed, for a
one-character correction rather than a silent error.

**A misread birth label.** `TempaV T gI Lahir` and `Tempat T gi Lahir` failed the label
pattern. `Lahir` survives these misreads and ends no other KTP label, so a short label
ending in it is accepted; `i` also joins the `l`/`I` lookalikes of label words.

**Two cards in one photo.** A front-and-back mockup was cropped to the back of the card,
which still classified as a business card by its website, and every contact on the front
was lost. When the colour mask shows two similar-sized objects, card detection now
steps aside and the whole image is read.

After this pass: 85 of 90 fields correct, none wrong. The five misses are a lone `-`
blood group the detector never finds (three cards) and the two addresses above, both
in review with their candidate shown.
