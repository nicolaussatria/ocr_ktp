import re
import unicodedata
from dataclasses import dataclass, field
from statistics import median

from ..schemas import Candidate, Evidence, FieldResult, Span

# The recogniser's dictionary is shared with Chinese text, so it often returns the
# fullwidth form of printed ASCII punctuation: "：BANDUNG" carries U+FF1A, which no
# strip(" :") removes, so it used to end up inside birth_place, blood_type and
# valid_until. Compatibility normalization maps fullwidth letters, digits and marks to
# ASCII; the CJK marks and dashes it leaves alone are mapped explicitly. Only the code
# point changes, never which character was read.
PUNCTUATION = str.maketrans({"、": ",", "。": ".",
                             "‐": "-", "‑": "-", "–": "-", "—": "-", "―": "-", "−": "-"})


def normalize_text(text: str, fold_accents: bool = False) -> str:
    text = unicodedata.normalize("NFKC", text).translate(PUNCTUATION)
    if fold_accents:
        # "DEWÍ" is the recogniser decorating the I of "DEWI".
        decomposed = unicodedata.normalize("NFKD", text)
        text = unicodedata.normalize("NFC", "".join(c for c in decomposed if not unicodedata.combining(c)))
    return text


def normalized(spans: list[Span], fold_accents: bool = False) -> list[Span]:
    """Parser view of the OCR boxes; raw_ocr keeps the recogniser's own code points.

    ``fold_accents`` is for documents printed without diacritics, such as the KTP,
    where an accented letter can only be a misread of the plain one.
    """
    result = []
    for span in spans:
        text = normalize_text(span.text, fold_accents)
        result.append(span if text == span.text else span.model_copy(update={"text": text}))
    return result


@dataclass
class Observation:
    value: str
    spans: list[Span]
    issues: list[str] = field(default_factory=list)
    # Boxes covering the printed value. The label box is kept in ``spans`` as evidence
    # but must not drag the score down: the label was matched by pattern, so a shaky
    # reading of "RT/RW" says nothing about how well "001/018" was read.
    value_spans: list[Span] | None = None
    assignment: str | None = None
    contact_index: int = 0
    # Score a number by its weakest digit rather than by the average character.
    digits: bool = False
    # A telephone number's kind: mobile, landline or fax; None when nothing tells.
    kind: str | None = None

    @property
    def score(self) -> float:
        """Weakest box of the printed value, each scored on its printed characters.

        A box that holds only a separator (a lone colon) is not part of the value. A NIK
        is scored by its weakest digit: an average over sixteen digits would hide the one
        the recogniser doubted, while the colon in front of it is no reason for doubt.
        """
        spans = self.value_spans or self.spans
        printed = [span for span in spans if span.text.strip(" :;|")] or spans
        return min((_value_score(span, self.digits) for span in printed), default=0.0)


def _value_score(span: Span, digits: bool) -> float:
    if digits and span.digit_score is not None:
        return span.digit_score
    return span.score if span.content_score is None else span.content_score


@dataclass
class Parsed:
    fields: dict[str, list[Observation]] = field(default_factory=dict)
    anchors: int = 0

    def add(
        self,
        key: str,
        value: str,
        spans: list[Span],
        issues: list[str] | None = None,
        value_spans: list[Span] | None = None,
        assignment: str | None = None,
        contact_index: int = 0,
        digits: bool = False,
        kind: str | None = None,
    ):
        value = re.sub(r"\s+", " ", value).strip(" :;|")
        if value:
            self.fields.setdefault(key, []).append(
                Observation(value, spans, issues or [], value_spans or None, assignment, contact_index, digits, kind)
            )


# Boxes starting within this many glyph heights of the field column's left edge anchor
# rows: the labels, including the indented RT/RW, Kel/Desa and Kecamatan labels.
ROW_ANCHOR_WIDTH = 3.0


def _in_line(span: Span, other: Span) -> bool:
    return abs(span.center_y - other.center_y) <= 0.45 * max(span.height, other.height)


