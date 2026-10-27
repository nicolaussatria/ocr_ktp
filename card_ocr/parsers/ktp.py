import re
from datetime import date
from statistics import median

from ..schemas import FieldResult, Span
from .common import (
    Observation,
    Parsed,
    canonical_street,
    flag,
    folded_category,
    label_word,
    normalized,
    rows,
    split_columns,
)

FIELDS = (
    "nik",
    "full_name",
    "birth_place",
    "birth_date",
    "gender",
    "blood_type",
    "address",
    "rt",
    "rw",
    "village",
    "district",
    "city",
    "province",
    "religion",
    "marital_status",
    "occupation",
    "nationality",
    "valid_until",
)
REQUIRED = ("nik", "full_name", "birth_date", "gender", "address")
LABELS = {
    "nik": label_word("NIK"),
    "full_name": label_word("NAMA"),
    # TG[LI1]: this model reads the lowercase l of "Tgl" as I or 1 on real cards.
    # The same documented lookalikes are accepted in every other label word.
    "birth": label_word("TEMPAT") + r"\s*[/,]?\s*(?:" + label_word("TGL") + r"\.?|"
             + label_word("TANGGAL") + r")\s*" + label_word("LAHIR")
             # "TempaV T gI Lahir": the long label is often misread; "Lahir" survives, and no
             # other KTP label ends with it.
             + r"|[A-Za-z][A-Za-z/,. ]{3,14}" + label_word("LAHIR"),
    "gender": label_word("JENIS") + r"\s*" + label_word("KELAMIN"),
    "blood_type": label_word("GOL") + r"\.?\s*" + label_word("DARAH"),
    "address": label_word("ALAMAT"),
    "rt_rw": label_word("RT") + r"\s*[/,.]?\s*" + label_word("RW"),
    "village": r"(?:" + label_word("KEL") + r"\.?\s*[/,]?\s*" + label_word("DESA") + r"|"
               + label_word("KELURAHAN") + r"|" + label_word("DESA") + r")",
    "district": label_word("KECAMATAN"),
    "religion": label_word("AGAMA"),
    "marital_status": label_word("STATUS") + r"\s*" + label_word("PERKAWINAN"),
    "occupation": label_word("PEKERJAAN"),
    "nationality": label_word("KEWARGANEGARAAN"),
    "valid_until": label_word("BERLAKU") + r"\s*" + label_word("HINGGA"),
}
LABEL_RE = re.compile(
    r"(?<![A-Z])(?:" + "|".join(f"(?P<{key}>{value})" for key, value in LABELS.items()) + r")\s*[:;]?", re.I
)
MARITAL_STATUS = {
    "BELUMKAWIN": "BELUM KAWIN",
    "KAWIN": "KAWIN",
    "CERAIHIDUP": "CERAI HIDUP",
    "CERAIMATI": "CERAI MATI",
}
# Closed printed categories match after documented lookalikes are folded together
# (see common.CATEGORY_FOLD); anything that does not fold to a known category stays
# unrecognized and reviewable.
MARITAL_FOLDED = {re.sub(r"[\s.]", "", folded_category(key)): value for key, value in MARITAL_STATUS.items()}
GENDER_FOLDED = {
    re.sub(r"[\s\-]", "", folded_category("LAKI-LAKI")): "LAKI-LAKI",
    re.sub(r"[\s\-]", "", folded_category("PEREMPUAN")): "PEREMPUAN",
}
# Fields whose printed value may wrap onto the next line.
CONTINUABLE = ("address", "full_name")
DATE_RE = re.compile(r"(?<!\d)(\d{1,2})\s*[-/.]\s*(\d{1,2})\s*[-/.]\s*(\d{4})(?!\d)")


def normalize_nik(text: str) -> tuple[str, list[str]]:
    compact = re.sub(r"[\s.\-]", "", text)
    candidate = compact.translate(
        str.maketrans(
            {
                "O": "0",
                "o": "0",
                "I": "1",
                "i": "1",
                "l": "1",
                "L": "1",
                "|": "1",
                "S": "5",
                "s": "5",
                "B": "8",
                "Z": "2",
                "z": "2",
            }
        )
    )
    issues = []
    if candidate != compact:
        issues.append("character_substitution_requires_review")
    if not re.fullmatch(r"[0-9]{16}", candidate):
        return candidate, issues + ["nik_must_have_16_digits"]
    encoded_day, month, year = int(candidate[6:8]), int(candidate[8:10]), int(candidate[10:12])
    day = encoded_day - 40 if 41 <= encoded_day <= 71 else encoded_day
    valid_date = False
    for century in (1900, 2000):
        try:
            born = date(century + year, month, day)
            valid_date |= born <= date.today()
        except ValueError:
            pass
    if encoded_day not in range(1, 32) and encoded_day not in range(41, 72):
        valid_date = False
    if not valid_date:
        issues.append("invalid_nik_birth_component")
    if candidate[:6] == "000000" or candidate[-4:] == "0000":
        issues.append("suspicious_nik_structure")
    return candidate, issues


