---
title: Card OCR KTP and Business Cards
emoji: 🪪
colorFrom: blue
colorTo: green
sdk: gradio
sdk_version: 6.27.0
python_version: "3.12.12"
app_file: app.py
pinned: false
short_description: Indonesian KTP and business card OCR with reviewable JSON
---

# Card OCR API — Indonesian KTP and business cards

Deploy this Python API once on your server. Web, Flutter, native iOS, native Android,
and other HTTP clients upload an image and consume the same JSON contract.
The app does not need to install an OCR model. There is no paid OCR API or LLM dependency.

This project extracts printed text. It is not a Dukcapil connection, document-authenticity
check, face match, or proof that a NIK belongs to somebody. A high OCR score is not a
measured probability that an entire field is correct.

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
the [tuning notes](docs/TUNING.md). Version 1.5.0 added the levelled re-read for tilted
pages, small-print retries and label lookalike handling.

## Start locally — no Docker

Install **64-bit Python 3.12**, extract this project, and open a terminal in its folder.
The setup script creates `.venv`, installs the free packages, and checks the bundled models.
You do not need a GPU, API subscription, or separate OCR model download.

macOS / Linux:

```bash
cd card-ocr-api-local-gradio-v1.4
python3.12 setup_local.py
python3.12 run_local.py
```

Windows PowerShell:

```powershell
cd card-ocr-api-local-gradio-v1.4
py -3.12 setup_local.py
py -3.12 run_local.py
```

Open **http://127.0.0.1:7860** for the Gradio upload screen, or
**http://127.0.0.1:7860/docs** for the interactive REST API.
Choose a synthetic example, press **Extract JSON**, and inspect `data` and `fields`.
Stop with Ctrl+C. Setup preserves an existing `.env`; repeat it to install missing packages.

For a smaller API-only installation, run `setup_local.py --api-only` followed by
`run_local.py --api-only`. That mode serves Swagger at **http://127.0.0.1:8000/docs**.
No shell activation is needed. See [local testing and troubleshooting](docs/LOCAL_TESTING.md).

## Test remotely or host the app

| Mode                      | Start / setup                                            | Where OCR runs                                   |
| ------------------------- | -------------------------------------------------------- | ------------------------------------------------ |
| Local interface + REST    | `python run_local.py`                                    | Your computer, port 7860                         |
| Temporary HTTPS share     | `python run_local.py --share`                            | Your computer; use the printed Gradio URL        |
| Hugging Face Gradio Space | Upload this project's source files; entry point `app.py` | The Space server, subject to account eligibility |
| Existing Python server    | `python app.py --host 0.0.0.0 --port 7860`               | That server                                      |

