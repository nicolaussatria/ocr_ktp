from hashlib import sha256
from importlib.metadata import version
from pathlib import Path
from typing import Protocol

import cv2
import numpy as np

from .config import Settings
from .schemas import Span

MODELS = {
    "det": "PP-OCRv6_det_small.onnx",
    "rec": "PP-OCRv6_rec_small.onnx",
    "cls": "ch_ppocr_mobile_v2.0_cls_mobile.onnx",
}
# From the model registry shipped in rapidocr 3.9.2. No runtime downloads.
MODEL_HASHES = {
    "det": "090f04abcd9d9a7498bc4ebf677e4cb9bdce1fe4197ddb7e529f1ef44e1ff94f",
    "rec": "6f327246b50388f3c176ae304bd95767ea6dc0c9ae92153ef8cbe210b3c14884",
    "cls": "e47acedf663230f8863ff1ab0e64dd2d82b838fceb5957146dab185a89d6215c",
}


class Engine(Protocol):
    name: str
    models: dict[str, str]
    hashes: dict[str, str]

    def recognize_crop(self, patch: np.ndarray) -> str | None:
        """Recognition only, no detection: re-read one already-cropped word."""
        output = self._engine(patch, use_det=False, use_cls=False, use_rec=True)
        if not output.txts:
            return None
        return str(output.txts[0]).strip()

    def recognize(self, image: np.ndarray, pass_id: str) -> list[Span]: ...


class _CharacterConfidence:
    """Have the recogniser keep its per-character confidences for every decoded line.

    RapidOCR's own word and single-character boxes pair those confidences with a
    space-free character list, which shifts every value after the first space
    (rapidocr 3.9.2). The list taken here, before that step, is aligned with the decoded
    line including its spaces. RapidOCR's word-box step stays off, so nothing else changes.
    The crops the recogniser read are also used to confirm rated word breaks.
    """

    def __init__(self, recognizer, orientation=None):
        self._recognizer = recognizer
        self._orientation = orientation

    def __call__(self, request):
        request.return_word_box = True
        output = self._recognizer(request)
        crops = [request.img] if isinstance(request.img, np.ndarray) else list(request.img or ())
        for crop, info in zip(crops, output.word_results or (), strict=False):
            _measure_rated_breaks(crop, info)
        flipped = self._orientation.take() if self._orientation is not None else None
        if flipped is not None and len(flipped) == len(crops) == len(output.word_results or ()):
            for info, flag in zip(output.word_results, flipped, strict=True):
                info.flipped = flag
        return output


class _LineOrientation:
    """Keep what the line classifier decided for each line of the read in progress.

    RapidOCR turns a line the classifier calls upside down and reads it, but does not
    report that it did. Which lines were turned says how the whole card lies: a card
    photographed sideways or upside down is read line by line all the same, with its
    layout standing on its head.
    """

    def __init__(self, classifier):
        self._classifier = classifier
        self._flipped = None

    def __getattr__(self, name):
        return getattr(self._classifier, name)

    def __call__(self, images):
        output = self._classifier(images)
        threshold = self._classifier.cls_thresh
        self._flipped = [("180" in label and score > threshold) for label, score in output.cls_res or ()]
        return output

    def take(self):
        flipped, self._flipped = self._flipped, None
        return flipped


class _BreakEvidence:
    """Record, for each decoded character, how strongly a word break before it was rated.

    The CTC decoder keeps only the best symbol at each step. A narrow printed space often
    loses to the letters around it although the model still rated it: on photographed
    e-KTP print "PEKALONGANBARAT" had the break before "BARAT" at 0.46.
    """

    def __init__(self, decoder):
        self._decoder = decoder

    def __getattr__(self, name):
        return getattr(self._decoder, name)

    def __call__(self, preds, return_word_box=False, **kwargs):
        space = self._decoder.dict.get(" ")
        if space is None or not return_word_box:
            return self._decoder(preds, return_word_box, **kwargs)
        # The same decoding RapidOCR's CTCLabelDecode performs, with the best-symbol index
        # computed once for both uses: over 18,710 classes it is the costly step.
        index = preds.argmax(axis=2)
        best = np.take_along_axis(preds, index[..., None], axis=2)[..., 0]
        ratios = kwargs.get("wh_ratio_list", (1.0,))
        padded = kwargs.get("max_wh_ratio", 1.0)
        lines, words = self._decoder.decode(index, best, return_word_box, ratios, padded, remove_duplicate=True)
        if len(words) != len(preds):
            return lines, words
        ignored = self._decoder.get_ignored_tokens()
        for row, info in enumerate(words):
            tokens = index[row]
            keep = np.ones(len(tokens), dtype=bool)
            keep[1:] = tokens[1:] != tokens[:-1]
            for token in ignored:
                keep &= tokens != token
            steps = np.flatnonzero(keep)
            info.breaks = [0.0] + [float(preds[row, before + 1 : step + 1, space].max())
                                   for before, step in zip(steps, steps[1:], strict=False)]
            # Horizontal position of each character as a fraction of the crop width: the
            # line is resized to the input height and padded to the widest line of the batch.
            used = min(ratios[row], padded) / padded
            info.positions = [(step + 0.5) / len(tokens) / used for step in steps]
        return lines, words


