# Changelog

What changed in each version of the Card OCR API, newest first. The measured results
behind each release are in [docs/TEST_REPORT.md](docs/TEST_REPORT.md).

## 1.8.0

Version **1.8.0** tells the mobile number on a business card from the office line and
the fax: each number in `fields.phones` has a `phone_type`, and `data.mobile_phones`
lists the accepted mobile numbers. A second name the company trades under, printed
beside its legal name and spelled by the card's own domain, is reported as
`company_alias`. The company address is `address` and the title is `job_title`, as before.

KTP recovery in `accurate` mode now re-reads the identity/address block when key
fields are still missing or uncertain, even on normal-sized print. This adds at most
two passes, controlled by `OCR_KTP_RECOVERY` (default `true`). A readable name whose
label was missed can appear as a layout-based review candidate. A short NIK is never
padded or completed from a birth date; it still needs two qualifying 16-digit reads
and the existing cross-checks. See [KTP recovery behavior](docs/KTP_RECOVERY.md).

## 1.7.0

Version 1.7.0 reads business cards photographed by hand. The card is found around
its own print, cut from the full-size upload and flattened, so the keyboard, the screen
and the other cards in the picture are no longer read as part of it; a card photographed
sideways or upside down is set upright first. The printed email address confirms which
line is the person's name, and the card's own domain confirms the company in its logo.
On 17 hand-held photographs of 14 Indonesian cards (136 printed values) accepted
correct values went from 101 to 136 and wrong accepted values from 10 to 0, in `fast`
mode from 102 and 15 to 136 and 0. A requested KTP is read as in 1.6.0; with
`document_type=auto`, a KTP photographed sideways is now turned upright and recognised
as one. See [business-card changes and sample results](docs/BUSINESS_CARDS.md).

## 1.6.0

Version 1.6.0 targeted real e-KTP layouts and photographed cards. NIK and address
are no longer lost when the card prints its colons in an aligned column. Fullwidth
colons from the recogniser no longer end up inside values. Fields are scored on their
printed characters (a NIK on its weakest digit), and a card photographed on a desk is
found and flattened before reading. Word breaks dropped on photographed print are
restored from the recogniser's own ratings, a sideways KTP is turned instead of
rejected, and an address block code this model misreads (`I-1` as `1-1`) is held for
review. On four real KTP photos (90 fields) accepted correct values went from 50 to 85,
with none wrong. On the local degraded corpus wrong accepted values went from 8 to 0
(28 to 0 in `fast` mode), and the NIK was accepted on 66 of 70 cards instead of 57. See
the [tuning notes](docs/TUNING.md).

## 1.5.0

Version 1.5.0 added the levelled re-read for tilted
pages, small-print retries and label lookalike handling.
