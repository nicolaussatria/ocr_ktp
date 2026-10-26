from typing import Literal

from pydantic import BaseModel, Field

DocumentType = Literal["ktp", "business_card", "auto"]
Mode = Literal["fast", "accurate"]


class Span(BaseModel):
    text: str
    score: float = Field(ge=0, le=1)
    box: list[list[float]]
    pass_id: str = "original"
    # Internal scores from the recogniser's per-character confidences, when available;
    # never serialized. ``score`` averages every decoded character, including word
    # breaks and the colon after a label, which are the characters this recogniser is
    # least sure of and which no field value contains. ``content_score`` averages only
    # the printed characters; ``digit_score`` is the weakest digit.
    content_score: float | None = Field(default=None, exclude=True, repr=False)
    digit_score: float | None = Field(default=None, exclude=True, repr=False)
    # Word breaks the engine inserted from the recogniser's ratings, as the number of
    # letters and digits before each; the respacer keeps them. Internal, never serialized.
    kept_breaks: list[int] | None = Field(default=None, exclude=True, repr=False)
    # Whether the line classifier found this line upside down and turned it before it was
    # read; None when the engine does not say. Internal, never serialized.
    flipped: bool | None = Field(default=None, exclude=True, repr=False)

    @property
    def x(self) -> float:
        return min(p[0] for p in self.box)

    @property
    def y(self) -> float:
        return min(p[1] for p in self.box)

    @property
    def right(self) -> float:
        return max(p[0] for p in self.box)

    @property
    def height(self) -> float:
        return max(p[1] for p in self.box) - self.y

    @property
    def center_y(self) -> float:
        return self.y + self.height / 2


class Evidence(BaseModel):
    text: str
    score: float
    box: list[list[float]]
    pass_id: str


class Candidate(BaseModel):
    value: str
    ocr_score: float
    issues: list[str] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    supporting_passes: list[str] = Field(default_factory=list)
    assignment: str | None = None


class FieldResult(BaseModel):
    value: str | None = None
    candidate: str | None = None
    status: Literal["accepted", "review", "missing"] = "missing"
    ocr_score: float | None = None
    reasons: list[str] = Field(default_factory=list)
    candidates: list[Candidate] = Field(default_factory=list)
    assignment: str | None = None
    # Business-card telephone numbers only: what kind of line the number is.
    phone_type: Literal["mobile", "landline", "fax"] | None = None


class Quality(BaseModel):
    width: int
    height: int
    sharpness: float
    contrast: float
    warnings: list[str] = Field(default_factory=list)
    text_height_px: float | None = None


class PassInfo(BaseModel):
    id: str
    rotation_clockwise: int
    enhancement: str
    width: int
    height: int
    ocr_ms: float
    # Maps pass coordinates to the EXIF-corrected, resized input before rotation.
    to_input: list[list[float]] | None = None


class Processing(BaseModel):
    mode: Mode
    elapsed_ms: float
    engine: str
    models: dict[str, str]
    model_hashes: dict[str, str] = Field(default_factory=dict)
    passes: list[PassInfo]
    phone_region: str | None = None


class OCRResponse(BaseModel):
    schema_version: str = "1.0"
    request_id: str
    document_type: Literal["ktp", "business_card"]
    status: Literal["ok", "needs_review"]
    needs_review: bool
    data: dict[str, str | None | list[str]]
    fields: dict[str, FieldResult | list[FieldResult]]
    review_reasons: list[str]
    quality: Quality
    processing: Processing
    raw_ocr: list[Span] | None = None
    verification: Literal["ocr_only_not_identity_verification"] = "ocr_only_not_identity_verification"


class ErrorBody(BaseModel):
    code: str
    message: str


class ErrorResponse(BaseModel):
    error: ErrorBody