def _date_value(text: str) -> tuple[str, list[str]]:
    match = DATE_RE.fullmatch(text.strip())
    if not match:
        return text, ["unrecognized_date_format"]
    try:
        day, month, year = map(int, match.groups())
        return date(year, month, day).isoformat(), []
    except ValueError:
        return text, ["invalid_calendar_date"]


def _store(
    parsed: Parsed,
    key: str,
    value: str,
    spans: list[Span],
    issues: list[str],
    value_spans: list[Span] | None = None,
):
    value = re.sub(r"\s+", " ", value).strip(" :;|")
    if not value:
        return

    def add(target: str, text: str, boxes: list[Span], notes: list[str]):
        parsed.add(target, text, boxes, notes, value_spans, digits=target == "nik")

    if key == "nik":
        value, extra = normalize_nik(value)
        add(key, value, spans, issues + extra)
    elif key == "birth":
        match = DATE_RE.search(value)
        if match:
            add("birth_place", value[: match.start()].strip(" ,:"), spans, issues)
            normalized, extra = _date_value(match.group())
            if not extra and (normalized > date.today().isoformat() or normalized < "1900-01-01"):
                extra.append("implausible_birth_date")
            add("birth_date", normalized, spans, issues + extra)
        else:
            # Preserve the printed candidate; never infer the birth date from NIK.
            add("birth_date", value, spans, issues + ["unrecognized_birth_line"])
    elif key == "rt_rw":
        match = re.fullmatch(r"(\d{1,3})\s*[/,]\s*(\d{1,3})", value)
        if match:
            add("rt", match[1].zfill(3), spans, issues)
            add("rw", match[2].zfill(3), spans, issues)
        else:
            add("rt", value, spans, issues + ["invalid_rt_rw"])
    elif key == "gender":
        compact = re.sub(r"[\s\-]", "", folded_category(value))
        gender = GENDER_FOLDED.get(compact)
        add(key, gender or value, spans, issues + ([] if gender else ["unrecognized_gender"]))
    elif key == "blood_type":
        normalized = re.sub(r"[\s.]", "", folded_category(value))
        valid = bool(re.fullmatch(r"(?:A|B|AB|O)[+-]?|-", normalized))
        add(key, normalized, spans, issues + ([] if valid else ["unrecognized_blood_type"]))
    elif key == "marital_status":
        # OCR drops the printed space: "BELUMKAWIN" is the same category as "BELUM KAWIN".
        compact = re.sub(r"[\s.]", "", folded_category(value))
        canonical = MARITAL_FOLDED.get(compact)
        add(
            key,
            canonical or value.upper(),
            spans,
            issues + ([] if canonical else ["unrecognized_marital_status"]),
        )
    elif key == "nationality":
        normalized = folded_category(value).strip()
        add(
            key,
            normalized,
            spans,
            issues + ([] if normalized in {"WNI", "WNA"} else ["unrecognized_nationality"]),
        )
    elif key == "valid_until":
        if re.sub(r"[\s.]", "", folded_category(value)) == "SEUMURHIDUP":
            add(key, "SEUMUR HIDUP", spans, issues)
        else:
            normalized, extra = _date_value(value)
            add(key, normalized, spans, issues + extra)
    else:
        if key == "address":
            # Same fixed abbreviation as the business card path: a JI./J1. prefix is
            # the recogniser reading the l of "Jl.", not a second spelling.
            value, extra = canonical_street(value)
            issues = issues + extra
        if key == "full_name" and (any(c.isdigit() for c in value) or not any(c.isalpha() for c in value)):
            issues = issues + ["suspicious_name_characters"]
        add(key, value, spans, issues)


def _label_only(text: str) -> bool:
    """A box that holds a field label and at most its colon, but no printed value."""
    match = LABEL_RE.match(text.strip())
    return bool(match) and not text.strip()[match.end():].strip(" :;|")


def _is_colon(text: str) -> bool:
    return not text.strip(" :;|")


