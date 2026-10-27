"""Gradio test interface and the same FastAPI JSON endpoints on a single port."""

from contextlib import asynccontextmanager
from pathlib import Path

import anyio
import gradio as gr
from fastapi import FastAPI

from .api import create_app, process_bytes
from .config import Settings
from .engine import Engine
from .errors import OCRProblem

PROJECT_ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = PROJECT_ROOT / "examples"


def ui_auth(settings: Settings):
    # Setting an API key also protects the UI and its generated Gradio endpoints.
    password = settings.ui_password or settings.api_key
    return (settings.ui_username, password) if password else None


def read_upload(path: str, limit: int) -> bytes:
    # Gradio validates that paths refer to uploaded/explicitly allowed files first.
    with Path(path).open("rb") as handle:
        payload = handle.read(limit + 1)
    if len(payload) > limit:
        raise OCRProblem("FILE_TOO_LARGE", "Image exceeds the configured upload limit.", 413)
    return payload


def build_demo(api: FastAPI, settings: Settings) -> gr.Blocks:
    async def recognize(file_path, document_type, mode, rotation, include_raw, phone_region=""):
        if not file_path:
            return "Choose an image first.", {"error": {"code": "MISSING_FILE", "message": "Choose an image."}}
        try:
            payload = await anyio.to_thread.run_sync(read_upload, file_path, settings.max_file_bytes)
            result = await process_bytes(api, settings, payload, document_type, mode, include_raw, int(rotation), phone_region)
        except OCRProblem as exc:
            return exc.message, {"error": {"code": exc.code, "message": exc.message}}
        except (OSError, ValueError):
            return "Upload the image again.", {
                "error": {"code": "INVALID_UPLOAD", "message": "Upload the image again."}
            }
        status = (
            "Review needed — check the candidates in fields before using them."
            if result.needs_review
            else "Extraction complete — accepted values are in data. Check them against the image."
        )
        return status, result.model_dump(mode="json")

    with gr.Blocks(title="Card OCR · KTP & Business Cards", analytics_enabled=False,
                   delete_cache=(600, 600)) as demo:

        with gr.Row():
            with gr.Column(scale=1):
                upload = gr.File(label="Card image · JPEG, PNG or WebP", type="filepath",
                                 file_count="single", file_types=[".jpg", ".jpeg", ".png", ".webp"])
                kind = gr.Dropdown(label="Document type", choices=[("Automatic", "auto"),
                                   ("Indonesian KTP", "ktp"), ("Business card", "business_card")], value="auto")
                mode = gr.Radio(label="Reading mode", choices=[("Accurate · checks two readings", "accurate"),
                                ("Fast · review every result", "fast")], value="accurate")
                with gr.Accordion("Image and output options", open=False):
                    rotation = gr.Dropdown(label="Clockwise rotation", choices=[0, 90, 180, 270], value=0)
                    raw = gr.Checkbox(label="Include all detected text and boxes", value=False)
                    phone_region = gr.Textbox(label="Phone country · ID, US, SG, etc.", value="",
                        placeholder=f"Default: {settings.default_phone_region}",
                        info="For numbers without +country code. Select the country the number belongs to.")
                run = gr.Button("Extract JSON", variant="primary")
            with gr.Column(scale=2):
                status = gr.Textbox(label="Result", value="Choose a card image or a synthetic example.",
                                    interactive=False)
                output = gr.JSON(label="JSON response", value={})

        run.click(recognize, inputs=[upload, kind, mode, rotation, raw, phone_region], outputs=[status, output],
                  api_name="extract", concurrency_limit=1)
        gr.ClearButton([upload, status, output])
        gr.Markdown(
            "Use `data` for accepted values and `fields` for review candidates. "
            "An accepted value can still contain an OCR error. "
            "[REST API documentation](/docs) · [JSON schema](/openapi.json)\n\n"
            "Uploads use temporary files; cleanup runs every 10 minutes for files older than 10 minutes. "
            "OCR does not verify identity or document authenticity."
        )
    return demo.queue(max_size=4, default_concurrency_limit=1, api_open=False)


def demo_options(settings: Settings) -> dict:
    return {
        "auth": ui_auth(settings),
        "auth_message": "Sign in with the demo credentials configured by the owner.",
        "max_file_size": settings.max_file_bytes,
        "allowed_paths": [str(EXAMPLES)],
        "blocked_paths": [str(PROJECT_ROOT / ".env"), str(PROJECT_ROOT / ".venv")],
        "show_error": False,
        "enable_monitoring": False,
        "run_history": False,
        "ssr_mode": False,
        "mcp_server": False,
        "footer_links": [],
    }


def create_combined_app(settings: Settings | None = None, engine: Engine | None = None) -> FastAPI:
    settings = settings or Settings()
    api = create_app(settings, engine, homepage=None)
    demo = build_demo(api, settings)
    # REST routes registered first continue to own /v1/ocr, /docs and health URLs.
    return gr.mount_gradio_app(api, demo, path="/", **demo_options(settings))


def share_app_kwargs(api: FastAPI) -> dict:
    """Pass public FastAPI constructor options through Gradio's launch API."""
    @asynccontextmanager
    async def lifespan(_gradio_app):
        # The route/UI closures both use this API's one model and admission slot.
        async with api.router.lifespan_context(api):
            yield

    return {
        "routes": list(api.router.routes),
        "middleware": list(api.user_middleware),
        "exception_handlers": dict(api.exception_handlers),
        "lifespan": lifespan,
    }


def launch_share(settings: Settings, host: str, port: int):
    api = create_app(settings, homepage=None)
    demo = build_demo(api, settings)
    # The share URL exposes the UI AND /v1/ocr using the same JSON schema.
    demo.launch(share=True, server_name=host, server_port=port, inbrowser=False,
                app_kwargs=share_app_kwargs(api), **demo_options(settings))
