"""Degraded, photo-like synthetic cards for local tuning. No real cards or PII.

These sheets are drawn from scratch. They are not real identity documents and not
photographs of real business cards. Each generated image pairs with the canonical
values the pipeline is expected to produce, plus a tag per applied degradation, so
``scripts.evaluate`` can report accuracy and coverage per condition.

Nothing here measures real-world accuracy. It measures how a change behaves under
controlled, repeatable camera-like conditions: tilt, perspective, blur, JPEG
compression, uneven light, and small print.
"""

import argparse
import json
import zlib
from collections.abc import Callable
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

FONT_CANDIDATES = [
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "C:/Windows/Fonts/arial.ttf",
]
MONO_CANDIDATES = [
    "/System/Library/Fonts/Menlo.ttc",
    "/System/Library/Fonts/Supplemental/Courier New.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
    "C:/Windows/Fonts/cour.ttf",
]


BOLD_CANDIDATES = [
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
]
MONO_BOLD_CANDIDATES = [
    "/System/Library/Fonts/Supplemental/Courier New Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf",
    "C:/Windows/Fonts/courbd.ttf",
]


def load_font(size: int, mono: bool = False, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = {
        (False, False): FONT_CANDIDATES,
        (True, False): MONO_CANDIDATES,
        (False, True): BOLD_CANDIDATES + FONT_CANDIDATES,
        (True, True): MONO_BOLD_CANDIDATES + MONO_CANDIDATES,
    }[(mono, bold)]
    for path in candidates:
        if Path(path).is_file():
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                continue
    return ImageFont.load_default(size=size)


def _ktp_standard() -> tuple[Image.Image, dict]:
    lines = [
        ("PROVINSI DKI JAKARTA", 60, 30),
        ("KOTA JAKARTA SELATAN", 60, 95),
        ("NIK : 9901011508901234", 60, 170),
        ("Nama : ANDI WIJAYA", 60, 235),
        ("Tempat/Tgl Lahir : JAKARTA, 15-08-1990", 60, 300),
        ("Jenis Kelamin : LAKI-LAKI   Gol. Darah : O", 60, 365),
        ("Alamat : JL. MERDEKA NO. 45", 60, 430),
        ("RT/RW : 001/002", 60, 495),
        ("Kel/Desa : CIPETE SELATAN", 60, 560),
        ("Kecamatan : CILANDAK", 60, 625),
        ("Agama : ISLAM", 60, 690),
        ("Status Perkawinan : KAWIN", 60, 755),
        ("Pekerjaan : KARYAWAN SWASTA", 60, 820),
        ("Kewarganegaraan : WNI", 60, 885),
        ("Berlaku Hingga : SEUMUR HIDUP", 60, 950),
    ]
    expected = {
        "nik": "9901011508901234",
        "full_name": "ANDI WIJAYA",
        "birth_place": "JAKARTA",
        "birth_date": "1990-08-15",
        "gender": "LAKI-LAKI",
        "blood_type": "O",
        "address": "JL. MERDEKA NO. 45",
        "rt": "001",
        "rw": "002",
        "village": "CIPETE SELATAN",
        "district": "CILANDAK",
        "city": "JAKARTA SELATAN",
        "province": "DKI JAKARTA",
        "religion": "ISLAM",
        "marital_status": "KAWIN",
        "occupation": "KARYAWAN SWASTA",
        "nationality": "WNI",
        "valid_until": "SEUMUR HIDUP",
    }
    image = Image.new("RGB", (1500, 1080), "white")
    draw = ImageDraw.Draw(image)
    font = load_font(34)
    bold = load_font(38)
    for index, (text, x, y) in enumerate(lines):
        draw.text((x, y), text, font=bold if index < 2 else font, fill="black")
    draw.text((60, 1020), "SYNTHETIC TEST ONLY - NOT AN ID", font=load_font(24), fill="#888888")
    return image, expected


def _ktp_female_wrapped() -> tuple[Image.Image, dict]:
    lines = [
        ("PROVINSI JAWA BARAT", 55, 40),
        ("KABUPATEN BANDUNG", 55, 105),
        ("NIK : 9901015508901234", 55, 180),
        ("Nama : SITI RAHAYU NINGSIH", 55, 245),
        ("Tempat/Tgl Lahir : BANDUNG, 15-08-1990", 55, 310),
        ("Jenis Kelamin : PEREMPUAN   Gol. Darah : AB", 55, 375),
        ("Alamat : JL. CIHAMPELAS NO. 120 BLOK C", 55, 440),
        ("RT/RW : 004/007", 55, 505),
        ("Kel/Desa : MEKARWANGI", 55, 570),
        ("Kecamatan : CIMENYAN", 55, 635),
        ("Agama : KRISTEN", 55, 700),
        ("Status Perkawinan : BELUM KAWIN", 55, 765),
        ("Pekerjaan : MAHASISWA", 55, 830),
        ("Kewarganegaraan : WNI", 55, 895),
        ("Berlaku Hingga : 15-08-2026", 55, 960),
    ]
    expected = {
        "nik": "9901015508901234",
        "full_name": "SITI RAHAYU NINGSIH",
        "birth_place": "BANDUNG",
        "birth_date": "1990-08-15",
        "gender": "PEREMPUAN",
        "blood_type": "AB",
        "address": "JL. CIHAMPELAS NO. 120 BLOK C",
        "rt": "004",
        "rw": "007",
        "village": "MEKARWANGI",
        "district": "CIMENYAN",
        "city": "BANDUNG",
        "province": "JAWA BARAT",
        "religion": "KRISTEN",
        "marital_status": "BELUM KAWIN",
        "occupation": "MAHASISWA",
        "nationality": "WNI",
        "valid_until": "2026-08-15",
    }
    image = Image.new("RGB", (1500, 1090), "white")
    draw = ImageDraw.Draw(image)
    font = load_font(33)
    bold = load_font(37)
    for index, (text, x, y) in enumerate(lines):
        draw.text((x, y), text, font=bold if index < 2 else font, fill="black")
    draw.text((55, 1025), "SYNTHETIC TEST ONLY - NOT AN ID", font=load_font(23), fill="#888888")
    return image, expected


def _ktp_photo_column() -> tuple[Image.Image, dict]:
    """Field column plus a photo block whose city/date share baselines."""
    image = Image.new("RGB", (1500, 1090), "white")
    draw = ImageDraw.Draw(image)
    font = load_font(32)
    draw.text((55, 35), "PROVINSI SUMATERA UTARA", font=load_font(36), fill="black")
    draw.text((55, 100), "KOTA MEDAN", font=load_font(36), fill="black")
    rows = [
        ("NIK : 9901011508901234", 175),
        ("Nama : BUDI SANTOSO", 240),
        ("Tempat/Tgl Lahir : MEDAN, 15-08-1990", 305),
        ("Jenis Kelamin : LAKI-LAKI", 370),
        ("Gol. Darah : B", 435),
        ("Alamat : JL. GATOT SUBROTO NO. 88", 500),
        ("RT/RW : 002/005", 565),
        ("Kel/Desa : SEI SIKAMBING", 630),
        ("Kecamatan : MEDAN PETISAH", 695),
        ("Agama : BUDDHA", 760),
        ("Status Perkawinan : CERAI HIDUP", 825),
        ("Pekerjaan : WIRASWASTA", 890),
        ("Kewarganegaraan : WNI", 955),
    ]
    for text, y in rows:
        draw.text((55, y), text, font=font, fill="black")
    # Photo block: gray portrait placeholder with city and date under it, sharing
    # the baselines of the field rows like a real KTP photo column.
    draw.rectangle([980, 180, 1400, 620], fill="#B8B8B8", outline="#666666", width=3)
    draw.text((1020, 660), "MEDAN", font=font, fill="black")
    draw.text((1020, 725), "15-08-1990", font=font, fill="black")
    draw.text((55, 1025), "SYNTHETIC TEST ONLY - NOT AN ID", font=load_font(22), fill="#888888")
    expected = {
        "nik": "9901011508901234",
        "full_name": "BUDI SANTOSO",
        "birth_place": "MEDAN",
        "birth_date": "1990-08-15",
        "gender": "LAKI-LAKI",
        "blood_type": "B",
        "address": "JL. GATOT SUBROTO NO. 88",
        "rt": "002",
        "rw": "005",
        "village": "SEI SIKAMBING",
        "district": "MEDAN PETISAH",
        "city": "MEDAN",
        "province": "SUMATERA UTARA",
        "religion": "BUDDHA",
        "marital_status": "CERAI HIDUP",
        "occupation": "WIRASWASTA",
        "nationality": "WNI",
        "valid_until": None,
    }
    return image, expected


def _ktp_small_print() -> tuple[Image.Image, dict]:
    lines = [
        "PROVINSI BANTEN",
        "KOTA TANGERANG",
        "NIK : 9901015508901234",
        "Nama : RINA KARTIKA",
        "Tempat/Tgl Lahir : TANGERANG, 15-08-1990",
        "Jenis Kelamin : PEREMPUAN   Gol. Darah : A",
        "Alamat : JL. SUDIRMAN NO. 7",
        "RT/RW : 003/004",
        "Kel/Desa : BABAKAN",
        "Kecamatan : TANGERANG",
        "Agama : ISLAM",
        "Status Perkawinan : KAWIN",
        "Pekerjaan : GURU",
        "Kewarganegaraan : WNI",
        "Berlaku Hingga : SEUMUR HIDUP",
    ]
    expected = {
        "nik": "9901015508901234",
        "full_name": "RINA KARTIKA",
        "birth_place": "TANGERANG",
        "birth_date": "1990-08-15",
        "gender": "PEREMPUAN",
        "blood_type": "A",
        "address": "JL. SUDIRMAN NO. 7",
        "rt": "003",
        "rw": "004",
        "village": "BABAKAN",
        "district": "TANGERANG",
        "city": "TANGERANG",
        "province": "BANTEN",
        "religion": "ISLAM",
        "marital_status": "KAWIN",
        "occupation": "GURU",
        "nationality": "WNI",
        "valid_until": "SEUMUR HIDUP",
    }
    image = Image.new("RGB", (1100, 770), "white")
    draw = ImageDraw.Draw(image)
    font = load_font(21, mono=True)
    for index, text in enumerate(lines):
        draw.text((40, 25 + index * 47), text, font=font, fill="black")
    draw.text((40, 735), "SYNTHETIC TEST ONLY - NOT AN ID", font=load_font(16), fill="#888888")
    return image, expected


def _security_ground(width: int, height: int, seed: int) -> Image.Image:
    """A pale blue gradient with guilloche-like strokes, as printed behind e-KTP text."""
    rng = np.random.default_rng(seed)
    y, x = np.mgrid[0:height, 0:width].astype(np.float32)
    ground = np.stack([200 - 30 * x / width, 225 - 15 * y / height, 235 - 25 * x / width], axis=-1)
    image = Image.fromarray(np.clip(ground, 0, 255).astype(np.uint8))
    draw = ImageDraw.Draw(image)
    for _ in range(60):
        cx, cy, radius = rng.uniform(0, width), rng.uniform(0, height), rng.uniform(80, 400)
        draw.ellipse([cx - radius, cy - 0.6 * radius, cx + radius, cy + 0.6 * radius],
                     outline=(150, 190, 215), width=2)
    for left in range(0, width, 18):
        draw.line([(left + 30 * np.sin(top / 40), top) for top in range(0, height, 8)],
                  fill=(185, 210, 228), width=1)
    return image


def _ektp(values: dict, *, address: tuple[str, ...], issued: tuple[str, str], seed: int,
          header: tuple[str, str], omit_labels: tuple[str, ...] = ()) -> tuple[Image.Image, dict]:
    """The e-KTP arrangement: labels and colons in aligned columns, a larger NIK line,
    indented RT/RW, Kel/Desa and Kecamatan rows, and the photo block on the right with
    the issuing place and date sharing baselines with the field rows.

    Aligned colons put short labels such as "NIK", "Nama" and "Alamat" a long way from
    their values, so the recogniser returns the label and the value as separate boxes.
    """
    width, height = 1600, 1010
    image = _security_ground(width, height, seed)
    draw = ImageDraw.Draw(image)
    heading = load_font(44, bold=True)
    for text, top in zip(header, (30, 85), strict=True):
        draw.text(((width - draw.textlength(text, font=heading)) / 2, top), text, font=heading, fill="black")
    label, nik_label = load_font(31), load_font(40, bold=True)
    left, indent, colon, value = 40, 80, 400, 425
    draw.text((left, 160), "NIK", font=nik_label, fill="black")
    draw.text((colon, 160), ":", font=nik_label, fill="black")
    draw.text((value, 155), values["nik"], font=load_font(50, mono=True, bold=True), fill="black")
    birth = f"{values['birth_place']}, {values['birth_printed']}"
    rows = [(left, "Nama", values["full_name"]), (left, "Tempat/Tgl Lahir", birth),
            (left, "Jenis Kelamin", values["gender"]), (left, "Alamat", address[0])]
    rows += [(left, None, line) for line in address[1:]]
    rows += [
        (indent, "RT/RW", f"{values['rt']}/{values['rw']}"),
        (indent, "Kel/Desa", values["village"]),
        (indent, "Kecamatan", values["district"]),
        (left, "Agama", values["religion"]),
        (left, "Status Perkawinan", values["marital_status"]),
        (left, "Pekerjaan", values["occupation"]),
        (left, "Kewarganegaraan", values["nationality"]),
        (left, "Berlaku Hingga", values["valid_until"]),
    ]
    for index, (x, name, text) in enumerate(rows):
        top = 240 + 50 * index
        if name and name not in omit_labels:
            draw.text((x, top), name, font=label, fill="black")
            draw.text((colon, top), ":", font=label, fill="black")
        draw.text((value, top), text, font=label, fill="black")
    draw.text((800, 340), "Gol. Darah", font=label, fill="black")
    draw.text((960, 340), ":", font=label, fill="black")
    draw.text((985, 340), values["blood_type"], font=label, fill="black")
    # Portrait placeholder, then the issuing place and date centred under it.
    draw.rectangle([1200, 200, 1530, 640], fill=(196, 72, 72))
    small = load_font(27)
    for text, top in zip(issued, (680, 720), strict=True):
        draw.text((1365 - draw.textlength(text, font=small) / 2, top), text, font=small, fill="black")
    draw.line([(1260, 820), (1330, 780), (1400, 830), (1470, 790)], fill=(40, 40, 40), width=3)
    draw.text((40, 960), "SYNTHETIC TEST ONLY - NOT AN ID", font=load_font(22), fill="#6B7B8C")
    expected = {key: values[key] for key in (
        "nik", "full_name", "birth_place", "birth_date", "gender", "blood_type", "rt", "rw",
        "village", "district", "city", "province", "religion", "marital_status", "occupation",
        "nationality", "valid_until")}
    expected["address"] = " ".join(address)
    return image, expected


def _ektp_single(*, omit_labels: tuple[str, ...] = ()) -> tuple[Image.Image, dict]:
    values = {
        "nik": "9901015508901234", "full_name": "SITI NURHALIZA PUTRI", "birth_place": "BANDUNG",
        "birth_printed": "15-08-1990", "birth_date": "1990-08-15", "gender": "PEREMPUAN",
        "blood_type": "O", "rt": "004", "rw": "007", "village": "CIPAGANTI", "district": "COBLONG",
        "city": "BANDUNG", "province": "JAWA BARAT", "religion": "ISLAM", "marital_status": "KAWIN",
        "occupation": "KARYAWAN SWASTA", "nationality": "WNI", "valid_until": "SEUMUR HIDUP",
    }
    return _ektp(values, address=("JL. CIHAMPELAS GG. MANGGA NO. 12",), issued=("BANDUNG", "12-05-2017"),
                 seed=3, header=("PROVINSI JAWA BARAT", "KOTA BANDUNG"), omit_labels=omit_labels)


def _ektp_wrapped() -> tuple[Image.Image, dict]:
    values = {
        "nik": "9901022103850007", "full_name": "BUDI SANTOSO", "birth_place": "SLEMAN",
        "birth_printed": "21-03-1985", "birth_date": "1985-03-21", "gender": "LAKI-LAKI",
        "blood_type": "AB", "rt": "012", "rw": "003", "village": "CATURTUNGGAL", "district": "DEPOK",
        "city": "SLEMAN", "province": "DI YOGYAKARTA", "religion": "KATHOLIK",
        "marital_status": "CERAI HIDUP", "occupation": "WIRASWASTA", "nationality": "WNI",
        "valid_until": "SEUMUR HIDUP",
    }
    return _ektp(values, address=("JL. SOEKARNO HATTA KOMPLEK GRIYA", "PERMAI BLOK C NO. 21"),
                 issued=("SLEMAN", "03-11-2016"), seed=11,
                 header=("PROVINSI DI YOGYAKARTA", "KABUPATEN SLEMAN"))


def _ektp_student() -> tuple[Image.Image, dict]:
    values = {
        "nik": "9901034709030002", "full_name": "RATNA DEWI ANGGRAINI", "birth_place": "SURABAYA",
        "birth_printed": "07-09-2003", "birth_date": "2003-09-07", "gender": "PEREMPUAN",
        "blood_type": "B", "rt": "001", "rw": "009", "village": "KEPUTIH", "district": "SUKOLILO",
        "city": "SURABAYA", "province": "JAWA TIMUR", "religion": "KRISTEN",
        "marital_status": "BELUM KAWIN", "occupation": "PELAJAR/MAHASISWA", "nationality": "WNI",
        "valid_until": "SEUMUR HIDUP",
    }
    return _ektp(values, address=("PERUM ARIMBI BLOK A-7",), issued=("SURABAYA", "19-10-2021"),
                 seed=29, header=("PROVINSI JAWA TIMUR", "KOTA SURABAYA"))


def _business_left() -> tuple[Image.Image, dict]:
    lines = [
        ("PT CAHAYA TEKNOLOGI", 70, 60, 40),
        ("ANDI WIJAYA", 70, 140, 34),
        ("Sales Manager", 70, 205, 30),
        ("andi.wijaya@cahayateknologi.co.id", 70, 285, 26),
        ("0812-3456-7890", 70, 345, 26),
        ("www.cahayateknologi.com", 70, 405, 26),
        ("Jl. Melati No. 12, Jakarta", 70, 465, 26),
    ]
    image = Image.new("RGB", (1300, 560), "white")
    draw = ImageDraw.Draw(image)
    for text, x, y, size in lines:
        draw.text((x, y), text, font=load_font(size), fill="black")
    draw.text((70, 515), "SYNTHETIC TEST ONLY", font=load_font(18), fill="#888888")
    expected = {
        "full_name": "ANDI WIJAYA",
        "company": "PT CAHAYA TEKNOLOGI",
        "job_title": "Sales Manager",
        "address": "Jl. Melati No. 12, Jakarta",
        "emails": ["andi.wijaya@cahayateknologi.co.id"],
        "phones": ["+6281234567890"],
        "websites": ["https://www.cahayateknologi.com"],
    }
    return image, expected


def _business_centered() -> tuple[Image.Image, dict]:
    lines = [
        "GRAHA NUSANTARA GROUP",
        "DEWI LESTARI",
        "Direktur Operasional",
        "dewi@grahanusantara.id",
        "+62 811 2233 4455",
    ]
    image = Image.new("RGB", (1300, 640), "white")
    draw = ImageDraw.Draw(image)
    font_company = load_font(38)
    font_name = load_font(33)
    font_title = load_font(28)
    draw.text((390, 80), lines[0], font=font_company, fill="black")
    draw.text((480, 170), lines[1], font=font_name, fill="black")
    draw.text((470, 240), lines[2], font=font_title, fill="black")
    draw.text((440, 330), lines[3], font=load_font(26), fill="black")
    draw.text((430, 390), lines[4], font=load_font(26), fill="black")
    draw.text((430, 590), "SYNTHETIC TEST ONLY", font=load_font(18), fill="#888888")
    expected = {
        "full_name": "DEWI LESTARI",
        "company": "GRAHA NUSANTARA GROUP",
        "job_title": "Direktur Operasional",
        "emails": ["dewi@grahanusantara.id"],
        "phones": ["+6281122334455"],
    }
    return image, expected


def _business_labeled_small() -> tuple[Image.Image, dict]:
    lines = [
        ("Nama : HENDRA GUNAWAN", 60, 50),
        ("Perusahaan : CV SUMBER MAKMUR", 60, 110),
        ("Jabatan : Marketing Manager", 60, 170),
        ("Kontak : hendra.sumber@example.com", 60, 230),
        ("Telepon : 0856 7890 1234", 60, 290),
        ("Alamat : Jl. Raya Bogor No. 88, Depok", 60, 350),
    ]
    image = Image.new("RGB", (1100, 420), "white")
    draw = ImageDraw.Draw(image)
    for text, x, y in lines:
        draw.text((x, y), text, font=load_font(24), fill="black")
    draw.text((60, 390), "SYNTHETIC TEST ONLY", font=load_font(16), fill="#888888")
    expected = {
        "full_name": "HENDRA GUNAWAN",
        "company": "CV SUMBER MAKMUR",
        "job_title": "Marketing Manager",
        "address": "Jl. Raya Bogor No. 88, Depok",
        "emails": ["hendra.sumber@example.com"],
        "phones": ["+6285678901234"],
    }
    return image, expected


def _contact_icon(draw: ImageDraw.ImageDraw, kind: str, x: int, y: int, size: int, ink) -> None:
    """Small pictograms printed before contact lines; the recogniser can read them as glyphs."""
    draw.ellipse([x, y, x + size, y + size], fill=ink)
    inner = (255, 255, 255)
    pad = size // 4
    if kind == "phone":
        draw.rounded_rectangle([x + pad + 3, y + pad, x + size - pad - 3, y + size - pad], radius=3, fill=inner)
    elif kind == "mail":
        draw.rectangle([x + pad, y + pad + 3, x + size - pad, y + size - pad - 3], outline=inner, width=2)
        draw.line([(x + pad, y + pad + 3), (x + size / 2, y + size / 2), (x + size - pad, y + pad + 3)],
                  fill=inner, width=2)
    elif kind == "web":
        draw.ellipse([x + pad, y + pad, x + size - pad, y + size - pad], outline=inner, width=2)
        draw.line([(x + pad, y + size / 2), (x + size - pad, y + size / 2)], fill=inner, width=2)
    else:
        draw.polygon([(x + size / 2, y + size - pad), (x + pad, y + pad + 4), (x + size - pad, y + pad + 4)],
                     fill=inner)


def _business_icons() -> tuple[Image.Image, dict]:
    """Two-column card: brand on the left, person and icon-led contact lines on the right."""
    image = Image.new("RGB", (1400, 800), (250, 248, 243))
    draw = ImageDraw.Draw(image)
    accent = (20, 70, 120)
    draw.rectangle([0, 0, 520, 800], fill=(232, 238, 245))
    draw.ellipse([150, 170, 370, 390], outline=accent, width=10)
    draw.text((115, 430), "PT ARTHA MANDIRI", font=load_font(36, bold=True), fill=accent)
    draw.text((170, 480), "Logistik & Pergudangan", font=load_font(22), fill=(90, 100, 110))
    draw.text((600, 110), "RIZKY PRATAMA", font=load_font(46, bold=True), fill=(30, 30, 30))
    draw.text((600, 175), "Business Development Manager", font=load_font(28), fill=(80, 80, 80))
    draw.line([(600, 235), (1300, 235)], fill=accent, width=3)
    contacts = [
        ("phone", "+62 21 5790 1234"),
        ("phone", "0813-2468-1357"),
        ("mail", "rizky.pratama@arthamandiri.co.id"),
        ("web", "www.arthamandiri.co.id"),
        ("pin", "Jl. Gatot Subroto Kav. 36, Jakarta"),
    ]
    for index, (kind, text) in enumerate(contacts):
        top = 290 + 80 * index
        _contact_icon(draw, kind, 600, top - 2, 40, accent)
        draw.text((665, top), text, font=load_font(30), fill=(30, 30, 30))
    draw.text((600, 740), "SYNTHETIC TEST ONLY", font=load_font(18), fill="#888888")
    expected = {
        "full_name": "RIZKY PRATAMA",
        "company": "PT ARTHA MANDIRI",
        "job_title": "Business Development Manager",
        "address": "Jl. Gatot Subroto Kav. 36, Jakarta",
        "emails": ["rizky.pratama@arthamandiri.co.id"],
        "phones": ["+622157901234", "+6281324681357"],
        "websites": ["https://www.arthamandiri.co.id"],
    }
    return image, expected


def _business_dark() -> tuple[Image.Image, dict]:
    """Light text on a dark card, with single-letter contact labels."""
    image = Image.new("RGB", (1300, 740), (22, 34, 52))
    draw = ImageDraw.Draw(image)
    gold = (226, 190, 120)
    light = (236, 236, 236)
    draw.text((80, 70), "CV KARYA LESTARI", font=load_font(40, bold=True), fill=gold)
    draw.text((80, 190), "MAYA KUSUMAWATI", font=load_font(44, bold=True), fill=light)
    draw.text((80, 255), "Marketing Director", font=load_font(30), fill=gold)
    lines = [
        "T. +62 22 8765 4321",
        "M. +62 878 1122 3344",
        "E. maya@karyalestari.id",
        "W. www.karyalestari.id",
    ]
    for index, text in enumerate(lines):
        draw.text((80, 360 + 70 * index), text, font=load_font(30), fill=light)
    draw.text((80, 680), "SYNTHETIC TEST ONLY", font=load_font(18), fill=(120, 130, 140))
    expected = {
        "full_name": "MAYA KUSUMAWATI",
        "company": "CV KARYA LESTARI",
        "job_title": "Marketing Director",
        "emails": ["maya@karyalestari.id"],
        "phones": ["+622287654321", "+6287811223344"],
        "websites": ["https://www.karyalestari.id"],
    }
    return image, expected


VARIANT_BUILDERS = {
    "ktp_standard": _ktp_standard,
    "ktp_female_wrapped": _ktp_female_wrapped,
    "ktp_photo_column": _ktp_photo_column,
    "ktp_small_print": _ktp_small_print,
    "ktp_ektp_single": _ektp_single,
    "ktp_ektp_wrapped": _ektp_wrapped,
    "ktp_ektp_student": _ektp_student,
    "business_left": _business_left,
    "business_centered": _business_centered,
    "business_labeled_small": _business_labeled_small,
    "business_icons": _business_icons,
    "business_dark": _business_dark,
}


def _white_border(image: np.ndarray, factor: float = 1.15) -> np.ndarray:
    height, width = image.shape[:2]
    canvas = np.full((int(height * factor), int(width * factor), 3), 255, dtype=np.uint8)
    y0, x0 = (canvas.shape[0] - height) // 2, (canvas.shape[1] - width) // 2
    canvas[y0 : y0 + height, x0 : x0 + width] = image
    return canvas


def _tilt(image: np.ndarray, angle: float) -> np.ndarray:
    framed = _white_border(image)
    center = (framed.shape[1] / 2, framed.shape[0] / 2)
    matrix = cv2.getRotationMatrix2D(center, angle, 1.0)
    return cv2.warpAffine(framed, matrix, (framed.shape[1], framed.shape[0]),
                          flags=cv2.INTER_CUBIC, borderValue=(255, 255, 255))


def _perspective(image: np.ndarray, strength: float = 0.035) -> np.ndarray:
    framed = _white_border(image)
    height, width = framed.shape[:2]
    dx, dy = width * strength, height * strength
    source = np.array([[0, 0], [width, 0], [width, height], [0, height]], dtype=np.float32)
    target = np.array([[dx, dy * 0.4], [width - dx * 0.6, 0],
                       [width - dx * 0.2, height - dy], [dx * 0.5, height - dy * 0.3]], dtype=np.float32)
    matrix = cv2.getPerspectiveTransform(source, target)
    return cv2.warpPerspective(framed, matrix, (width, height), flags=cv2.INTER_CUBIC,
                               borderValue=(255, 255, 255))


def _blur(image: np.ndarray, sigma: float) -> np.ndarray:
    return cv2.GaussianBlur(image, (0, 0), sigma)


def _jpeg(image: np.ndarray, quality: int) -> np.ndarray:
    ok, buffer = cv2.imencode(".jpg", image, [int(cv2.IMWRITE_JPEG_QUALITY), quality])
    return cv2.imdecode(buffer, cv2.IMREAD_COLOR) if ok else image


def _uneven_light(image: np.ndarray, low: float = 0.55) -> np.ndarray:
    width = image.shape[1]
    gradient = np.linspace(low, 1.0, width, dtype=np.float32)[None, :]
    shaded = image.astype(np.float32) * gradient[:, :, None]
    return np.clip(shaded, 0, 255).astype(np.uint8)


def _downscale(image: np.ndarray, factor: float) -> np.ndarray:
    height, width = image.shape[:2]
    return cv2.resize(image, (int(width * factor), int(height * factor)), interpolation=cv2.INTER_AREA)


def _on_table(image: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    """The card photographed on a desk: it fills about 60% of the frame, seen at an angle,
    with rounded corners, a soft shadow and a textured surface around it."""
    height, width = image.shape[:2]
    frame_w, frame_h = int(width / 0.6), int(width / 0.6 * 0.75)
    grain = rng.normal(0, 1, (frame_h // 8 + 1, frame_w // 2 + 1)).astype(np.float32)
    grain = cv2.resize(cv2.GaussianBlur(grain, (0, 0), 2), (frame_w, frame_h))
    stripes = np.sin(np.linspace(0, 40, frame_h, dtype=np.float32))[:, None] * 0.4
    tone = (grain + stripes)[:, :, None] * 10
    scene = np.clip(np.array([62, 94, 128], np.float32) + tone, 0, 255).astype(np.uint8)

    mask = np.zeros((height, width), np.uint8)
    radius = int(0.04 * width)
    cv2.rectangle(mask, (radius, 0), (width - radius, height), 255, -1)
    cv2.rectangle(mask, (0, radius), (width, height - radius), 255, -1)
    for cx, cy in ((radius, radius), (width - radius, radius), (radius, height - radius),
                   (width - radius, height - radius)):
        cv2.circle(mask, (cx, cy), radius, (255,), -1)

    x0, y0 = (frame_w - width) / 2, (frame_h - height) / 2
    jitter = lambda: rng.uniform(-0.035, 0.035) * width  # noqa: E731
    source = np.array([[0, 0], [width, 0], [width, height], [0, height]], dtype=np.float32)
    target = np.array([[x0 + jitter(), y0 + jitter()], [x0 + width + jitter(), y0 + jitter()],
                       [x0 + width + jitter(), y0 + height + jitter()], [x0 + jitter(), y0 + height + jitter()]],
                      dtype=np.float32)
    matrix = cv2.getPerspectiveTransform(source, target)
    card = cv2.warpPerspective(image, matrix, (frame_w, frame_h), flags=cv2.INTER_CUBIC)
    alpha = cv2.warpPerspective(mask, matrix, (frame_w, frame_h), flags=cv2.INTER_LINEAR)
    shadow = cv2.GaussianBlur(np.roll(alpha, (int(0.02 * height), int(0.015 * width)), (0, 1)), (0, 0), 12)
    scene = (scene.astype(np.float32) * (1 - 0.45 * shadow[:, :, None] / 255)).astype(np.uint8)
    weight = alpha[:, :, None].astype(np.float32) / 255
    composed = (card * weight + scene * (1 - weight)).astype(np.uint8)
    return _jpeg(_blur(composed, 0.7), 80)


CONDITIONS: dict[str, Callable[[np.ndarray, np.random.Generator], np.ndarray]] = {
    "clean": lambda image, rng: image,
    "tilt4": lambda image, rng: _tilt(image, 4.0),
    "tilt8": lambda image, rng: _tilt(image, 8.0),
    "perspective": lambda image, rng: _perspective(image, 0.03 + 0.02 * rng.random()),
    "blur1.4": lambda image, rng: _blur(image, 1.4),
    "jpeg55": lambda image, rng: _jpeg(image, 55),
    "backlight": lambda image, rng: _uneven_light(image, 0.5 + 0.15 * rng.random()),
    "downscale60": lambda image, rng: _downscale(image, 0.6),
    "photo": lambda image, rng: _jpeg(
        _uneven_light(_blur(_perspective(_tilt(image, 3.0), 0.03), 0.8), 0.6), 70
    ),
    "on_table": _on_table,
}


def build_corpus(destination: Path, variants: list[str], conditions: list[str], seed: int = 7) -> list[dict]:
    destination.mkdir(parents=True, exist_ok=True)
    manifest = []
    for variant in variants:
        image, expected = VARIANT_BUILDERS[variant]()
        kind = "ktp" if variant.startswith("ktp") else "business_card"
        bgr = cv2.cvtColor(np.asarray(image), cv2.COLOR_RGB2BGR)
        if kind == "ktp":
            expected.setdefault("valid_until", None)
        for condition in conditions:
            # crc32, not hash(): Python salts str hashing per process, and a measurement
            # corpus must regenerate byte-identically on every run.
            rng = np.random.default_rng(zlib.crc32(f"{seed}|{variant}|{condition}".encode()))
            degraded = CONDITIONS[condition](bgr.copy(), rng)
            name = f"{variant}__{condition}.png"
            cv2.imwrite(str(destination / name), degraded)
            manifest.append(
                {
                    "image": name,
                    "document_type": kind,
                    "expected": {k: v for k, v in expected.items() if v is not None},
                    "tags": [variant, condition],
                }
            )
    (destination / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate degraded synthetic cards for tuning")
    parser.add_argument("destination", type=Path, nargs="?", default=Path("test-output/stress"))
    parser.add_argument("--variants", nargs="*", default=list(VARIANT_BUILDERS), choices=list(VARIANT_BUILDERS))
    parser.add_argument("--conditions", nargs="*", default=list(CONDITIONS), choices=list(CONDITIONS))
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args()
    manifest = build_corpus(args.destination, args.variants, args.conditions, args.seed)
    print(f"Wrote {len(manifest)} degraded sheets to {args.destination}")


if __name__ == "__main__":
    main()