# A value box may start this many glyph heights either side of the measured value
# column. The photo block sits 20+ heights to the right of the column and the
# "Gol. Darah" label about 11; perspective shifts the column by far less.
VALUE_COLUMN_TOLERANCE = 4.0


def _value_column(table: list[list[Span]]) -> float | None:
    """Left edge of the printed value column, measured where a label is a box of its own.

    On an e-KTP the colons are printed in an aligned column, so a short label such as
    "NIK", "Nama" or "Alamat" sits far from its value and the recogniser returns the two
    as separate boxes. Those value boxes all start at the same x; the photo block does
    not. The median keeps one label whose value was missed from moving the column.
    """
    starts = []
    for row in table:
        if len(row) >= 2 and _label_only(row[0].text):
            value = next((span for span in row[1:] if not _is_colon(span.text)), None)
            if value is not None:
                starts.append(value.x)
    return median(starts) if len(starts) >= 2 else None


def _in_value_column(segment: list[Span], value_x: float | None) -> bool:
    if _is_colon(segment[0].text) or segment[0].text.lstrip().startswith((":", ";")):
        return True
    first = next((span for span in segment if not _is_colon(span.text)), None)
    if first is None or value_x is None:
        return False
    return abs(first.x - value_x) <= VALUE_COLUMN_TOLERANCE * max(first.height, 1.0)


def _segments(row: list[Span], value_x: float | None) -> list[list[Span]]:
    """Layout columns of one row, with each label box rejoined to its own value box.

    Position decides, not wording: a village printed "DESA SUKAMAJU" starts with a
    label word but sits in the value column, where no label is ever printed.
    """
    label_gaps = frozenset(i for i, span in enumerate(row[:-1]) if _label_only(span.text))
    joined: list[list[Span]] = []
    for segment in split_columns(row, label_gaps):
        if (joined and _label_only(" ".join(span.text.strip() for span in joined[-1]))
                and _in_value_column(segment, value_x)):
            joined[-1] = joined[-1] + segment
        else:
            joined.append(segment)
    return joined


def _continuation_allowed(key: str, text: str) -> bool:
    """A wrapped line must look like more of the same field, not a misread label row."""
    if key == "address":
        return True
    if key == "full_name":
        # "Tempat/TgILahir : BANDUNG, 15-08-1990" fails a label match when the l reads as
        # I. Requiring letters only keeps a birth line from being appended to the name.
        return bool(text) and all(c.isalpha() or c in " .,'-" for c in text)
    return False


def _recover_name(parsed: Parsed, table: list[list[Span]], value_x: float | None) -> None:
    """Keep a name whose label was missed as a review candidate, using its row.

    Both the NIK and birth row must bracket exactly one line in the measured value
    column. No label or birth text is repaired, and layout alone never accepts a name.
    """
    if parsed.fields.get("full_name") or value_x is None:
        return
    boundaries = {}
    for index, row in enumerate(table):
        match = LABEL_RE.match(" ".join(s.text.strip() for s in _segments(row, value_x)[0]))
        if match and match.lastgroup in {"nik", "birth"}:
            boundaries.setdefault(match.lastgroup, []).append(index)
    if len(boundaries.get("nik", [])) != 1 or len(boundaries.get("birth", [])) != 1:
        return
    before, after = boundaries["nik"][0], boundaries["birth"][0]
    if after != before + 2:
        return
    row = table[before + 1]
    # A damaged label can be a separate box at the left. Only boxes actually in
    # the value column may supply the name; issuing captions sit far to its right.
    start = next((i for i, s in enumerate(row)
                  if abs(s.x - value_x) <= 1.5 * max(s.height, 1)), None)
    if start is None:
        return
    candidate = split_columns(row[start:])[0]
    text = " ".join(s.text.strip() for s in candidate).strip(" :;|")
    if (not _continuation_allowed("full_name", text) or LABEL_RE.match(text)
            or sum(c.isalpha() for c in text) < 2):
        return
    gap = table[after][0].center_y - table[before][0].center_y
    if not 0 < gap <= 6 * max(s.height for s in row):
        return
    _store(parsed, "full_name", text, table[before] + candidate + table[after],
           ["unlabeled_name_requires_review"], candidate)