# Word breaks the recogniser rated but did not decode. Inside words on photographed and
# synthetic KTP lines the rating stayed below 0.002; the breaks it had dropped on
# photographed e-KTP print were rated 0.012 to 0.49. Monospace print is the exception: its
# wide letter spacing drew ratings up to 0.03 inside words ("A|lamat"). So a rated break
# also needs the ink to part: a blank run between the two characters of at least
# BREAK_GAP of the line height and clearly wider than the line's own letter spacing (its
# 90th-percentile gap between unrated letters) -- BREAK_SPACING times for a rating of
# BREAK_CERTAIN or more, BREAK_SPACING_WEAK times for a weaker one from BREAK_POSSIBLE.
# Measured: every real break cleared 1.9 times its line's letter spacing; "A|lamat" 1.7.
# Ratings below BREAK_POSSIBLE are left alone: the band down to 0.005 held one real break
# and three non-breaks, too close to the noise floor to be worth the risk.
BREAK_CERTAIN = 0.05
BREAK_POSSIBLE = 0.01
BREAK_UNRATED = 0.005
BREAK_GAP = 0.12
BREAK_SPACING = 1.5
BREAK_SPACING_WEAK = 2.0
BREAK_AFTER = frozenset(",:;，：；")


def _blank_runs(crop, positions) -> list[float]:
    """Longest blank column run between each character and the one before it, per height."""
    height, width = crop.shape[:2]
    gray = crop if crop.ndim == 2 else cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    _, ink = cv2.threshold(cv2.GaussianBlur(gray, (3, 3), 0), 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    blank = (ink > 0).sum(axis=0) <= max(1, int(0.04 * height))
    runs = [0.0]
    for before, after in zip(positions, positions[1:], strict=False):
        run = longest = 0
        for empty in blank[max(int(before * width), 0) : min(int(np.ceil(after * width)), width)]:
            run = run + 1 if empty else 0
            longest = max(longest, run)
        runs.append(longest / height)
    return runs


def _measure_rated_breaks(crop, info) -> None:
    """Keep, for each rated break, whether the ink parts widely enough to confirm it."""
    breaks = getattr(info, "breaks", None)
    positions = getattr(info, "positions", None)
    if not breaks or not positions or len(breaks) != len(positions) or crop is None or crop.size == 0:
        return
    rated = [k for k in range(1, len(breaks)) if breaks[k] >= BREAK_POSSIBLE]
    if not rated:
        return
    runs = _blank_runs(crop, positions)
    unrated = [runs[k] for k in range(1, len(breaks)) if breaks[k] < BREAK_UNRATED]
    spacing = float(np.quantile(unrated, 0.9)) if unrated else 0.0
    info.confirmed = {
        k for k in rated
        if runs[k] >= max(BREAK_GAP, (BREAK_SPACING if breaks[k] >= BREAK_CERTAIN else BREAK_SPACING_WEAK) * spacing)
    }


def _with_rated_breaks(text: str, info) -> tuple[str, list[int]]:
    """Insert the word breaks the recogniser rated but did not decode, where the ink agrees.

    Only between two letters, or between a colon or comma and the next word: a space
    inside a number, a date, or after the full stop of "JL." would change the value.
    Also returns where each inserted break sits, counted in letters and digits before it.
    """
    breaks = getattr(info, "breaks", None)
    confirmed = getattr(info, "confirmed", None)
    if not breaks or not confirmed or len(breaks) != len(text):
        return text, []
    result, inserted = [], []
    seen = 0
    for index, character in enumerate(text):
        left = text[index - 1] if index else ""
        if (index in confirmed and left and not left.isspace()
                and (character.isalpha() and (left.isalpha() or left in BREAK_AFTER)
                     or character.isdigit() and left in BREAK_AFTER)):
            result.append(" ")
            inserted.append(seen)
        seen += character.isalnum()
        result.append(character)
    return "".join(result), inserted


# Printed between a label and its value; never part of a value.
SEPARATORS = frozenset(":;|：；｜")


def _character_scores(text: str, info) -> dict[str, float]:
    """Content and weakest-digit scores of one decoded line; empty when unavailable."""
    scores = getattr(info, "confs", None)
    if not scores or len(scores) != len(text):
        return {}
    pairs = [(character, max(0.0, min(1.0, float(score))))
             for character, score in zip(text, scores, strict=True)]
    content = [score for character, score in pairs if not character.isspace() and character not in SEPARATORS]
    digits = [score for character, score in pairs if character.isdigit()]
    result = {}
    if content:
        result["content_score"] = sum(content) / len(content)
    if digits:
        result["digit_score"] = min(digits)
    return result


class RapidEngine:
    def __init__(self, settings: Settings):
        import rapidocr
        from rapidocr import EngineType, ModelType, OCRVersion, RapidOCR

        if version("rapidocr") != "3.9.2":
            raise RuntimeError("Install the pinned rapidocr==3.9.2 package.")
        package_models = Path(rapidocr.__file__).parent / "models"
        paths = {}
        for key, name in MODELS.items():
            override = settings.model_dir / name
            path = override if override.is_file() else package_models / name
            if not path.is_file():
                raise RuntimeError(f"Missing OCR model: {name}; reinstall the pinned package.")
            if sha256(path.read_bytes()).hexdigest() != MODEL_HASHES[key]:
                raise RuntimeError(f"OCR model checksum mismatch: {name}.")
            paths[key] = str(path.resolve())
        cv2.setNumThreads(1)
        self.name = f"RapidOCR {version('rapidocr')} / ONNX Runtime {version('onnxruntime')}"
        self.models = MODELS.copy()
        self.hashes = MODEL_HASHES.copy()
        self._engine = RapidOCR(
            params={
                "Global.log_level": "error",
                "Global.text_score": 0.35,
                "Global.max_side_len": settings.max_side,
                "EngineConfig.onnxruntime.intra_op_num_threads": settings.cpu_threads,
                "EngineConfig.onnxruntime.inter_op_num_threads": 1,
                "Det.engine_type": EngineType.ONNXRUNTIME,
                "Det.ocr_version": OCRVersion.PPOCRV6,
                "Det.model_type": ModelType.SMALL,
                "Det.lang_type": "id",
                "Det.model_path": paths["det"],
                "Det.limit_side_len": 1280,
                "Det.limit_type": "max",
                "Cls.engine_type": EngineType.ONNXRUNTIME,
                "Cls.ocr_version": OCRVersion.PPOCRV4,
                "Cls.model_type": ModelType.MOBILE,
                "Cls.model_path": paths["cls"],
                "Rec.engine_type": EngineType.ONNXRUNTIME,
                "Rec.ocr_version": OCRVersion.PPOCRV6,
                "Rec.model_type": ModelType.SMALL,
                "Rec.lang_type": "id",
                "Rec.model_path": paths["rec"],
                "Rec.rec_batch_num": 8,
            }
        )
        recognizer = self._engine.text_rec
        recognizer.postprocess_op = _BreakEvidence(recognizer.postprocess_op)
        self._engine.text_cls = _LineOrientation(self._engine.text_cls)
        self._engine.text_rec = _CharacterConfidence(recognizer, self._engine.text_cls)

    def recognize_crop(self, patch: np.ndarray) -> str | None:
        """Recognition only, no detection: re-read one already-cropped word.

        Rated breaks are not added here. On a magnified word piece of monospace print the
        model rates breaks inside words ("Kewarganega raan"), and the gap after a narrow
        letter is as wide as a word space; breaks confirmed on the whole line are kept
        by the respacer instead.
        """
        output = self._engine(patch, use_det=False, use_cls=False, use_rec=True)
        if not output.txts:
            return None
        return str(output.txts[0]).strip()

    def recognize(self, image: np.ndarray, pass_id: str) -> list[Span]:
        output = self._engine(image, use_det=True, use_cls=True, use_rec=True)
        if output.txts is None or output.boxes is None or output.scores is None:
            return []
        details = output.word_results if len(output.word_results or ()) == len(output.txts) else ()
        spans = []
        for index, (text, score, box) in enumerate(zip(output.txts, output.scores, output.boxes, strict=True)):
            info = details[index] if details else None
            spaced, inserted = _with_rated_breaks(str(text), info)
            spans.append(Span(
                text=spaced,
                score=max(0, min(1, float(score))),
                box=np.asarray(box).astype(float).round(2).tolist(),
                pass_id=pass_id,
                kept_breaks=inserted or None,
                flipped=getattr(info, "flipped", None),
                **(_character_scores(str(text), info) if info is not None else {}),
            ))
        return spans
