# Local sharing and server deployment

Web, Flutter, native iOS and native Android all use the same REST API. Python and the
models run on the server; each client uploads a card and reads JSON. No Docker setup
is required. Start with the included synthetic images.

## Temporary free HTTPS URL

After local setup, run `python run_local.py --share` (Windows: `py -3.12 run_local.py --share`).
Gradio prints an `https://...gradio.live` address. Open it on your phone or use it as the
base URL in any included client. The REST paths and JSON contract stay the same:

```bash
curl https://YOUR-LINK.gradio.live/v1/ocr/ktp \
  -F "file=@examples/synthetic-ktp.png" -F "mode=accurate"
```

The share service proxies requests to your computer. Keep it awake and the process
running. Links expire after one week; restarting creates a new link. Outbound access
is required and corporate firewalls may block the tunnel. This is a temporary demo,
not independent server hosting. [Gradio sharing guide](https://gradio.app/guides/sharing-your-app).

To restrict access, set `OCR_API_KEY` in `.env` and restart. The Gradio login uses
username `learner` and the API key as its password by default. Optionally set
`OCR_UI_USERNAME` and a separate `OCR_UI_PASSWORD`. REST clients still send `X-API-Key`.
A UI password alone does not protect REST; configure `OCR_API_KEY` too. With empty
credentials the demo is public. Use synthetic cards for public learning demos.

## Hugging Face Spaces: Gradio SDK

Hosting policy checked on 11 September 2026:

- Ordinary Gradio compute Space creation currently requires PRO, Team or Enterprise.
  CPU Basic has no hourly hardware charge, but the account plan requirement applies.
- Free personal accounts in good standing with verified email and an account older
  than 30 days can host up to two ZeroGPU Spaces.
- This project uses CPU ONNX Runtime. It is prepared for a normal Gradio Space;
  ZeroGPU compatibility has not been tested. No GPU decorator is needed by this engine.
  Do not assume ZeroGPU eligibility guarantees suitable hosting for this CPU app.

Check [Spaces rules](https://huggingface.co/docs/hub/spaces-overview) and
[ZeroGPU conditions](https://huggingface.co/docs/hub/spaces-zerogpu) in your account.
If no suitable free option is available, use the local share mode above. Do not select
paid hardware just to follow this tutorial.

Once your account has access to suitable Gradio hosting:

1. Create a Space and choose **Gradio** as the SDK. Choose hardware available under
   your intended plan. CPU inference is sufficient; CPU Basic has 2 vCPU and 16 GB RAM.
2. Upload the **contents** of `card-ocr-api`, not the ZIP or an enclosing folder. Required:
   `README.md`, `app.py`, `requirements.txt`, `requirements-api.txt`, `packages.txt`,
   the complete `card_ocr/` directory, and both synthetic PNGs in `examples/`.
   Keep their relative paths. The other source, documentation and tests can also be uploaded.
3. The root README supplies Gradio 6.27.0, Python 3.12.12 and `app_file: app.py`.
   Spaces installs the self-contained `requirements.txt` and OS libraries from
   `packages.txt`, then runs
   `app.py`. It binds to `0.0.0.0:7860` when Spaces supplies `SPACE_ID`.
4. In **Settings → Secrets**, set `OCR_API_KEY` if access should be restricted.
   Optionally set `OCR_UI_PASSWORD` and `OCR_UI_USERNAME`. Never upload `.env`.
   Set `OCR_CORS_ORIGINS` as a JSON array variable for separate browser clients.
5. Wait for build/startup. Open the Space's direct `https://...hf.space` URL and try a
   synthetic example. For login, open the direct URL in its own tab; iframe cookie
   restrictions can otherwise interfere with Gradio authentication.
6. Check `/readyz`, open `/docs`, and send a multipart request to `/v1/ocr/ktp` or
   `/v1/ocr/business_card`. Use the direct `hf.space` base URL in your clients,
   not the `huggingface.co/spaces/...` repository page.

### Upload from the command line

Uploading the whole project folder would also publish `.env`, card photographs kept
beside the code and test output. `scripts/deploy_space.py` uploads a fixed list of
files instead; anything not on the list stays on your computer.

```bash
pip install -U huggingface_hub          # provides the hf command
hf auth login                           # once per computer
python -m scripts.deploy_space <user>/<space> --dry-run    # shows the files, sends nothing
python -m scripts.deploy_space <user>/<space>              # uploads; the Space rebuilds
hf spaces wait <user>/<space>           # until it is RUNNING, or reports a build error
```

Create the Space first if it does not exist:
`hf repos create <user>/<space> --type space --space-sdk gradio --public` (or
`--private`). Then check the new version and the models:

```bash
curl https://<user>-<space>.hf.space/healthz     # {"status":"ok","version":"..."}
curl https://<user>-<space>.hf.space/readyz
hf spaces logs <user>/<space> --build            # if the build failed
```

To require a key, add it as a secret and restart; never upload it in a file:
`hf spaces secrets add <user>/<space> -s OCR_API_KEY=<a long random value>`. Without
`OCR_API_KEY` anyone who knows the address of a public Space can use it.

Private Spaces also apply provider access controls; the application key does not
replace those. Free hardware can sleep when idle, so allow startup time on first use.
Disk storage is ephemeral. This app needs neither persistent uploads nor a database.
[SDK configuration](https://huggingface.co/docs/hub/spaces-config-reference) and
[dependency installation](https://huggingface.co/docs/hub/spaces-dependencies).

## Any existing Python server

Install 64-bit Python 3.12 and extract the source. On Debian/Ubuntu, install `libgl1`
and `libglib2.0-0` if OpenCV reports them missing. Then run:

```bash
python3.12 setup_local.py
.venv/bin/python app.py --host 0.0.0.0 --port 7860
```

For REST only, install `requirements-api.txt` and run:

```bash
.venv/bin/python -m uvicorn card_ocr.api:app --host 127.0.0.1 --port 8000 --workers 1
```

Use your host's process manager to keep the service running. Place an HTTPS reverse
proxy or authenticated app backend in front of it. `deploy/nginx.conf.example` targets
API-only port 8000. Start capacity planning around 2 CPU cores and 2–4 GB RAM, then
measure your actual workload. A GPU is unused by this package. Tiny free instances
may not fit the model and image memory; no remote host was benchmarked here.

## Client networking and keys

A phone's localhost refers to the phone. Use a server/share HTTPS URL, or run
`python run_local.py --host 0.0.0.0` on a trusted LAN and use the computer's LAN IP.
Android emulators normally reach the host through `10.0.2.2`. LAN plain HTTP may
require development-only platform permissions; the HTTPS share URL avoids that.
Convert iOS camera HEIC images to JPEG before upload.

For a separate browser app, set for example:

```dotenv
OCR_CORS_ORIGINS=["http://localhost:5173"]
```

Restart after changes. CORS is not authentication. For production, keep the OCR key
in your authenticated application backend and forward uploads from there. A shared
secret embedded in JavaScript, an IPA or an APK can be extracted.

## Runtime and data handling

One process loads one engine and uses one inference slot for REST and Gradio. REST
admits up to four concurrent requests, with a 20-second upload timeout and a default
3-second inference-slot wait. Gradio queues up to four waiting jobs. Cancellation does
not interrupt native inference. Additional workers consume additional RAM.

There is no result database; the application does not log extracted text. REST uploads
are bounded and closed after use. Gradio uses temporary files and cleans up every
600 seconds for files older than 600 seconds; active/recent files may live longer.
Crashes can leave files behind, so use ephemeral hosting and remove test caches when
needed. This is not secure erasure. Gradio run history and analytics are disabled.

Responses use `Cache-Control: no-store`. The entire response can contain personal data,
including source evidence in `fields`. Avoid body logging and never commit real KTPs,
credentials, private datasets or `.venv` to a public repository.

`/healthz` checks the process; `/readyz` checks models; `/docs` and `/openapi.json`
describe REST. All OCR weights ship with the installed RapidOCR wheel and are checked
at startup. Inference makes no paid API calls. Installing packages, hosting and share
tunnels have separate network requirements. No remote deployment was performed here.