def recovery_spans(spans: list[Span], keys: set[str]) -> list[Span]:
    """Bound a retry around the identity/address rows, keeping neighbouring context.

    Use surrounding labels as well as the failed field: its own label or text may
    be completely absent from the first read. Keep wrapped lines inside the block.
    """
    labels = set()
    if keys & {"nik", "full_name", "birth_date", "gender"}:
        labels.update(("nik", "full_name", "birth", "gender"))
    if keys & {"address", "rt", "rw", "village", "district"}:
        labels.update(("gender", "address", "rt_rw", "village", "district", "religion"))
    table = rows(normalized(spans, fold_accents=True))
    value_x = _value_column(table)
    segments = [_segments(row, value_x)[0] for row in table]
    indexes = []
    for index, segment in enumerate(segments):
        match = LABEL_RE.match(" ".join(s.text.strip() for s in segment))
        if match and match.lastgroup in labels:
            indexes.append(index)
    if len(indexes) < 2:
        return []
    return [s for segment in segments[max(0, min(indexes) - 1):max(indexes) + 2] for s in segment]


def parse(spans: list[Span]) -> Parsed:
    parsed = Parsed()
    seen_labels: set[str] = set()
    previous_key: str | None = None
    previous_row: list[Span] = []
    previous_had_value = False
    value_left = 0.0
    # An address whose wrapped line is not closed off by a later labelled row: there is
    # nothing below it to prove where the address ends, so its extent stays a guess.
    open_addresses: list[tuple[Observation, int]] = []
    # e-KTP data is printed in plain capitals and digits, without diacritics.
    table = rows(normalized(spans, fold_accents=True))
    value_x = _value_column(table)
    for row_number, row in enumerate(table):
        # The photo column shares baselines with the field column; keep them apart.
        segments = _segments(row, value_x)
        text = " ".join(span.text.strip() for span in segments[0])
        # Headers are only read at the top of the document, never from addresses.
        # \s* not \s+: this model prints "PROVINSIJAWABARAT" without the space.
        header = re.fullmatch(label_word("PROVINSI") + r"\s*(.+)", text, re.I) if row_number < 4 else None
        city = re.fullmatch(r"(?:" + label_word("KOTA") + r"|" + label_word("KABUPATEN") + r"|"
                            + label_word("KAB") + r"\.)\s*(.+)", text, re.I) if row_number < 4 else None
        if header or city:
            parsed.add("province" if header else "city", (header or city)[1], segments[0])
            previous_key = None
            continue
        matched_any = False
        for segment in segments:
            segment_text = " ".join(span.text.strip() for span in segment)
            found = list(LABEL_RE.finditer(segment_text))
            # A value can itself contain a label word (e.g. a person named "NAMA ..."
            # or an address containing "DESA"). Only the gender/blood row has two labels.
            matches = [found[0]] if found and found[0].start() == 0 else []
            if matches and matches[0].lastgroup == "gender":
                blood = next((m for m in found[1:] if m.lastgroup == "blood_type"), None)
                if blood is not None:
                    matches.append(blood)
            if not matches:
                continue
            matched_any = True
            # Map text character ranges back to the OCR boxes providing evidence.
            ranges = []
            offset = 0
            for span in segment:
                ranges.append((offset, offset + len(span.text.strip()), span))
                offset += len(span.text.strip()) + 1
            for i, match in enumerate(matches):
                key = match.lastgroup
                seen_labels.add(key)
                end = matches[i + 1].start() if i + 1 < len(matches) else len(segment_text)
                value = segment_text[match.end() : end].strip(" :;|")
                evidence = [s for left, right, s in ranges if right > match.start() and left < end]
                printed = [s for left, right, s in ranges if right > match.end() and left < end]
                _store(parsed, key, value, evidence, [], printed or evidence)
                if not value or key in CONTINUABLE:
                    previous_key, previous_row, previous_had_value = key, segment, bool(value)
                    # A wrapped line aligns with the first value box, not with the last
                    # word of a value the recogniser returned as several boxes.
                    value_left = next((s.x for left, right, s in ranges
                                       if match.start() < left < end and right > match.end()), segment[0].x)
                else:
                    previous_key = None
        if matched_any:
            # A recognised label row closes the address block above it. Between "Alamat"
            # and the next label there is no other field the wrapped line could belong
            # to, so its extent is determined by the layout, not guessed.
            # A recognised label row closes the address block above it. One wrapped line
            # is the ordinary KTP layout; a block that absorbed more than that is not
            # settled by the closing label alone and stays flagged.
            open_addresses = [item for item in open_addresses if item[1] > 1]
            continue
        if previous_key and previous_row:
            row = segments[0]
            text = " ".join(span.text.strip() for span in row)
            distance = row[0].center_y - previous_row[0].center_y
            # A wrapped value stays inside the value column; a new field starts at the left.
            aligned = row[0].x >= value_left - 0.5 * max(s.height for s in row)
            if 0 < distance < 2.5 * max(s.height for s in previous_row):
                if not previous_had_value:
                    # The issuing place under the photo is not the value of a label whose
                    # own value the recogniser missed.
                    if value_x is None or _in_value_column(row, value_x):
                        _store(parsed, previous_key, text, previous_row + row, ["label_on_previous_row"])
                elif aligned and _continuation_allowed(previous_key, text) and parsed.fields.get(previous_key):
                    previous = parsed.fields[previous_key][-1]
                    previous.value = re.sub(r"\s+", " ", previous.value + " " + text).strip()
                    previous.spans.extend(row)
                    # The wrapped line is printed value too, so it counts toward the score.
                    if previous.value_spans is not None:
                        previous.value_spans.extend(row)
                    if previous_key == "address":
                        lines = next((n for obs, n in open_addresses if obs is previous), 0) + 1
                        open_addresses = [item for item in open_addresses if item[0] is not previous]
                        open_addresses.append((previous, lines))
                        # An address can wrap more than once. Keep the block open and
                        # measure the next line from this one, so a third line is
                        # assembled rather than silently dropped.
                        previous_row = row
                        value_left = min(value_left, row[0].x)
                        continue
        previous_key = None
    for observation, _ in open_addresses:
        observation.issues.append("multiline_address_requires_review")
    _recover_name(parsed, table, value_x)
    parsed.anchors = len(seen_labels)
    return parsed


