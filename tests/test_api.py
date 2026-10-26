import asyncio
from io import BytesIO

import pytest
from conftest import StubEngine
from fastapi.testclient import TestClient
from PIL import Image

from card_ocr.api import RequestGuard, create_app
from card_ocr.config import Settings


@pytest.fixture
def client():
    with TestClient(create_app(Settings(api_key="test-secret"), StubEngine())) as test_client:
        yield test_client


def test_api_accurate_contract(client, image_bytes):
    response = client.post(
        "/v1/ocr/ktp",
        headers={"X-API-Key": "test-secret"},
        files={"file": ("ktp.png", image_bytes, "image/png")},
    )
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["data"]["nik"] == "9901011508901234"
    assert result["data"]["birth_date"] == "1990-08-15"
    assert result["raw_ocr"] is None
    assert result["needs_review"] is False
    assert len(result["processing"]["passes"]) == 2
    assert response.headers["cache-control"] == "no-store"


def test_auto_and_raw(client, image_bytes):
    response = client.post(
        "/v1/ocr/auto",
        headers={"X-API-Key": "test-secret"},
        data={"include_raw": "true"},
        files={"file": ("img.png", image_bytes)},
    )
    assert response.json()["document_type"] == "ktp"
    assert response.json()["raw_ocr"][0]["pass_id"] == "p1"


def test_fast_mode_does_not_auto_accept_single_nik(client, image_bytes):
    response = client.post(
        "/v1/ocr/ktp",
        headers={"X-API-Key": "test-secret"},
        data={"mode": "fast"},
        files={"file": ("img.png", image_bytes)},
    )
    assert response.json()["data"]["nik"] is None
    assert response.json()["fields"]["nik"]["candidate"] == "9901011508901234"
    assert response.json()["needs_review"] is True


def test_auth_precedes_image_processing(client):
    response = client.post("/v1/ocr/ktp", files={"file": ("invalid.png", b"bad")})
    assert response.status_code == 401


@pytest.mark.parametrize("filename,data,code", [("x.png", b"not an image", 415), ("x.png", b"", 422)])
def test_invalid_files(client, filename, data, code):
    response = client.post(
        "/v1/ocr/ktp", headers={"X-API-Key": "test-secret"}, files={"file": (filename, data)}
    )
    assert response.status_code == code
    assert "error" in response.json()


def test_reject_image_bomb_before_decode(image_bytes):
    with TestClient(create_app(Settings(max_pixels=100_000), StubEngine())) as client:
        response = client.post("/v1/ocr/ktp", files={"file": ("large.png", image_bytes)})
        assert response.status_code == 413


def test_animated_image_rejected(client):
    out = BytesIO()
    Image.new("RGB", (400, 400), "red").save(
        out, "WEBP", save_all=True, append_images=[Image.new("RGB", (400, 400), "blue")], duration=100
    )
    response = client.post(
        "/v1/ocr/ktp", headers={"X-API-Key": "test-secret"}, files={"file": ("animated.webp", out.getvalue())}
    )
    assert response.status_code == 415


def test_unknown_document_and_blank_text(image_bytes):
    with TestClient(create_app(Settings(), StubEngine([]))) as client:
        response = client.post("/v1/ocr/auto", files={"file": ("img.png", image_bytes)})
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "NO_TEXT"


def test_wrong_document_type(client, image_bytes):
    response = client.post(
        "/v1/ocr/business_card",
        headers={"X-API-Key": "test-secret"},
        files={"file": ("img.png", image_bytes)},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "DOCUMENT_TYPE_MISMATCH"


def test_oversize_stream_without_content_length():
    async def run():
        settings = Settings(max_upload_mb=1)
        called = False

        async def underlying(scope, receive, send):
            nonlocal called
            called = True

        guard = RequestGuard(underlying, settings)
        messages = iter(
            [
                {"type": "http.request", "body": b"x" * 700_000, "more_body": True},
                {"type": "http.request", "body": b"x" * 700_000, "more_body": False},
            ]
        )
        sent = []

        async def receive():
            return next(messages)

        async def send(message):
            sent.append(message)

        await guard({"type": "http", "path": "/v1/ocr/ktp", "method": "POST", "headers": []}, receive, send)
        assert sent[0]["status"] == 413
        assert not called
        assert guard.inflight == 0

    asyncio.run(run())


def test_schema_is_available(client):
    spec = client.get("/openapi.json").json()
    assert "OCRResponse" in spec["components"]["schemas"]
    assert client.get("/readyz").status_code == 200
