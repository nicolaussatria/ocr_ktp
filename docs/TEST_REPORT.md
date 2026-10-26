# Validation report — v1.8.0

Validated 7 October 2026 on the same machine and software as v1.7.0 below.

`python -m pytest -q`: **303 passed**, 4 skipped; with `RUN_OCR_INTEGRATION=1`, which
adds the real-model integration tests, 307 passed. New tests cover the phone type from
the number and from the label, labels and numbers that disagree, numbers sharing a
label, numbers with no fixed type, the type agreed across reads, and
`data.mobile_phones`. For the company alias they cover a trading name over a legal
name, the logo when the name is not written out, short forms of the legal name, lines
the domain does not spell or spells only at the start, a card without a legal name, a
line that may be the person's name, and two reads that differ. Each alias rule was
also taken out in turn; a test failed every time.
`docs/openapi.json` was regenerated: `FieldResult` gained `phone_type`; nothing else
changed apart from the version (`data` is a free-form object, so `company_alias` needs
no schema change). The example responses in `examples/` were regenerated from the
synthetic sheets with the real engine; their accepted values are unchanged, and the
business-card example now carries an empty `company_alias`.

On the 17 hand-held business-card photographs (accurate mode) all 41 printed telephone
numbers got the right type and `data.mobile_phones` was exact on every photograph. All
136 printed values were still accepted correctly, none wrong.

One of the 17 photographs prints a second company name. It was accepted as
`company_alias` in `accurate` mode, in `fast` mode and with `document_type=auto`; no
alias was accepted or proposed for the other 16. With that value the check is 137 of
137 correct, none wrong, in all three runs. The synthetic stress sheets print no second
company name, so they were not run again.

# Validation report — v1.7.0

Validated 2 October 2026 on macOS arm64 (Apple Silicon), CPython 3.12.0. RapidOCR
3.9.2, ONNX Runtime 1.30.0, OpenCV 4.11.0, the same PP-OCRv6 small models and
orientation classifier; two ONNX CPU threads. Direct dependencies and model hashes did
not change. v1.6.0 was the starting point.

## Automated checks

`RUN_OCR_INTEGRATION=1 python -m pytest -q`: **279 passed**, 19.6 seconds, with 34
upstream deprecation warnings. Without the environment variable: 275 passed, 4 skipped.

New tests cover the card outline on drawn scenes (a held card among other things, a
two-colour card, a footer band, a card lying on a larger rectangle, two cards side by
side, a square object, a flat scan), the flattened view cut from the full-size upload,
lines cut off by the frame, the orientation read off the line classifier, and the
pipeline around them: the flattened view in accurate mode, the single read moved into
it in fast mode, the fallback when the view reads nothing, a silhouette view narrowed to
the card in front, a sideways card in both modes, and a requested KTP left alone. Parser
tests cover roles against offerings, pictograms in front of numbers, the shared area
code and its setting, streets printed after the building, numerals read with a
lowercase l, names settled by a mailbox and the mailboxes that settle nothing,
logotypes named by the card's own domain, and bare domains.

The tests in `tests/test_business_indonesia.py` that held names and numbers read from
real cards were rewritten with made-up ones; what each test checks is unchanged.

`ruff check card_ocr scripts tests app.py setup_local.py run_local.py`: passed.
`pip check`: no broken requirements. `python -m compileall`: passed.
`docs/openapi.json` differs from v1.6.0 only in the version, `1.7.0`. The response
schema is unchanged: `assignment` gained the value `contact`, and the per-line
classifier result is internal and never serialized.

## Hand-held business-card photographs

