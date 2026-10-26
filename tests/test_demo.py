import json
from unittest.mock import patch

import pytest
from conftest import StubEngine
from fastapi.testclient import TestClient

from card_ocr.api import create_app
from card_ocr.config import Settings
from card_ocr.demo import build_demo, create_combined_app, demo_options, share_app_kwargs


def upload(client, payload):
    response = client.post("/gradio_api/upload", files={"files": ("test.png", payload, "image/png")})
    assert response.status_code == 200, response.text
    return {"path": response.json()[0], "meta": {"_type": "gradio.FileData"}}


def extract(client, file_data, kind="ktp", phone_region=""):
    response = client.post("/gradio_api/call/extract", json={"data": [file_data, kind, "accurate", 0, False, phone_region]})
    assert response.status_code == 200, response.text
    result = client.get(f"/gradio_api/call/extract/{response.json()['event_id']}")
    assert "event: complete" in result.text, result.text
    lines = result.text.splitlines()
    for index, line in enumerate(lines):
        if line == "event: complete":
            return json.loads(lines[index + 1].removeprefix("data: "))[1]
    raise AssertionError("No completed Gradio response")


def test_mounted_ui_and_rest_share_engine_and_schema(image_bytes):
    engine = StubEngine()
    settings = Settings(_env_file=None)
    with TestClient(create_combined_app(settings, engine)) as client:
        assert client.get("/").status_code == 200
        assert client.get("/docs").status_code == 200
        assert client.get("/readyz").json()["status"] == "ready"
        ui_result = extract(client, upload(client, image_bytes))
        rest = client.post("/v1/ocr/ktp", files={"file": ("test.png", image_bytes)})
        assert rest.status_code == 200
        assert ui_result["data"] == rest.json()["data"]
        assert ui_result["schema_version"] == rest.json()["schema_version"]
        assert ui_result["data"]["nik"] == "9901011508901234"
        assert engine.calls == 4  # Both accurate requests used this single engine instance.


def test_key_also_protects_gradio_upload_and_prediction(image_bytes):
    settings = Settings(_env_file=None, api_key="local-test-key")
    with TestClient(create_combined_app(settings, StubEngine())) as client:
        assert client.post("/gradio_api/upload", files={"files": ("x.png", image_bytes)}).status_code == 401
        assert client.post("/gradio_api/call/extract", json={"data": []}).status_code == 401
        assert client.post("/v1/ocr/ktp", files={"file": ("x.png", image_bytes)}).status_code == 401
        assert client.post("/login", data={"username": "learner", "password": "wrong"}).status_code == 400
        assert client.post("/login", data={"username": "learner", "password": "local-test-key"}).status_code == 200
        assert extract(client, upload(client, image_bytes))["data"]["nik"] == "9901011508901234"
        # A UI login cookie does not silently bypass the REST key policy.
        assert client.post("/v1/ocr/ktp", files={"file": ("x.png", image_bytes)}).status_code == 401


def test_gradio_rejects_invalid_image_content():
    engine = StubEngine()
    with TestClient(create_combined_app(Settings(_env_file=None), engine)) as client:
        result = extract(client, upload(client, b"not an image"))
        assert result["error"]["code"] == "INVALID_IMAGE"
        assert engine.calls == 0


def test_gradio_bounds_total_upload_before_spooling():
    engine = StubEngine()
    with TestClient(create_combined_app(Settings(_env_file=None, max_upload_mb=1), engine)) as client:
        response = client.post("/gradio_api/upload", files={"files": ("large.png", b"x" * 1_200_000)})
        assert response.status_code == 413
        assert engine.calls == 0


def test_ui_honors_same_busy_slot_as_rest(image_bytes):
    app = create_combined_app(Settings(_env_file=None, queue_timeout_seconds=0.1), StubEngine())
    with TestClient(app) as client:
        file_data = upload(client, image_bytes)
        client.portal.call(app.state.slot.acquire)
        try:
            result = extract(client, file_data)
            assert result["error"]["code"] == "SERVER_BUSY"
        finally:
            client.portal.call(app.state.slot.release)
        assert extract(client, file_data)["data"]["nik"] == "9901011508901234"


def test_share_launch_contains_working_ui_rest_auth_and_lifespan(image_bytes):
    settings = Settings(_env_file=None, api_key="share-test-key", ui_password="ui-test-password")
    engine = StubEngine()
    api = create_app(settings, engine, homepage=None)
    demo = build_demo(api, settings)
    captured = {}

    class ServerIntercept(Exception):
        pass

    def capture_server(**kwargs):
        captured["app"] = kwargs["app"]
        raise ServerIntercept

    # Run Gradio's real launch configuration, stopping before opening a socket or public tunnel.
    with patch("gradio.http_server.start_server", side_effect=capture_server), pytest.raises(ServerIntercept):
        demo.launch(share=True, server_name="127.0.0.1", server_port=7860,
                    app_kwargs=share_app_kwargs(api), **demo_options(settings))
    with TestClient(captured["app"]) as client:
        # launch normally starts the queue through this local endpoint after opening the server.
        assert client.get("/gradio_api/startup-events").status_code == 200
        assert client.get("/").status_code == 200
        assert client.get("/readyz").status_code == 200
        assert client.post("/gradio_api/upload", files={"files": ("x.png", image_bytes)}).status_code == 401
        assert client.post("/v1/ocr/ktp", files={"file": ("x.png", image_bytes)}).status_code == 401
        response = client.post("/v1/ocr/ktp", headers={"X-API-Key": "share-test-key"},
                               files={"file": ("x.png", image_bytes)})
        assert response.status_code == 200
        assert response.json()["data"]["nik"] == "9901011508901234"
        assert client.post("/login", data={"username": "learner", "password": "ui-test-password"}).status_code == 200
        assert extract(client, upload(client, image_bytes))["data"] == response.json()["data"]


@pytest.mark.integration
def test_gradio_real_model_image_to_json():
    import os
    from pathlib import Path

    if os.getenv("RUN_OCR_INTEGRATION") != "1":
        pytest.skip("Set RUN_OCR_INTEGRATION=1")
    payload = (Path(__file__).resolve().parents[1] / "examples/synthetic-ktp.png").read_bytes()
    with TestClient(create_combined_app(Settings(_env_file=None))) as client:
        result = extract(client, upload(client, payload))
        assert result["fields"]["nik"]["candidate"] == "9901011508901234"
        assert result["fields"]["birth_date"]["candidate"] == "1990-08-15"


def test_gradio_forwards_phone_country(image_bytes):
    engine = StubEngine(["Name: NAMA CONTOH", "Company: EXAMPLE CO", "(423) 220-0983"])
    with TestClient(create_combined_app(Settings(_env_file=None), engine)) as client:
        result = extract(client, upload(client, image_bytes), "business_card", "US")
    assert result["data"]["phones"] == ["+14232200983"]
    assert result["processing"]["phone_region"] == "US"