The temporary share URL also exposes `/v1/ocr/ktp`, `/v1/ocr/business_card`, and `/docs`.
It expires after one week or earlier if the local process stops. Use synthetic data for
public learning demos. [Gradio sharing guide](https://gradio.app/guides/sharing-your-app).

**Hugging Face free hosting is account-dependent.** Its current rules require a paid
plan to create ordinary compute Spaces, with a free ZeroGPU exception for eligible
personal accounts. This project uses CPU ONNX inference; ZeroGPU hosting has not been
validated. Check eligibility before choosing hardware or paying for anything.
[Current Spaces rules](https://huggingface.co/docs/hub/spaces-overview).

The package includes the Gradio SDK metadata and dependencies for a Space. Follow
[deployment instructions](docs/DEPLOYMENT.md) and the [free tools guide](docs/FREE_TOOLS.md).
No remote deployment or public share link is created automatically by local setup.

## Make a request

One image, one card, one side per request. Supported formats: JPEG, PNG, WebP.
The default limit is 10 MiB and 20 million decoded pixels. PDF, HEIC, and animated
images are rejected; convert camera HEIC to JPEG on iOS before upload.

```bash
curl -X POST http://localhost:7860/v1/ocr/ktp \
  -H "X-API-Key: YOUR_LOCAL_TEST_KEY" \
  -F "file=@/absolute/path/to/ktp.jpg" \
  -F "mode=accurate" \
  -F "include_raw=false"
```

Omit the header when testing locally with an empty `OCR_API_KEY`. Replace `ktp` with
`business_card` for contact cards. `auto` uses detected field labels and contact patterns
to choose a parser; it can decline an uncertain document type. A contact-containing
document can resemble a business card, so use an explicit type when the user already knows it.

| Form field     | Default               | Meaning                                                                                           |
| -------------- | --------------------- | ------------------------------------------------------------------------------------------------- |
| `file`         | Required              | Image bytes in multipart upload                                                                   |
| `mode`         | `accurate`            | `accurate` or `fast`                                                                              |
| `include_raw`  | `false`               | Include all detected text boxes and OCR scores                                                    |
| `rotation`     | `0`                   | Extra clockwise rotation: 0, 90, 180, or 270; applied after EXIF                                  |
| `phone_region` | Server setting (`ID`) | Country for national phone numbers, e.g. `US`; explicit `+country` numbers keep their own country |

Keep NIK and phone numbers as **strings** in every database and client. NIK must not
be converted to a JavaScript number; 16 digits can exceed exact integer precision.
Dates with an unambiguous printed four-digit year use ISO `YYYY-MM-DD`.

## Consume the JSON safely

The contract has two useful layers:

- `data`: only values that passed the configured acceptance policy. A withheld scalar
  is `null`; a contact list contains only accepted entries.
- `fields`: every candidate, its status, the source text and boxes, and reasons to review.
  Read `candidate` to prefill a correction form. It is not an accepted value.

The following is an abbreviated illustrative response, not a measured accuracy claim:

```json
{
  "schema_version": "1.0",
  "document_type": "ktp",
  "status": "needs_review",
  "needs_review": true,
  "data": {
    "nik": null,
    "full_name": "NAMA CONTOH",
    "birth_date": "1990-08-15"
  },
  "fields": {
    "nik": {
      "value": null,
      "candidate": "9901011508901234",
      "status": "review",
      "ocr_score": 0.94,
      "reasons": ["low_ocr_score"]
    }
  },
  "verification": "ocr_only_not_identity_verification"
}
```

Complete responses generated by the real engine from synthetic test sheets are in
`examples/ktp-response.json` and `examples/business-response.json`.

| Field status | Application behavior                                                         |
| ------------ | ---------------------------------------------------------------------------- |
| `accepted`   | Prefill from `value`; it passed policy, but is not independently verified    |
| `review`     | Show `candidate`, alternatives, and reasons for user correction/confirmation |
| `missing`    | Ask the user to enter the value or retake the photograph                     |

`needs_review` is the document-level routing signal. `status=ok` means the required
fields passed policy and no detected field needs review. Optional fields may still
be missing; validate your own form's required fields as well.
Human-confirmed edits should be stored by your application separately from the
original OCR response. There is no database or confirmation endpoint in this service.

KTP fields: `nik`, `full_name`, `birth_place`, `birth_date`, `gender`, `blood_type`,
`address`, `rt`, `rw`, `village`, `district`, `city`, `province`, `religion`,
`marital_status`, `occupation`, `nationality`, `valid_until`.
`city` excludes the leading KOTA/KABUPATEN header. Printed categories stay Indonesian.

Business-card scalar fields: `full_name`, `company`, `company_alias` (a second name the
company trades under, when the card's own domain spells it; otherwise `null`),
`job_title`, `address` (the company address printed on the card).
Contact arrays: `emails`, `phones`, `websites`, `social_handles`. Each phone result has
a `phone_type` (`mobile`, `landline`, `fax` or `null`), and `data.mobile_phones` lists
the accepted mobile numbers. In `fields`, each contact array contains
field-result objects; in `data`, it contains strings. Phone numbers use E.164 when
valid; extensions use `;ext=123`. Set `phone_region=US` for national US numbers.
Ambiguous numbers retain their printed form in review candidates, without an invented `+62`.
A second landline number printed without its area code (`(021) 5551234, 5551235`) is
completed with the area code printed for the first; `OCR_SHARED_AREA_CODE=false` keeps
it as a review candidate instead.
Websites may receive an `https://` prefix for normalization; no network check is performed.

## Accuracy and efficiency design

1. Decode verified image bytes, respect EXIF orientation, flatten alpha, and cap dimensions.
   When a card is photographed on a contrasting surface with all four edges visible,
   read a flattened, magnified view of the card instead (`OCR_CARD_DETECTION`, both
   modes). If that view does not read as the requested card, the whole photo is read
   as before, at the cost of one extra read. A business card that is held in a hand
   or lies among other things is found around its own print after the first read, cut
   from the full-size upload, flattened and read again; print outside its outline is
   never evidence. A business card photographed sideways or upside down is turned
   upright and read once more.
2. Detect and recognize text with the bundled multilingual PP-OCRv6 small models through
   ONNX Runtime. The model family supports Indonesian. See the [PaddleOCR language table](https://www.paddleocr.ai/latest/en/version3.x/pipeline_usage/OCR.html).
   Fullwidth punctuation from the recogniser is normalized before parsing; `raw_ocr`
   keeps its own code points.
3. Reassemble KTP fields and separate business-card columns using text-box geometry.
   KTP labels are rejoined with values printed across an aligned colon column, and the
   photo block's issuing place and date are kept out of field values.
4. Read original and contrast-enhanced images. A page whose detected text lines are
   tilted by more than about a degree is re-read from a levelled view in `accurate` mode.
   Documents whose median detected text height is below `OCR_SMALL_TEXT_HEIGHT_PX`
   (default 28 pixels) get two extra reads of a magnified text crop, for both card types.
   Disable the retries with `OCR_SMALL_TEXT_RETRY=false` or `OCR_DESKEW_RETRY=false`
   (the retained `OCR_BUSINESS_RETRY=false` also disables the small-print retry). Normal
   documents need two full-image reads; small-print documents need four, a deskewed view
   adds one, a card view that has to be discarded adds one, and two orientation probes
   can add at most two more. A KTP whose identity or address fields still need review
   can add two bounded field-block reads after these passes. A photographed business card needs three: one of the
   photograph to find the card and two of the flattened card. Models are reused
   throughout the request.
5. Business fields require two qualifying readings in `accurate` mode. Explicit labels,
   company suffixes, job patterns and a unique nearby name/title pair establish field
   roles. Exact character and punctuation conflicts remain reviewable. The v1.3 KTP
   single-read exceptions and cross-check settings remain available; see `docs/ACCURACY.md`.
6. Keep source text, boxes, OCR scores, and review reasons. Business `assignment` is
   `label`, `pattern`, `layout`, `contact` or `heuristic`; it describes how the role was
   selected (`contact`: by a printed email address or domain).
   `supporting_passes` identifies the two strongest agreeing reads, whose weaker score
   is the field's `ocr_score`. Scores count only the printed characters of a value:
   the colon after a label and word breaks, the characters the recogniser doubts most,
   do not lower it. A NIK is scored by its weakest digit.

Default thresholds are 0.93 for normal fields and 0.98 for NIK. They are conservative
starting settings, **not calibrated accuracy percentages**. Two processed versions
use the same model and have correlated errors; agreement can still be wrong.

`fast` mode uses one pass and always routes the document to review. It reads twice
more only to turn a KTP whose upright read does not look like one, and once more to set
a sideways or upside-down business card upright. A photographed business card keeps its
one read: the boxes are moved into the flattened card frame and what is not on the card
is dropped. NIK remains
unaccepted without a second reading. Other fields can be available for a fast prefill.
`accurate` is the default when reducing silent errors matters more than latency.

Business cards have arbitrary layouts. A unique name above a recognized job title can
be accepted after two qualifying reads, and so can a line that a personal mailbox at
the company's own host spells out. Legal company prefixes/suffixes, a logotype named by
the card's own domain, and clear street patterns can establish other roles. Isolated
brands, ambiguous people, placeholder company names, uncertain street prefixes and
unreadable contacts remain review candidates.
These are layout heuristics, not a trained entity model or a guarantee of correctness.

The engine is loaded once per process. CPU work runs off the async request loop, with
one inference slot and at most four in-flight OCR requests per process. Upload and
queue timeouts prevent an unbounded backlog. Model files are not downloaded per request.
Use independent processes for parallel inference; each consumes its own RAM.
The Gradio interface shares the REST engine and admission slot; it queues at most four jobs.

`processing.passes[].to_input` maps evidence coordinates into the EXIF-corrected,
resized input canvas (`quality.width` / `quality.height`) before requested rotation.
Use the matrix when drawing overlays for magnified crop passes.

See `docs/ACCURACY.md` for limitations, photo guidance, and a dataset-based evaluation workflow.

## Client examples

| Platform         | Included file                  | What it uses                                    |
| ---------------- | ------------------------------ | ----------------------------------------------- |
| Web / JavaScript | `examples/web-client.mjs`      | `fetch`, `FormData`, cancellation               |
| Flutter / Dart   | `examples/flutter_client.dart` | Dio, byte uploads, cancellation token           |
| Native iOS       | `examples/CardOCRClient.swift` | URLSession async/await, Decodable response      |
| Native Android   | `examples/CardOCRClient.kt`    | HttpURLConnection on Dispatchers.IO, JSONObject |

These are integration source examples, not complete mobile apps. Native builds must
be compiled and tested in your app's Xcode/Android/Flutter environment. Swift uses iOS 15+.
For Android, add INTERNET permission and your project's coroutines dependency.

In production, clients should call your existing authenticated application backend
or gateway, which holds the OCR server key and forwards the image. Never ship a
server-wide secret in a browser bundle, IPA, or APK. The examples accept request headers
so you can reuse your app's gateway authentication. Direct `X-API-Key` calls are useful
for local development and server-to-server requests.

## Run the tests

```bash
python -m pip install -r requirements-dev.txt
pytest -q
RUN_OCR_INTEGRATION=1 pytest -q
ruff check card_ocr scripts tests
```

PowerShell: `$env:RUN_OCR_INTEGRATION="1"; pytest -q`.
Integration tests load the actual models and post synthetic images through FastAPI.
They do not establish accuracy on real KTPs or real business cards.
See `docs/TEST_REPORT.md` for the checks executed when this package was created.

Generate your own synthetic smoke test and evaluate it:

```bash
python -m scripts.synthetic test-output/synthetic
python -m scripts.evaluate test-output/synthetic/manifest.json --output test-output/evaluation.json
```

Build a harder, repeatable corpus with camera-like degradations (tilt, perspective,
blur, JPEG, uneven light, downscale) and inspect accuracy per condition:

```bash
python -m scripts.stress test-output/stress
python -m scripts.evaluate test-output/stress/manifest.json --output test-output/stress/evaluation.json
```

The evaluation report groups field metrics per tag (`tags`), so a change can be read
against the condition it targets. The corpus includes e-KTP-style sheets (aligned
colon column, larger NIK, security background, photo block) and an `on_table` condition
(the card photographed on a desk). `docs/TUNING.md` describes the tuning method and the
measured effect of the v1.5, v1.6 and v1.7 changes.

For useful accuracy numbers, replace these sheets with your own consented, labeled
card photos. The evaluator reports accepted-field precision, acceptance coverage,
candidate matches, error counts, and latency. It writes aggregates without extracted PII.

## Error responses

Errors use `{"error":{"code":"...","message":"..."}}`. The input image, filename,
and OCR text are not included in error messages.

| HTTP status | Examples                                                       | Suggested behavior                         |
| ----------- | -------------------------------------------------------------- | ------------------------------------------ |
| 401         | `UNAUTHORIZED`                                                 | Check server/gateway credentials           |
| 413         | `FILE_TOO_LARGE`, `IMAGE_TOO_LARGE`                            | Reduce image size                          |
| 415         | `INVALID_IMAGE`, `UNSUPPORTED_IMAGE`, `ANIMATED_IMAGE`         | Send a supported still image               |
| 422         | `NO_TEXT`, `DOCUMENT_TYPE_MISMATCH`, `DOCUMENT_TYPE_UNCERTAIN` | Retake or select the correct type          |
| 408         | `UPLOAD_TIMEOUT`                                               | Check connection and upload size           |
| 503         | `SERVER_BUSY`, `OCR_FAILED`                                    | Retry with backoff; inspect service health |

## Project map

| Path                              | Responsibility                                                               |
| --------------------------------- | ---------------------------------------------------------------------------- |
| `app.py` / `card_ocr/demo.py`     | Gradio screen, shared inference, local/Spaces entry point                    |
| `setup_local.py` / `run_local.py` | Cross-platform Python installation and launch helpers                        |
| `card_ocr/api.py`                 | HTTP contract, auth, upload bounds, worker admission                         |
| `card_ocr/engine.py`              | Pinned model loading, checksums, ONNX inference                              |
| `card_ocr/imaging.py`             | Decode, image quality heuristics, contrast and rotation                      |
| `card_ocr/parsers/`               | KTP/business parsing, evidence, validation, candidate resolution             |
| `card_ocr/pipeline.py`            | Pass selection, field acceptance, JSON assembly                              |
| `scripts/`                        | Startup check, synthetic fixtures, degraded stress corpus, dataset evaluator |
| `tests/`                          | Parser, API, and real-engine integration tests                               |

## Sources and licenses

The code here uses [RapidOCR](https://github.com/RapidAI/RapidOCR),
[ONNX Runtime](https://onnxruntime.ai/), and [FastAPI](https://fastapi.tiangolo.com/).
The selected OCR weights are shipped by RapidOCR; preserve its license/model notices
when redistributing installed dependencies. This archive contains application source,
not copied model weights. See `THIRD_PARTY.md`.
