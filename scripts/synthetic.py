"""Plain test sheets only. These are not realistic KTP samples or identity documents."""

import argparse
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

KTP_LINES = [
    "PROVINSI CONTOH",
    "KOTA CONTOH",
    "NIK : 9901011508901234",
    "Nama : NAMA CONTOH",
    "Tempat/Tgl Lahir : CONTOH, 15-08-1990",
    "Jenis Kelamin : LAKI-LAKI",
    "Gol. Darah : O",
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
BUSINESS_LINES = [
    "PT CONTOH TEKNOLOGI",
    "NAMA CONTOH",
    "Sales Manager",
    "info@example.com",
    "+62 812 3456 7890",
    "www.example.com",
    "Jl. Contoh No. 123, Jakarta",
]


def build_images(destination: Path) -> list[dict]:
    destination.mkdir(parents=True, exist_ok=True)
    fonts = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "C:/Windows/Fonts/arial.ttf",
    ]
    font = next((ImageFont.truetype(p, 36) for p in fonts if Path(p).is_file()), None)
    font = font or ImageFont.load_default(size=36)
    manifest = []
    for name, kind, lines, expected in [
        (
            "synthetic-ktp",
            "ktp",
            KTP_LINES,
            {
                "nik": "9901011508901234",
                "full_name": "NAMA CONTOH",
                "birth_date": "1990-08-15",
                "gender": "LAKI-LAKI",
                "address": "JL CONTOH NO 123",
                "rt": "001",
                "rw": "002",
            },
        ),
        (
            "synthetic-business",
            "business_card",
            BUSINESS_LINES,
            {
                "full_name": "NAMA CONTOH",
                "company": "PT CONTOH TEKNOLOGI",
                "job_title": "Sales Manager",
                "emails": ["info@example.com"],
                "phones": ["+6281234567890"],
                "websites": ["https://www.example.com"],
            },
        ),
    ]:
        image = Image.new("RGB", (1600, len(lines) * 65 + 160), "white")
        draw = ImageDraw.Draw(image)
        for index, line in enumerate(lines):
            draw.text((55, 30 + index * 65), line, font=font, fill="black")
        draw.text((55, image.height - 75), "SYNTHETIC TEST ONLY - NOT AN ID", font=font, fill="#777777")
        path = destination / f"{name}.png"
        image.save(path)
        manifest.append({"image": path.name, "document_type": kind, "expected": expected})
    (destination / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("destination", type=Path, nargs="?", default=Path("test-output/synthetic"))
    args = parser.parse_args()
    build_images(args.destination)
    print(f"Synthetic test sheets written to {args.destination}")