# This recogniser reads a plain capital I as the digit 1 confidently, and the same way in
# every re-read of the crop: a card printing block "I-1" came back as "1-1" at 0.98.
# So a one-character block code "1" (or "l") in front of a dash or slash stays a review
# candidate however many passes agree; a block code actually read as "I" goes against
# that bias and is kept. After a dash, where a number is expected, a lone I or l is the
# opposite confusion and is held as well.
AMBIGUOUS_BLOCK_RE = re.compile(r"(?:^|(?<=[\s/]))[1l](?=[-/])|(?<=[-/])[Il](?=$|[\s/.])")


def review_lookalikes(fields: dict[str, FieldResult]) -> None:
    address = fields["address"]
    if address.candidate and AMBIGUOUS_BLOCK_RE.search(address.candidate):
        flag(address, "ambiguous_block_character")


def cross_validate(
    fields: dict[str, FieldResult], strict: bool = False, corroborate_gender: bool = False
) -> None:
    nik, birth, gender = fields["nik"], fields["birth_date"], fields["gender"]
    if not nik.candidate or not re.fullmatch(r"[0-9]{16}", nik.candidate):
        return
    value = nik.candidate
    if not birth.candidate or not gender.candidate:
        flag(nik, "printed_birth_date_and_gender_required")
    # A printed value that agrees with the NIK encoding corroborates it even when that
    # field is itself under review for its own OCR score. Set strict=True to require
    # both corroborating fields to be accepted outright.
    if strict and (birth.status != "accepted" or gender.status != "accepted"):
        flag(nik, "cross_check_field_requires_review")
    if birth.candidate:
        try:
            born = date.fromisoformat(birth.candidate)
        except ValueError:
            flag(nik, "birth_date_cannot_be_cross_checked")
        else:
            encoded_day = int(value[6:8])
            day = encoded_day - 40 if encoded_day > 40 else encoded_day
            if (day, int(value[8:10]), int(value[10:12])) != (born.day, born.month, born.year % 100):
                flag(nik, "nik_birth_date_mismatch")
                flag(birth, "nik_birth_date_mismatch")
    if gender.candidate in {"LAKI-LAKI", "PEREMPUAN"}:
        encoded_gender = "PEREMPUAN" if int(value[6:8]) > 40 else "LAKI-LAKI"
        if gender.candidate != encoded_gender:
            flag(nik, "nik_gender_mismatch")
            flag(gender, "nik_gender_mismatch")
        elif corroborate_gender and nik.status == "accepted" and gender.status == "review":
            # Two separately printed regions of the card agree. That settles a reading the
            # recogniser was merely unsure of; it does not settle one that failed
            # validation, so only confidence-related reasons can be cleared this way.
            if set(gender.reasons) <= {"low_ocr_score", "second_read_required"}:
                gender.value = gender.candidate
                gender.status = "accepted"
                gender.reasons = ["corroborated_by_nik"]
