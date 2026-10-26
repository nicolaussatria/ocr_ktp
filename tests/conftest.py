import math
from io import BytesIO

import cv2
import numpy as np
import pytest
from PIL import Image, ImageDraw

from card_ocr.schemas import Span

KTP_LINES = [
    "PROVINSI CONTOH",
    "KOTA CONTOH",
    "NIK : 9901011508901234",
    "Nama : NAMA CONTOH",
    "Tempat/Tgl Lahir : CONTOH, 15-08-1990",
    "Jenis Kelamin : LAKI-LAKI Gol. Darah : O",
    "Alamat : JL CONTOH NO 123",
    "RT/RW : 001/002",
    "Kel/Desa : DESA CONTOH",
    "Kecamatan : KEC CONTOH",
    "Agama : ISLAM",
    "Status Perkawinan : KAWIN",
    "Pekerjaan : KARYAWAN SWASTA",
    "Kewarganegaraan : WNI",
    "Berlaku Hingga : SEUMUR HIDUP",
]


def make_spans(lines, pass_id="p1", score=0.999):
    return [
        Span(text=t, score=score, box=[[30, y], [1000, y], [1000, y + 30], [30, y + 30]], pass_id=pass_id)
        for y, t in enumerate(lines, 1)
        for y in [y * 50]
    ]


def tilted_line(x, y, width=300, height=34, angle=0.0, text="PRINTED LINE", **fields):
    """A text box whose top edge starts at (x, y) and is turned by ``angle`` degrees."""
    along = np.array([math.cos(math.radians(angle)), math.sin(math.radians(angle))])
    down = np.array([-along[1], along[0]])
    start = np.array([x, y], dtype=float)
    box = [start, start + width * along, start + width * along + height * down, start + height * down]
    return Span(text=text, score=fields.pop("score", 0.99), box=[point.tolist() for point in box], **fields)


def drawn_photo(*shapes, size=(1200, 900), background=(70, 95, 120), grain=0.0):
    """A photograph: filled shapes on a surface, softened the way a lens softens edges.

    ``grain`` adds sensor noise, so the picture does not measure as out of focus.
    """
    width, height = size
    image = np.full((height, width, 3), background, np.uint8)
    for corners, colour in shapes:
        cv2.fillConvexPoly(image, np.int32(corners), colour, lineType=cv2.LINE_AA)
    image = cv2.GaussianBlur(image, (5, 5), 0)
    if grain:
        noise = np.random.default_rng(7).normal(0.0, grain, image.shape)
        image = np.clip(image + noise, 0, 255).astype(np.uint8)
    return image


class StubEngine:
    name = "test-double"
    models = {}
    hashes = {}

    def __init__(self, lines=None):
        self.lines = lines if lines is not None else KTP_LINES
        self.calls = 0

    def recognize(self, image, pass_id):
        self.calls += 1
        return make_spans(self.lines, pass_id)


@pytest.fixture
def image_bytes():
    image = Image.new("RGB", (1400, 900), "white")
    draw = ImageDraw.Draw(image)
    for x in range(0, 1400, 10):
        draw.line((x, 0, x, 900), fill="black", width=3)
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()
