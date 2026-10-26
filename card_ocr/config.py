from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="OCR_", env_file=".env", extra="ignore")

    api_key: str = ""
    ui_username: str = "learner"
    ui_password: str = ""
    cors_origins: list[str] = []
    max_upload_mb: int = Field(default=10, ge=1, le=30)
    max_pixels: int = Field(default=20_000_000, ge=100_000, le=50_000_000)
    max_side: int = Field(default=2000, ge=960, le=3000)
    min_side: int = Field(default=240, ge=100)
    cpu_threads: int = Field(default=2, ge=1, le=16)
    queue_timeout_seconds: float = Field(default=3.0, ge=0.1, le=30)
    field_threshold: float = Field(default=0.93, ge=0.5, le=1)
    nik_threshold: float = Field(default=0.98, ge=0.8, le=1)
    # KTP only: a field seen in one pass may be accepted at this score. NIK is excluded.
    # Set to 1.0 to restore the strict "every accepted value appears in two passes" rule.
    single_pass_threshold: float = Field(default=0.99, ge=0.5, le=1)
    # Require birth date and gender to be accepted outright before accepting a NIK.
    strict_nik_cross_check: bool = False
    # Recover printed word breaks the recogniser dropped, by re-reading each word between
    # the blank pixel columns of a line. Costs one extra pass over long all-letter lines.
    respace_words: bool = True
    # Accept a printed gender that matches the encoding of an already accepted NIK.
    nik_corroborates_gender: bool = True
    # Accurate mode: when the median detected text height is below the small-print
    # threshold, retry a magnified crop of the card text. Applies to both card types.
    small_text_retry: bool = True
    # Accurate KTP: at most two extra reads of the field block when identity or
    # address fields remain missing/uncertain, even when the print is not small.
    ktp_recovery: bool = True
    # Median glyph height, in pixels of the processed input, below which the small-print
    # retry runs. Measured on synthetic degradations: 24 px kept running short of a
    # second read; 32 px cost more passes without extra correct fields.
    small_text_height_px: int = Field(default=28, ge=16, le=64)
    # Retained configuration name from the business-card release: false disables the
    # small-print retry as well, so an existing .env keeps its documented behavior.
    business_retry: bool = True
    # Measure the tilt of the detected text lines. Accurate mode re-reads a levelled view
    # when the page is visibly rotated (one extra read, only on tilted images); fast mode
    # moves the boxes of its single read into the levelled frame instead.
    deskew_retry: bool = True
    # Both modes: when the card outline is visible on a background, read a flattened,
    # full-resolution view of the card instead of the whole photograph. Falls back to
    # the whole image (one extra read) when that view does not classify.
    card_detection: bool = True
    # Business cards: "(021) 5551234, 5551235" prints the area code once. true completes
    # the second landline number with the area code of the first when it has as many
    # digits as the first subscriber number and the result is a valid number. false keeps
    # the short number as printed, as a review candidate.
    shared_area_code: bool = True
    model_dir: Path = Path("models")
    default_phone_region: str = "ID"

    @property
    def max_file_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024
