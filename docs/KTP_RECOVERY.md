# KTP recovery for incomplete scans

The reported confirmation screen showed a missing name, a 15-digit NIK, and a
partly read address. The screenshot contains the application result, not the source
KTP photograph or OCR response, so it cannot establish the exact recognition failure
or the correct card values.

## Behavior

In `accurate` mode, the pipeline now checks the resolved NIK, name, birth date,
gender, street address, RT, RW, village, and district after its usual reads. If any
remain missing or uncertain, it crops the corresponding field block, keeps adjacent
rows for context, and reads both the magnified crop and its contrast-enhanced copy.
This also runs on ordinary-sized print, which previously did not qualify for the
small-text retry. There is no retry loop: at most two additional reads per request.
An address held only for `ambiguous_block_character` does not itself trigger a retry.

The extra observations use the existing thresholds, weakest-digit NIK score,
cross-checks, and conflict handling. A complete NIK supported by two qualifying reads
can supersede an invalid short reading. Missing digits are never invented, and
conflicting plausible NIKs remain in review. Evidence and crop-to-input transforms
are available through the existing response fields. The additional pass names are
`ktp_recovery` and `ktp_recovery_contrast`.

If the name label is absent or damaged, exactly one letters-only row between the
recognized NIK and birth rows can supply a name candidate. It must align with the
measured value column. This carries `unlabeled_name_requires_review`, even when
multiple reads agree. Photo captions and date rows cannot supply the candidate.
Once a retry reads the printed name label, only the labeled reads establish name
acceptance; layout-only observations do not count as confirming reads.

Only fields awaiting recovery receive the extra observations. Already accepted fields
keep their complete-image evidence, since context rows can be clipped by the crop.
Target text that touches a crop edge stays in review with
`recovery_text_touches_crop_edge`, so a cut-off name or address cannot silently qualify.

`OCR_KTP_RECOVERY=true` is the default. Set it to `false` to disable these two passes
independently of the existing small-text retry. `fast` mode and business-card pass
selection are unchanged. Restart the API process to load the updated code/settings.

## Application integration

Use `mode=accurate` for KTP uploads. Prefill accepted fields from `data`; when a field
requires review, show `fields.<key>.candidate` with its reasons. Store a NIK as a
string, preserving all digits.

`address` is the street line/block. RT, RW, village, district, city, and province are
separate fields. When composing an address for a confirmation form, add a component's
label only when its value/candidate exists; do not append a bare `KEL` or `KEC` for a
missing component. Keep uncertain components marked for review.

The mobile confirmation screen is outside this repository. This change improves the
API's extraction and candidates; it does not edit that application's dialog.

## Validation

Final checks: `RUN_OCR_INTEGRATION=1 .venv/bin/python -m pytest -q` — **320 passed**;
`.venv/bin/ruff check card_ocr scripts tests` — passed. Dependency deprecation warnings
remain in FastAPI/Starlette/Gradio; no tests failed.

Regression tests cover missing/damaged name labels, rejecting photo/date candidates,
recovering incomplete ordinary-sized reads, two-read NIK support, conflicting complete
NIKs, keeping unresolved short NIKs unchanged, a bounded retry count, and disabling
recovery or selecting fast mode. A real-engine API test renders a synthetic e-KTP
without its name label and checks that the correct printed name remains a review
candidate.

On 7 October 2026, the pre-change baseline was run on all 70 existing synthetic KTP
stress images with default settings (`Settings(_env_file=None)`). Four had their NIK
in review; all other recovery fields were already accepted correctly. Those four
eligible images were then re-run with the final recovery code:

| Synthetic case | NIK before | NIK after | Wrong accepted fields after |
| --- | --- | --- | --- |
| Standard, perspective | Review | Accepted correctly | 0 |
| Standard, blur 1.4 | Review | Accepted correctly | 0 |
| Photo column, tilt 8 degrees | Review | Review | 0 |
| Small print, blur 1.4 | Review | Accepted correctly | 0 |

The other 66 baseline images did not need recovery and were not re-run in this
comparison. Per-case results and diagnostic timings are saved in
[`ktp-recovery-report.json`](../test-output/ktp-recovery-report.json). The extra reads
add latency on eligible scans; the timings were collected with other checks running
and are not a controlled speed benchmark.

These checks use synthetic cards and do not measure accuracy on the reported
photograph. Glare or blur that destroys printed
characters can still require a new photograph or manual correction.
