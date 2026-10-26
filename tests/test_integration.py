import os
from io import BytesIO

import pytest
from fastapi.testclient import TestClient

from card_ocr.api import create_app
from card_ocr.config import Settings
from card_ocr.engine import RapidEngine
from scripts.stress import _ektp_single
from scripts.synthetic import build_images

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(os.getenv("RUN_OCR_INTEGRATION") != "1", reason="Set RUN_OCR_INTEGRATION=1"),
]


@pytest.fixture(scope="module")
def real_client(tmp_path_factory):
    images = tmp_path_factory.mktemp("synthetic")
    build_images(images)
    with TestClient(create_app(Settings(), RapidEngine(Settings()))) as client:
        yield client, images


def test_real_ktp_image_to_json(real_client):
    client, images = real_client
    response = client.post(
        "/v1/ocr/ktp", files={"file": ("ktp.png", (images / "synthetic-ktp.png").read_bytes())}
    )
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["fields"]["nik"]["candidate"] == "9901011508901234"
    assert result["fields"]["birth_date"]["candidate"] == "1990-08-15"
    assert result["fields"]["full_name"]["candidate"] == "NAMA CONTOH"


def test_real_ktp_with_missing_name_label_keeps_the_printed_name_for_review(real_client):
    client, _ = real_client
    image, expected = _ektp_single(omit_labels=("Nama",))
    payload = BytesIO()
    image.save(payload, format="PNG")
    response = client.post("/v1/ocr/ktp", files={"file": ("missing-label.png", payload.getvalue())})
    assert response.status_code == 200, response.text
    result = response.json()
    name = result["fields"]["full_name"]
    assert name["candidate"] == expected["full_name"]
    assert name["status"] == "review"
    assert "unlabeled_name_requires_review" in name["reasons"]
    assert result["data"]["full_name"] is None


def test_real_business_card_image_to_json(real_client):
    client, images = real_client
    response = client.post(
        "/v1/ocr/business_card",
        files={"file": ("business.png", (images / "synthetic-business.png").read_bytes())},
    )
    assert response.status_code == 200, response.text
    result = response.json()
    assert "info@example.com" in [f["candidate"] for f in result["fields"]["emails"]]
    assert "+6281234567890" in [f["candidate"] for f in result["fields"]["phones"]]


def test_real_rotation_parameter(real_client, tmp_path):
    from PIL import Image

    client, images = real_client
    rotated = tmp_path / "rotated.png"
    Image.open(images / "synthetic-ktp.png").transpose(Image.Transpose.ROTATE_90).save(rotated)
    response = client.post(
        "/v1/ocr/ktp", data={"rotation": "90"}, files={"file": ("rotated.png", rotated.read_bytes())}
    )
    assert response.status_code == 200
    assert response.json()["fields"]["nik"]["candidate"] == "9901011508901234"
