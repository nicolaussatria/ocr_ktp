import asyncio
import hmac
from contextlib import asynccontextmanager
from typing import Annotated

import anyio
from fastapi import FastAPI, File, Form, Security, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.security import APIKeyHeader

from . import __version__
from .config import Settings
from .engine import Engine, RapidEngine
from .errors import OCRProblem
from .pipeline import OCRPipeline
from .schemas import DocumentType, ErrorResponse, Mode, OCRResponse


class RequestGuard:
    """Authenticate and bound the entire body before the multipart parser can spool it."""

    def __init__(self, app, settings: Settings):
        self.app = app
        self.settings = settings
        self.inflight = 0

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        async def no_store(message):
            if message["type"] == "http.response.start":
                message.setdefault("headers", []).extend(
                    [(b"cache-control", b"no-store"), (b"x-content-type-options", b"nosniff")]
                )
            await send(message)

        is_rest = scope["path"].startswith("/v1/ocr/")
        is_demo_upload = scope["path"].rstrip("/") == "/gradio_api/upload"
        if not (is_rest or is_demo_upload) or scope["method"] == "OPTIONS":
            return await self.app(scope, receive, no_store)

        async def error(code, message, status):
            response = JSONResponse({"error": {"code": code, "message": message}}, status_code=status)
            await response(scope, receive, no_store)

        headers = dict(scope.get("headers", []))
        # Gradio authenticates its upload route with its own session cookie.
        if is_rest and self.settings.api_key and not hmac.compare_digest(
            headers.get(b"x-api-key", b""), self.settings.api_key.encode()
        ):
            return await error("UNAUTHORIZED", "Valid X-API-Key required.", 401)
        limit = self.settings.max_file_bytes + 64 * 1024
        try:
            content_length = int(headers.get(b"content-length", b"0"))
            if content_length < 0:
                raise ValueError
        except ValueError:
            return await error("INVALID_CONTENT_LENGTH", "Invalid Content-Length.", 400)
        if content_length > limit:
            return await error("FILE_TOO_LARGE", "Request body exceeds the configured limit.", 413)
        if self.inflight >= 4:
            return await error("SERVER_BUSY", "OCR capacity is busy; retry later.", 503)
        self.inflight += 1
        try:
            buffer = bytearray()
            try:
                async with asyncio.timeout(20):
                    while True:
                        message = await receive()
                        if message["type"] == "http.disconnect":
                            return
                        chunk = message.get("body", b"")
                        if len(buffer) + len(chunk) > limit:
                            return await error(
                                "FILE_TOO_LARGE", "Request body exceeds the configured limit.", 413
                            )
                        buffer.extend(chunk)
                        if not message.get("more_body", False):
                            break
            except TimeoutError:
                return await error("UPLOAD_TIMEOUT", "Image upload took too long.", 408)
            delivered = False

            async def replay():
                nonlocal delivered
                if delivered:
                    return await receive()
                delivered = True
                return {"type": "http.request", "body": bytes(buffer), "more_body": False}

            await self.app(scope, replay, no_store)
        finally:
            self.inflight -= 1


async def process_bytes(
    app: FastAPI,
    settings: Settings,
    payload: bytes,
    document_type: DocumentType,
    mode: Mode = "accurate",
    include_raw: bool = False,
    rotation: int = 0,
    phone_region: str | None = None,
) -> OCRResponse:
    """One bounded inference slot shared by REST uploads and the Gradio interface."""
    if rotation not in {0, 90, 180, 270}:
        raise OCRProblem("INVALID_ROTATION", "rotation must be 0, 90, 180, or 270.")
    if len(payload) > settings.max_file_bytes:
        raise OCRProblem("FILE_TOO_LARGE", "Image exceeds the configured upload limit.", 413)
    if not getattr(app.state, "pipeline", None):
        raise OCRProblem("NOT_READY", "OCR models are not ready.", 503)
    try:
        await asyncio.wait_for(app.state.slot.acquire(), settings.queue_timeout_seconds)
    except TimeoutError as exc:
        raise OCRProblem("SERVER_BUSY", "OCR capacity is busy; retry later.", 503) from exc
    try:
        # Hold the slot until native inference finishes, including on client disconnect.
        with anyio.CancelScope(shield=True):
            return await anyio.to_thread.run_sync(
                app.state.pipeline.process, payload, document_type, mode, include_raw, rotation, phone_region
            )
    except OCRProblem:
        raise
    except Exception as exc:
        raise OCRProblem(
            "OCR_FAILED", "OCR processing failed. Retry or contact the server operator.", 503
        ) from exc
    finally:
        app.state.slot.release()


def create_app(
    settings: Settings | None = None,
    engine: Engine | None = None,
    *,
    homepage: str | None = "/docs",
) -> FastAPI:
    settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.pipeline = OCRPipeline(engine or RapidEngine(settings), settings)
        app.state.slot = asyncio.Semaphore(1)
        yield
        app.state.pipeline = None

    app = FastAPI(
        title="Card OCR API",
        version=__version__,
        lifespan=lifespan,
        description="Upload one KTP or business card. Accepted values and review candidates are separated.",
    )
    app.add_middleware(RequestGuard, settings=settings)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["POST", "GET"],
        allow_headers=["Content-Type", "X-API-Key"],
    )

    @app.exception_handler(OCRProblem)
    async def ocr_problem(_, exc: OCRProblem):
        return JSONResponse({"error": {"code": exc.code, "message": exc.message}}, status_code=exc.status)

    @app.exception_handler(RequestValidationError)
    async def invalid_request(_, exc):
        # Do not echo uploaded data or secrets in validation errors.
        return JSONResponse(
            {
                "error": {
                    "code": "INVALID_REQUEST",
                    "message": "Send file, mode (fast/accurate), include_raw (boolean), and rotation (0/90/180/270).",
                }
            },
            status_code=422,
        )

    if homepage is not None:
        @app.get("/", include_in_schema=False)
        async def index():
            return RedirectResponse(homepage)

    @app.get("/healthz", tags=["operations"])
    async def health():
        return {"status": "ok", "version": __version__}

    @app.get("/readyz", tags=["operations"])
    async def ready():
        if not getattr(app.state, "pipeline", None):
            raise OCRProblem("NOT_READY", "OCR models are not ready.", 503)
        return {"status": "ready", "engine": app.state.pipeline.engine.name}

    @app.post(
        "/v1/ocr/{document_type}",
        response_model=OCRResponse,
        tags=["ocr"],
        responses={code: {"model": ErrorResponse} for code in (401, 413, 415, 422, 503)},
    )
    async def recognize(
        document_type: DocumentType,
        file: Annotated[UploadFile, File(description="One JPEG, PNG, or WebP image")],
        mode: Annotated[Mode, Form()] = "accurate",
        include_raw: Annotated[bool, Form()] = False,
        rotation: Annotated[int, Form()] = 0,
        phone_region: Annotated[str | None, Form(description="Phone country for national numbers, e.g. ID or US")] = None,
        api_key: Annotated[str | None, Security(APIKeyHeader(name="X-API-Key", auto_error=False))] = None,
    ):
        try:
            payload = await file.read(settings.max_file_bytes + 1)
            return await process_bytes(app, settings, payload, document_type, mode, include_raw, rotation, phone_region)
        finally:
            await file.close()

    return app


app = create_app()