def rows(spans: list[Span]) -> list[list[Span]]:
    """Cluster boxes into printed rows, each ordered left to right (not OCR array order).

    Rows are anchored on the field column's left edge. The boxes that start there form
    the rows, lining up with every anchor already in a row; every other box then joins the
    anchored row it lines up with best. A box that lines up with no anchored row (a wrapped
    line, a header, the photo block) starts a row of its own. Anchoring matters on photos
    whose rows are 20 px apart: the issuing place or date under the photo sits between two
    field rows, and grouping in reading order let it bridge them, or claim a label while
    pushing that label's value into a row of its own. Without a clear left column (a
    business card, a sideways read) every box is an anchor.
    """
    spans = sorted((s for s in spans if s.text.strip()), key=lambda s: (s.center_y, s.x))
    if not spans:
        return []
    reach = ROW_ANCHOR_WIDTH * median(s.height for s in spans)
    edges = sorted(s.x for s in spans)
    left = next((x for x in edges if sum(x <= other <= x + reach for other in edges) >= 3), None)
    anchored = [s for s in spans if left is not None and s.x <= left + reach]
    if len(anchored) < 3:
        anchored = spans
    groups: list[tuple[list[Span], list[Span]]] = []
    for span in anchored:
        match = next((g for g in reversed(groups) if all(_in_line(span, a) for a in g[0])), None)
        if match is None:
            groups.append(([span], [span]))
        else:
            match[0].append(span)
            match[1].append(span)
    chosen = {id(s) for s in anchored}
    for span in spans:
        if id(span) in chosen:
            continue
        fitting = [g for g in groups if all(_in_line(span, a) for a in (g[0] or g[1]))]
        if fitting:
            best = min(fitting, key=lambda g: abs(span.center_y - median(a.center_y for a in (g[0] or g[1]))))
            best[1].append(span)
        else:
            groups.append(([], [span]))
    ordered = sorted(groups, key=lambda g: median(a.center_y for a in (g[0] or g[1])))
    return [sorted(members, key=lambda s: s.x) for _, members in ordered]


# A KTP's photo block (issuing city, date, signature) sits on the same baselines as
# the field column. A break is judged against the row's own other gaps rather than an
# absolute pixel figure, so label-to-value spacing survives and the photo block splits
# off. A two-span row is always label plus value and is never split.
COLUMN_GAP_HEIGHTS = 3.0
COLUMN_GAP_DOMINANCE = 2.0
# A two-span row is normally a label and its value, so it is not split against the row's
# own gaps — there is only one. The photo block is still separable by scale: measured
# across cards, a KTP label-to-value gap runs 3.6 to 5.9 times the glyph height, while
# the jump across to the photo column runs 10 to 14 times.
COLUMN_GAP_ISOLATED = 8.0


