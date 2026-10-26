"""Evaluate annotated local images without writing images or extracted PII to the report."""

import argparse
import json
from pathlib import Path
from time import perf_counter

import numpy as np

from card_ocr.config import Settings
from card_ocr.engine import RapidEngine
from card_ocr.errors import OCRProblem
from card_ocr.pipeline import OCRPipeline


def same(actual, expected):
    return (
        sorted(actual) == sorted(expected)
        if isinstance(actual, list) and isinstance(expected, list)
        else actual == expected
    )


def _blank_metric():
    return {"evaluated": 0, "correct_final": 0, "accepted": 0, "wrong_accepted": 0, "correct_candidate": 0}


def _aggregate(rows: list[tuple[dict, object, float]]) -> dict:
    fields: dict[str, dict] = {}
    documents_requiring_review = 0
    for entry, response, _ in rows:
        documents_requiring_review += int(response is None or response.needs_review)
        for key, expected in entry["expected"].items():
            metric = fields.setdefault(key, _blank_metric())
            metric["evaluated"] += 1
            actual = response.data.get(key) if response else None
            accepted = actual is not None and actual != []
            correct = same(actual, expected)
            metric["correct_final"] += int(correct)
            metric["accepted"] += int(accepted)
            metric["wrong_accepted"] += int(accepted and not correct)
            field = response.fields.get(key) if response else None
            if isinstance(field, list):
                candidates = [f.candidate for f in field]
                metric["correct_candidate"] += int(same(candidates, expected))
            else:
                metric["correct_candidate"] += int(field is not None and same(field.candidate, expected))
    for metric in fields.values():
        accepted = metric["accepted"]
        metric["accepted_precision"] = (accepted - metric["wrong_accepted"]) / accepted if accepted else None
        metric["acceptance_coverage"] = accepted / metric["evaluated"]
    return {
        "documents": len(rows),
        "documents_requiring_review": documents_requiring_review,
        "fields": fields,
    }


def evaluate(manifest_path: Path, mode="accurate") -> dict:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    settings = Settings()
    pipeline = OCRPipeline(RapidEngine(settings), settings)
    # Warmup excluded from latency statistics.
    pipeline.engine.recognize(np.full((300, 800, 3), 255, dtype=np.uint8), "warmup")
    rows: list[tuple[dict, object, float]] = []
    errors = {}
    for entry in manifest:
        started = perf_counter()
        response = None
        try:
            response = pipeline.process(
                (manifest_path.parent / entry["image"]).read_bytes(), entry["document_type"], mode,
                phone_region=entry.get("phone_region")
            )
        except OCRProblem as exc:
            errors[exc.code] = errors.get(exc.code, 0) + 1
        rows.append((entry, response, (perf_counter() - started) * 1000))
    latencies = [row[2] for row in rows]
    tags: dict[str, list] = {}
    for row in rows:
        for tag in row[0].get("tags", []):
            tags.setdefault(tag, []).append(row)
    result = {
        "dataset_size": len(manifest),
        "mode": mode,
        "model_hashes": pipeline.engine.hashes,
        "errors": errors,
        "latency_ms": {
            "p50": round(float(np.percentile(latencies, 50)), 2),
            "p95": round(float(np.percentile(latencies, 95)), 2),
        }
        if latencies
        else {},
        "note": "Metrics apply only to this dataset and annotated fields. Synthetic samples do not measure real-world accuracy.",
        **_aggregate(rows),
    }
    if tags:
        result["tags"] = {tag: _aggregate(tag_rows) for tag, tag_rows in sorted(tags.items())}
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--mode", choices=["fast", "accurate"], default="accurate")
    parser.add_argument("--output", type=Path, default=Path("evaluation.json"))
    args = parser.parse_args()
    args.output.write_text(json.dumps(evaluate(args.manifest, args.mode), indent=2), encoding="utf-8")
    print(f"Evaluation saved to {args.output}")
