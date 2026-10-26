# Learn and test locally

Use **64-bit Python 3.12**. No Docker, database, GPU or OCR API subscription is needed.
Python 3.13 is allowed but this package was tested on 3.12. Initial package installation
needs internet and can take several minutes.

## Install and start

From the extracted folder containing `setup_local.py` and `run_local.py`:

| System | Install | Start |
|---|---|---|
| Windows | `py -3.12 setup_local.py` | `py -3.12 run_local.py` |
| macOS / Linux | `python3.12 setup_local.py` | `python3.12 run_local.py` |

Open http://127.0.0.1:7860. Choose a synthetic example, select **Accurate**, and press
**Extract JSON**. Then try the same upload in http://127.0.0.1:7860/docs to learn REST.
Stop with Ctrl+C. Setup preserves an existing `.env` file.

The launcher finds the project's `.venv` directly. No shell activation or PowerShell
execution-policy changes are needed. With your own activated environment, you can use:

```bash
python -m pip install -r requirements.txt
python -m scripts.warmup
python app.py
```

For a smaller install without Gradio, use `setup_local.py --api-only` and then
`run_local.py --api-only`. Swagger then lives at http://127.0.0.1:8000/docs.
Copy `.env.example` to `.env` if manually installing and you need configuration.

## First REST request

macOS/Linux:

```bash
curl http://127.0.0.1:7860/v1/ocr/ktp \
  -F "file=@examples/synthetic-ktp.png" -F "mode=accurate"
```

Windows PowerShell (use `curl.exe` to avoid the old PowerShell alias):

```powershell
curl.exe http://127.0.0.1:7860/v1/ocr/ktp -F "file=@examples/synthetic-ktp.png" -F "mode=accurate"
```

For business cards, use `/v1/ocr/business_card` with `examples/synthetic-business.png`.
Some fields in the business example may remain review candidates; inspect their reasons. The included JavaScript, Swift, Kotlin and Dart clients use the same
contract. They are source examples to integrate into your own app.

For a US national phone number, add `-F "phone_region=US"` to the REST request.
In Gradio, open **Image and output options** and enter `US` in **Phone country**.
Leave it blank for the server default (`ID`). Do not choose a country based only on
where the person lives; use the country the number belongs to.

## Upgrade from v1.3

Stop the old server with Ctrl+C. Extract the entire v1.4 ZIP into a new folder, then
run its `setup_local.py` and `run_local.py` using Python 3.12. Keep all project folders
next to the launch scripts. Copy your `.env` if needed; new settings have defaults.
Check `/healthz` reports `1.4.0` so you know the old server is no longer answering.

## Understand the result

- `data`: values that passed acceptance rules. `null` means withheld or missing.
- `fields`: candidates, evidence, status and review reasons.
- `needs_review`: route the result to a correction form.
- `fast`: one reading; always review. `accurate`: compare readings and require a higher
  score for NIK. Neither mode guarantees correctness or authentic identity.

Keep NIK and phones as strings. Try one sharply focused, tightly framed card at a time.
JPEG, PNG and WebP are accepted. Improve a blurry photo rather than lowering thresholds
just to get filled fields. Use `ACCURACY.md` and the evaluator on your own labeled photos.

## Optional development checks

Run `setup_local.py --dev`, then activate `.venv` or use its interpreter directly:

```bash
python -m pytest -q
RUN_OCR_INTEGRATION=1 python -m pytest -q
python -m ruff check card_ocr scripts tests app.py setup_local.py run_local.py
```

Activation on macOS/Linux: `source .venv/bin/activate`. On Windows use
`.venv\Scripts\python.exe` in place of `python`; enable model tests with
`$env:RUN_OCR_INTEGRATION="1"` in PowerShell. Integration tests use synthetic images.

## Troubleshooting

| Problem | Action |
|---|---|
| Python missing | Install Python 3.12; Windows can use `py -3.12` |
| No compatible binary wheel | Check 64-bit architecture and Python version; use 3.12 on a supported OS |
| Linux `venv` / `ensurepip` missing | Install the distribution's Python 3.12 venv package |
| OpenCV missing `libGL.so.1` | Debian/Ubuntu: install `libgl1` and `libglib2.0-0` |
| Windows ONNX DLL error | Check the Microsoft Visual C++ runtime required by ONNX Runtime |
| Port occupied | `python run_local.py --port 7861` |
| Gradio missing | Re-run setup without `--api-only` |
| SOCKS proxy import error | Install `httpx[socks]` in `.venv` if your network uses SOCKS |
| Model hash mismatch | Reinstall pinned RapidOCR; do not disable checksum validation |
| HEIC/PDF rejected | Convert the card image to JPEG or PNG |
| Uncertain result | Improve the photo and inspect candidates in `fields` |
| Phone cannot reach localhost | Use `--share` or the computer's LAN IP; see `DEPLOYMENT.md` |
| Spaces asks for payment | Check eligibility; local Gradio share is a free testing alternative |

`requirements.lock` records the tested Linux Python 3.12 runtime. `requirements.txt`
pins direct packages and lets pip resolve compatible transitive packages on other
platforms. For exact Linux reproduction, install the lock as well.