def split_columns(row: list[Span], label_gaps: frozenset[int] = frozenset()) -> list[list[Span]]:
    """Split one visual row into layout columns separated by a dominant gap.

    ``label_gaps`` holds the indexes of gaps that follow a box holding only a field
    label. With colons printed in an aligned column that gap is as wide as the jump to
    the photo block, so it is left out when judging what a typical gap in the row is.
    """
    if len(row) == 2:
        reference = min(row[0].height, row[1].height)
        if reference > 0 and row[1].x - row[0].right > COLUMN_GAP_ISOLATED * reference:
            return [[row[0]], [row[1]]]
        return [row]
    if len(row) < 3:
        return [row]
    gaps = [row[i + 1].x - row[i].right for i in range(len(row) - 1)]
    groups: list[list[Span]] = [[row[0]]]
    for i, gap in enumerate(gaps):
        others = sorted(other for j, other in enumerate(gaps) if j != i and j not in label_gaps)
        typical = max(others[len(others) // 2], 1.0) if others else 1.0
        reference = min(row[i].height, row[i + 1].height)
        if gap > COLUMN_GAP_HEIGHTS * reference and gap > COLUMN_GAP_DOMINANCE * typical:
            groups.append([row[i + 1]])
        else:
            groups[-1].append(row[i + 1])
    return groups


def agreement_key(value: str) -> str:
    """Two passes agree when only spacing or punctuation differs, not characters."""
    return re.sub(r"[^0-9A-Z]", "", value.upper())


def resolve(
    observations: list[Observation],
    threshold: float,
    consensus: bool,
    single_pass_threshold: float | None = None,
) -> FieldResult:
    if not observations:
        return FieldResult(reasons=["not_found"])
    grouped: dict[str, list[Observation]] = {}
    for item in observations:
        # Group on the agreement key so "ANDREAS SURYA" and "ANDREASSURYA" from two
        # passes count as the same reading instead of a conflict.
        grouped.setdefault(agreement_key(item.value), []).append(item)
    candidates = []
    for group in grouped.values():
        evidence = []
        seen = set()
        for item in group:
            for span in item.spans:
                marker = (span.pass_id, span.text, str(span.box))
                if marker not in seen:
                    seen.add(marker)
                    evidence.append(Evidence(**span.model_dump()))
        # Readings in a group agree on letters and digits, but punctuation is part of a
        # value: "NO.5A" and "NO 5A" are different addresses. The form most passes read
        # wins; between equally backed forms, the one with more marks, since this model
        # loses a faint full stop more often than it invents one. Then the surface that
        # preserved the most word separators; spaces are dropped far more often than added.
        forms: dict[str, set[str]] = {}
        for item in group:
            forms.setdefault(re.sub(r"\s+", "", item.value), set()).update(
                span.pass_id for span in item.value_spans or item.spans)
        form = max(forms, key=lambda f: (len(forms[f]), sum(not c.isalnum() for c in f)))
        display = max((o for o in group if re.sub(r"\s+", "", o.value) == form),
                      key=lambda o: (len(o.value.split()), o.score)).value
        unsettled = len(forms) > 1 and len(forms[form]) < 2
        # Each pass contributes its best reading of the value, and the field is scored
        # by the weaker of the two strongest passes (or the only one). A further, less
        # confident pass that reads the same value is support, not doubt: with the
        # minimum over every read, adding a magnified retry could only lower the score
        # of a NIK that two passes had already read at 0.99.
        per_pass: dict[str, float] = {}
        for item in group:
            for pass_id in {span.pass_id for span in item.value_spans or item.spans}:
                per_pass[pass_id] = max(per_pass.get(pass_id, 0.0), item.score)
        strongest = sorted(per_pass, key=lambda pass_id: per_pass[pass_id], reverse=True)[:2]
        candidate = Candidate(
            value=display,
            ocr_score=round(min(per_pass[p] for p in strongest), 4),
            issues=sorted({issue for o in group for issue in o.issues}),
            evidence=evidence,
            supporting_passes=sorted(strongest),
        )
        qualifying = sum(score >= threshold for score in per_pass.values())
        candidates.append((candidate, qualifying, len(per_pass), unsettled))
    # A reading that failed field validation must never outrank a clean one, however
    # high its OCR score: "LAKHLAKI" at 0.96 is a misread, "LAKI-LAKI" at 0.91 is not.
    # Then reads that cleared the threshold count before reads that merely exist: two
    # passes reading "F1ON/3" at 0.55 are not better evidence than one reading at 0.96.
    candidates.sort(key=lambda item: (not item[0].issues, item[1], item[2], item[0].ocr_score), reverse=True)
    unsettled = candidates[0][3]
    candidates = [candidate for candidate, _, _, _ in candidates]
    best = candidates[0]
    # Only a reading we would accept on its own can veto another one. A sub-threshold or
    # invalid alternative is noise from one pass, not a genuine disagreement.
    rivals = [c for c in candidates[1:] if c.ocr_score >= threshold and not c.issues]
    reasons = list(best.issues)
    if rivals:
        reasons.append("conflicting_readings")
    if unsettled:
        reasons.append("punctuation_differs")
    if best.ocr_score < threshold:
        reasons.append("low_ocr_score")
    if consensus and len(best.supporting_passes) < 2:
        if single_pass_threshold is None or best.ocr_score < single_pass_threshold:
            reasons.append("second_read_required")
    accepted = not reasons
    return FieldResult(
        value=best.value if accepted else None,
        candidate=best.value,
        status="accepted" if accepted else "review",
        ocr_score=best.ocr_score,
        reasons=sorted(set(reasons)),
        candidates=candidates,
    )


def flag(result: FieldResult, reason: str) -> None:
    if result.candidate is not None:
        result.value = None
        result.status = "review"
        result.reasons = sorted(set(result.reasons + [reason]))


# This recogniser reads some printed glyphs as their lookalikes: the lowercase l of
# "Tgl." as I or 1, the u of "Berlaku" as y, and the usual o/0, s/5, b/8, z/2 pairs.
# A label is a fixed printed word, so the documented lookalikes are accepted while
# matching it; the value after the label is still taken from the untouched text.
LOOKALIKES = {
    "I": "IL1li",
    "L": "IL1li",
    "U": "UY",
    "O": "O0",
    "S": "S5",
    "B": "B8",
    "Z": "Z2",
}


def label_word(text: str) -> str:
    """A fixed printed word, with each lookalike letter accepting its confusion set."""
    return "".join(f"[{LOOKALIKES[character]}]" if character in LOOKALIKES else re.escape(character)
                   for character in text)


# Closed printed vocabularies (gender, blood group, marital status, nationality) are
# matched after folding the same lookalikes onto one character. Two readings that
# differ only by a documented lookalike are the same printed category; anything else
# stays unrecognized. Open text such as a name or street is never folded.
CATEGORY_FOLD = str.maketrans({"1": "I", "l": "I", "|": "I", "L": "I",
                               "0": "O", "5": "S", "8": "B", "2": "Z", "Y": "U"})


def folded_category(text: str) -> str:
    """Upper-case and fold lookalikes onto one character; callers strip spacing they ignore."""
    return text.upper().translate(CATEGORY_FOLD)


# "Jl." is this recogniser reading the lowercase l as I or 1: the Indonesian street
# abbreviation is fixed, so the prefix is written out instead of keeping one recorded
# glyph confusion uncertain forever. Only the two ambiguous characters change; the rest
# of the line, the spacing and the raw reading in the evidence boxes are untouched.
STREET_PREFIX_RE = re.compile(r"^J[lI1i](\.\s*)")


def canonical_street(text: str) -> tuple[str, list[str]]:
    match = STREET_PREFIX_RE.match(text)
    if match:
        tail = text[match.end() :]
        return ("JL" if tail[:8].isupper() else "Jl") + text[match.start(1) :], []
    if re.match(r"^[HJ]\s*\.?\s+", text) and not re.match(r"^Jl\.", text, re.I):
        return text, ["uncertain_street_prefix"]
    return text, []
