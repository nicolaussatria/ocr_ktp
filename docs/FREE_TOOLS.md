# Free tools for learning

Checked on 11 September 2026. Start with **Python 3.12, the included Gradio screen and
Swagger UI on your computer**. No cloud account or credit card is needed for local OCR.
Your computer provides the CPU and RAM. The engine has no per-request service charge.

| Tool / option | Purpose | Cost / limit |
|---|---|---|
| Python + venv | Run an isolated project environment | Free; used by the setup script |
| RapidOCR + ONNX Runtime | Text detection and recognition on CPU | Open source; no paid OCR API |
| Gradio | Upload images and inspect JSON | Open source; included in full install |
| FastAPI Swagger UI | Test REST and inspect its schema | Included at `/docs` |
| VS Code | Edit and explore source code | Free editor; paid extensions unnecessary |
| Bruno Open Source | Save repeatable HTTP requests | $0 edition; paid editions optional |
| Gradio share link | Test from a phone using an HTTPS URL | Free proxy; expires after a week; computer stays on |
| Hugging Face Spaces | Run a Gradio app on a server | Account-dependent eligibility; details below |

Use the synthetic PNGs in `examples/` for initial tests. No paid OCR provider, LLM,
annotation service or cloud database is needed. Swagger is sufficient to start;
Bruno is optional when you want saved request collections.

## Hosting choice

**Local** is the recommended first step and keeps real private photos on your computer.
Package installation needs downloads, but OCR makes no external inference requests.

**Gradio share** is convenient for mobile/web integration while your laptop stays on.
Run `python run_local.py --share`. Both UI and `/v1/ocr` routes use the printed URL.
This is a temporary proxy, not remote compute. Use synthetic data on public demos.
[Sharing rules](https://gradio.app/guides/sharing-your-app).

**Hugging Face Spaces** is suitable for server hosting if your account can create a
compatible Space. Current ordinary compute Space creation requires a paid plan. Free
personal accounts with verified email, good standing and age over 30 days can host up
to two ZeroGPU Spaces. This CPU ONNX project has not been validated on ZeroGPU.
CPU Basic's lack of hourly hardware charges does not remove account plan requirements.
Check the creation screen before relying on zero-cost hosting.
[Spaces rules](https://huggingface.co/docs/hub/spaces-overview),
[ZeroGPU eligibility](https://huggingface.co/docs/hub/spaces-zerogpu).

**Render Free** offers native Python web services, but low memory/CPU budgets may not
fit OCR plus Gradio. Services sleep after 15 minutes without traffic and share 750
free running hours per workspace each month. This project was not tested on Render;
local sharing is the more predictable first test.
[Render free limits](https://render.com/docs/free).

The Gradio SDK configuration and hosting steps are in `DEPLOYMENT.md`. No source-code
setting can guarantee an account's eligibility or keep a provider's plan free forever.

## Official sources

- [Python downloads](https://www.python.org/downloads/) and [venv guide](https://docs.python.org/3.12/library/venv.html)
- [RapidOCR](https://github.com/RapidAI/RapidOCR) and [ONNX Runtime](https://onnxruntime.ai/)
- [Gradio source](https://github.com/gradio-app/gradio)
- [FastAPI API docs guide](https://fastapi.tiangolo.com/tutorial/first-steps/)
- [VS Code FAQ](https://code.visualstudio.com/docs/supporting/faq)
- [Bruno Open Source pricing](https://www.usebruno.com/pricing)