Seventeen phone photographs of 14 Indonesian business cards (136 printed values),
evaluated with v1.6.0 and v1.7.0 on the same machine. Accurate mode: 101 → 136 accepted
correct, 10 → 0 wrong, 1 → 16 documents `ok`. Fast mode: 102 → 136 correct, 15 → 0
wrong. Copies turned by a quarter either way and upside down: 135, 135 and 134 of 136
correct, none wrong. Copies reduced to 1600 and 1024 pixels: 134 and 132 correct, none
wrong. The photographs were used during development; they are not a held-out set. The
images, transcriptions and extracted values are not in this archive. Details are in
[TUNING.md](TUNING.md#v17--business-cards-photographed-by-hand).

Timing, back to back on the 17 photographs twice: accurate mode v1.6 87 s and 87 s,
v1.7 78 s and 76 s; fast mode v1.6 34 s and 35 s, v1.7 37 s and 38 s.

## Earlier corpora

The degraded synthetic corpus (120 images, 1560 fields) in accurate mode with the
final code: 1550 accepted correct and none wrong, identical to v1.6.0 on this machine
(KTP 1246 of 1250, business cards 304 of 310). Fast mode and the real KTP and
business-card photographs of the v1.6.0 report were compared before the last changes to
the outline and name rules and not again: fast mode identical (1483 correct, none
wrong); KTP values identical when a KTP is requested; one business value changed, the
second landline number of a pair printed with one area code, now completed.

# Validation report — v1.6.0

Validated 17 September 2026 on macOS arm64 (Apple Silicon), CPython 3.12.0. RapidOCR
3.9.2, ONNX Runtime 1.30.0, OpenCV 4.11.0, the same PP-OCRv6 small models and
orientation classifier; two ONNX CPU threads. Direct dependencies and model hashes did
not change. v1.5.0 was the starting point.

## Automated checks

`RUN_OCR_INTEGRATION=1 python -m pytest -q`: **166 passed**, 18.5 seconds, with 34
upstream deprecation warnings. Without the environment variable: 162 passed, 4 skipped.

New regressions cover the e-KTP layout (label and value in separate boxes across an
aligned colon column, wrapped addresses, values starting with a label word, the photo
block's place and date, a separate colon box), fullwidth and accented recogniser
output, per-character and weakest-digit scoring, two-strongest-pass resolution,
word-break detection against letter gaps, punctuation-preserving respacing, card
localisation and its fallback, fast-mode levelling, business spacing agreement, glued
street prefixes and contact-line exclusion from respacing. The second pass added row
anchoring against photo-block text, rated word breaks and their pixel confirmation
(including monospace print), kept breaks during respacing, candidate ranking by
qualifying reads, punctuation agreement, the ambiguous block code, the misread birth
label, sideways-card probes in both modes, and the two-card photo. The first e-KTP layout
tests were also run against the v1.5 parser, where 9 of 13 fail as expected.

`ruff check card_ocr scripts tests app.py setup_local.py run_local.py`: passed.
`pip check`: no broken requirements. `python -m compileall`: passed.
`docs/openapi.json` was regenerated from the app; the only change is the version,
`1.6.0`. The response schema is unchanged: the new per-character scores are internal
and never serialized.

## Degraded synthetic corpus

`scripts/stress.py` (12 layouts under 10 conditions, 120 images, 1560 annotated fields)
was evaluated with the v1.5.0 and v1.6.0 code on the same machine. Accurate mode: wrong
accepted values 8 → 0, accepted correct values 1430 → 1549. Fast mode: wrong accepted
values 28 → 0, accepted correct values 1242 → 1483. Per-field and per-condition figures
are in [TUNING.md](TUNING.md). These are synthetic sheets, not photographs of real
cards, and do not establish a real-world accuracy percentage.

## Real photographs

Four consented KTP photos (one also as WebP; 90 annotated fields) and a photo without a
card were evaluated with v1.5.0 and v1.6.0. Accurate mode: 50 → 85 accepted correct,
1 → 0 wrong, and the sideways card no longer fails. Fast mode: 43 → 76 correct, 2 → 0
wrong. Nine business-card images were compared value by value: the 72 values v1.5
accepted are unchanged. The images, transcriptions and extracted values are not in
this archive. Details are in [TUNING.md](TUNING.md#real-photographs).

Timing, back to back on the same six synthetic documents twice: v1.5 49–52 s, v1.6
40–46 s. Absolute latencies drifted 15–20% during the session as machine load changed.

# Validation report — v1.4.0

Validated 15 September 2026 on Linux x86_64, CPython 3.12.14. RapidOCR 3.9.2,
ONNX Runtime 1.30.0, PP-OCRv6 small detection/recognition and the bundled orientation
classifier; two ONNX CPU threads. The submitted v1.3 archive was the starting point.
Direct dependencies and model hashes did not change.

## Automated checks

`RUN_OCR_INTEGRATION=1 python -m pytest -q`: **96 passed**, 18.48 seconds on the final
full run. The suite emitted 34 upstream deprecation warnings; no tests failed.

The suite covers KTP and business parsers, REST behavior, shared Gradio/REST inference,
authentication, upload limits, invalid images, rotation, and real-model image-to-JSON
integration. Four tests run actual OCR on synthetic images, including a queued Gradio
upload. Other tests use deliberate OCR doubles for deterministic error cases.

New business regressions cover company suffixes and Indonesian jobs, large logos near
small print, distant columns, multiple person blocks, multiline addresses, excluding
postcodes from phones, extensions, ambiguous national numbers, missing area codes,
invalid number candidates, social handles, template text, punctuation-sensitive
agreement, correlated passes, coordinate transforms and bounded small-print retries.
Both REST and Gradio tests verify forwarding `phone_region=US`.

`ruff check card_ocr scripts tests app.py setup_local.py run_local.py`: passed.
`pip check`: no broken requirements. Python bytecode compilation and JavaScript syntax
checks passed. JavaScript multipart construction was checked with a mock transport,
including the optional country parameter and request-error behavior.
API `/healthz` and OpenAPI metadata were separately checked to report `1.4.0`.

The share-mode test runs Gradio's launch configuration but intercepts network startup.
It verifies registered routes, authentication and lifecycle; it does not establish that
a public tunnel or a remotely deployed server is reachable.

## Actual OCR on the six supplied business-card images

All six images were read before and after development with the same pinned models.
The primary printed name was manually transcribed for comparison. The following are
results on the development examples, **not a held-out accuracy estimate**. Additional
fields were inspected to check the specific reported failures, not to produce a complete
field-level accuracy benchmark. The images and their extracted private details are not
included in this archive.

| Input | Main improvement observed | Remaining review / missing information | Final time; full OCR passes |
|---|---|---|---|
| `8.jpg` | Name, company and job accepted; multiline street candidate retained; telephone extension preserved | Street prefix read as `JI.` instead of `Jl.` | 1.77 s; 2 |
| `21415_577186_27631_image.jpg` | Name and company separated from other columns; magnification recovered the job title | Street OCR varies; second short landline needs an area code | 3.60 s; 4 |
| `images.jpeg` | Person selected instead of the company placeholder; job recognized | Company is placeholder text; invalid phone retained; generic location text cannot be assigned as an address | 2.02 s; 4 |
| `IMG_8627-scaled-510x286.jpg` | Name/job accepted; brand and address candidates recovered | Very small text causes email/domain and street conflicts; brand remains uncertain | 1.27 s; 4 |
| `modern-geometric-…_screen.jpg` | Name selected instead of company placeholder; street and email accepted; postcode excluded from phones | Decorative bar read as `I` before job; company placeholder; national phones need the correct country | 0.78 s; 2 |
| `simple-real-estate-business-card-template.jpg` | Person selected instead of logo; job/street accepted; social handle separated from email | Logo's company role needs review; example phone number is invalid/ambiguous | 1.56 s; 2 |

The primary name matched the printed name and passed policy on **all six development
examples**. In the unmodified v1.3 run, none of the six names was accepted, and four
primary name candidates selected a logo/company or mixed-column text instead.
This is a narrow development-case comparison, not a claim of 100% name accuracy.

The US-card test was repeated with `phone_region=US`: both national numbers normalized
to `+1`. With default ID they stayed printed review candidates, rather than wrongly
accepted `+62` numbers. Postcodes from the supplied address lines no longer appeared
as phone candidates. The existing extension printed as `ex 123` was preserved as
`;ext=123` in the appropriate telephone result.

All six documents still routed to review because at least one relevant field or image
quality warning remained. Do not interpret more accepted fields as independent identity
or business verification. Crop one card/side per request; several supplied images show
multiple sides or stacked cards, which this API does not reliably separate.

These times are single runs in a shared execution environment, excluding engine
construction but including parsing/preprocessing. They are not throughput, p95 latency,
or hardware-sizing measurements. Large, readable cards used two full OCR passes.
The small-print path used four; optional orientation probes can raise the total to six.

## KTP and synthetic examples

The supplied KTP photograph was checked again with the retained v1.3 KTP policy.
The issuing footer stayed out of religion/marital fields, the name included its wrapped
line, lifetime validity normalized correctly, and the uncertain address stayed in review.
No KTP accuracy percentage is inferred from this one photograph.

`examples/ktp-response.json` and `examples/business-response.json` were regenerated
with the actual models from the included synthetic sheets. These demonstrate the
current JSON contract and carry no real identity data. They are not real-photo accuracy
fixtures. The original v1.3 KTP regression tests also pass.

## Not validated

- Accuracy/false-accept rates on a separate representative dataset.
- Sustained load or performance/RAM use on the user's server.
- Native Swift/Kotlin/Flutter compilation, macOS/Windows installation, or camera capture.
- Visual browser interaction, an actual public Gradio tunnel, or a Hugging Face build.
- Automatic isolation of multiple cards or association of their front/back sides.
- Hosting-account eligibility, deployment, TLS or production gateway configuration.

The project runs as a local Python service and includes hosting instructions. It has
not been deployed to a remote server. Use the evaluator and `ACCURACY.md` to validate
representative data before relying on automatic acceptance.
