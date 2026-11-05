"""Measure Phase-2 models on the labeled benchmark corpus.

    python scripts/evaluate.py

Every number printed here is computed from real model outputs on the seeded
corpus - nothing is hand-written.  Results are saved to ``var/eval_results.json``
and rendered as Markdown so they can be copied into the README.

Sections:

1. Category classifier  - accuracy + per-category precision/recall on the
   held-out template split.
2. Duplicate detection  - precision/recall/F1 of embedding similarity at the
   configured geo radius + threshold and at the F1-optimal threshold, over all
   candidate pairs (same ward + same category, within the radius, mirroring the
   runtime filters).
3. Resolution verification - accuracy/precision/recall on unseen synthetic
   before/after image pairs.
4. Hotspot forecast      - 14-day held-out MAE from the trained artifact and a
   recursive 14-step backtest on the tail of every series.
5. Language detection    - accuracy per language on the corpus templates.
6. Translation           - non-empty-rate and sample outputs for Hindi/Kannada.
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

# Windows consoles default to cp1252; translations include Devanagari/Kannada.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import joblib  # noqa: E402
import numpy as np  # noqa: E402

from app.ai.classifier import classifier_path  # noqa: E402
from app.ai.clustering import haversine_km  # noqa: E402
from app.ai.forecast import load_artifact, predict_next_days  # noqa: E402
from app.ai.language import detect_language  # noqa: E402
from app.ai.resolution import FEATURE_NAMES, extract_features, load_comparator  # noqa: E402
from app.ai.translation import translate_to_english  # noqa: E402
from app.core.config import get_settings  # noqa: E402
from app.data.corpus import (  # noqa: E402
    TEMPLATES,
    directory_fingerprint,
    generate_resolution_pairs,
    split_text_samples,
)
from app.db.sync_mongo import get_sync_database  # noqa: E402

RESULTS_PATH = Path("var/eval_results.json")


# --- 1. Classifier ------------------------------------------------------------
def evaluate_classifier() -> dict[str, Any]:
    artifact = joblib.load(classifier_path())
    pipeline = artifact["pipeline"]
    _, holdout = split_text_samples()
    texts = [sample.text for sample in holdout]
    truth = [sample.category.value for sample in holdout]
    predicted = pipeline.predict(texts).tolist()

    labels = sorted(set(truth) | set(predicted))
    per_category: list[dict[str, Any]] = []
    for label in labels:
        tp = sum(1 for t, p in zip(truth, predicted, strict=True) if t == label and p == label)
        fp = sum(1 for t, p in zip(truth, predicted, strict=True) if t != label and p == label)
        fn = sum(1 for t, p in zip(truth, predicted, strict=True) if t == label and p != label)
        support = sum(1 for t in truth if t == label)
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        per_category.append(
            {
                "category": label,
                "precision": round(precision, 4),
                "recall": round(recall, 4),
                "f1": round(f1, 4),
                "support": support,
            }
        )

    accuracy = sum(1 for t, p in zip(truth, predicted, strict=True) if t == p) / len(truth)
    correct = sum(1 for t, p in zip(truth, predicted, strict=True) if t == p)
    return {
        "version": artifact["version"],
        "n_holdout": len(truth),
        "correct": correct,
        "accuracy": round(accuracy, 4),
        "per_category": per_category,
    }


# --- 2. Duplicate detection ---------------------------------------------------
def _load_embedded_complaints() -> list[dict[str, Any]]:
    db = get_sync_database()
    docs = list(
        db["complaints"].find(
            {"embedding": {"$exists": True, "$ne": []}},
            {
                "title": 1,
                "description": 1,
                "category": 1,
                "ward": 1,
                "embedding": 1,
                "location": 1,
                "benchmark.duplicate_group": 1,
            },
        )
    )
    if not docs:
        raise SystemExit("No embedded complaints found. Run scripts/seed_dataset.py first.")
    return docs


def _candidate_scores(
    docs: list[dict[str, Any]], radius_km: float
) -> tuple[np.ndarray, np.ndarray]:
    """Same-ward/same-category pair similarities within ``radius_km``."""
    by_group: dict[tuple[int, str], list[dict[str, Any]]] = defaultdict(list)
    for doc in docs:
        by_group[(int(doc["ward"]), str(doc["category"]))].append(doc)

    scores: list[float] = []
    labels: list[int] = []
    for group_docs in by_group.values():
        if len(group_docs) < 2:
            continue
        matrix = np.asarray([doc["embedding"] for doc in group_docs], dtype=np.float64)
        norms = np.linalg.norm(matrix, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        matrix = matrix / norms
        similarity = matrix @ matrix.T
        for i in range(len(group_docs)):
            lng_i, lat_i = group_docs[i]["location"]["coordinates"]
            for j in range(i + 1, len(group_docs)):
                lng_j, lat_j = group_docs[j]["location"]["coordinates"]
                if haversine_km(lng_i, lat_i, lng_j, lat_j) > radius_km:
                    continue
                left = group_docs[i].get("benchmark", {}).get("duplicate_group")
                right = group_docs[j].get("benchmark", {}).get("duplicate_group")
                scores.append(float(similarity[i, j]))
                labels.append(1 if left and left == right else 0)
    return np.asarray(scores), np.asarray(labels)


def _prf(scores: np.ndarray, labels: np.ndarray, threshold: float) -> dict[str, Any]:
    predicted = scores >= threshold
    tp = int(np.sum(predicted & (labels == 1)))
    fp = int(np.sum(predicted & (labels == 0)))
    fn = int(np.sum(~predicted & (labels == 1)))
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        "threshold": round(float(threshold), 3),
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
        "true_positives": tp,
        "false_positives": fp,
        "false_negatives": fn,
        "predicted_positive": int(predicted.sum()),
    }


def evaluate_duplicates(settings) -> dict[str, Any]:
    docs = _load_embedded_complaints()
    radius = settings.similar_geo_radius_km
    scores, labels = _candidate_scores(docs, radius)
    if len(labels) == 0:
        raise SystemExit("No candidate pairs; seed more complaints.")
    positives = int(labels.sum())

    sweep = [_prf(scores, labels, threshold) for threshold in np.arange(0.30, 0.951, 0.01)]
    best = max(sweep, key=lambda row: (row["f1"], row["threshold"]))
    configured = _prf(scores, labels, settings.similar_min_score)

    return {
        "complaints": len(docs),
        "geo_radius_km": radius,
        "candidate_pairs": len(labels),
        "positive_pairs": positives,
        "base_rate": round(positives / len(labels), 4),
        "configured": configured,
        "chosen": best,
        "curve": [
            row
            for row in sweep
            if row["threshold"] in {round(x / 10, 1) for x in range(3, 10)}
            or row is best
        ],
    }


# --- 3. Resolution verification ----------------------------------------------
def evaluate_resolution(settings) -> dict[str, Any]:
    comparator = load_comparator()
    if comparator is None:
        raise SystemExit("Resolution comparator missing; run scripts/train_models.py first.")
    # Unseen pairs: the training set used seed 21, this uses seed 99.
    pairs = generate_resolution_pairs(count=40, seed=99)
    model = comparator["model"]
    truth: list[int] = []
    probabilities: list[float] = []
    for before, after, label, _pair_id in pairs:
        features = extract_features(before, after)
        row = np.asarray([[features[name] for name in FEATURE_NAMES]], dtype=np.float64)
        probabilities.append(float(model.predict_proba(row)[0, 1]))
        truth.append(label)

    predicted = [1 if p >= settings.resolution_pass_threshold else 0 for p in probabilities]
    tp = sum(1 for t, p in zip(truth, predicted, strict=True) if t == 1 and p == 1)
    tn = sum(1 for t, p in zip(truth, predicted, strict=True) if t == 0 and p == 0)
    fp = sum(1 for t, p in zip(truth, predicted, strict=True) if t == 0 and p == 1)
    fn = sum(1 for t, p in zip(truth, predicted, strict=True) if t == 1 and p == 0)
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    positives = [p for p, t in zip(probabilities, truth, strict=True) if t == 1]
    negatives = [p for p, t in zip(probabilities, truth, strict=True) if t == 0]
    return {
        "version": comparator["version"],
        "pairs": len(pairs),
        "threshold": settings.resolution_pass_threshold,
        "accuracy": round((tp + tn) / len(pairs), 4),
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "confusion": {"tp": tp, "tn": tn, "fp": fp, "fn": fn},
        "mean_confidence_fixed": round(float(np.mean(positives)), 4) if positives else None,
        "mean_confidence_unfixed": round(float(np.mean(negatives)), 4) if negatives else None,
    }


# --- 4. Forecast --------------------------------------------------------------
def _dense_series(days: int = 120) -> tuple[dict[tuple[int, str], dict[date, int]], date]:
    db = get_sync_database()
    docs = list(
        db["complaints"].find({}, {"ward": 1, "category": 1, "created_at": 1})
    )
    if not docs:
        raise SystemExit("No complaints in MongoDB. Run scripts/seed_dataset.py first.")
    latest = max(doc["created_at"] for doc in docs).date()
    start = latest - timedelta(days=days - 1)
    raw: dict[tuple[int, str], dict[date, int]] = defaultdict(dict)
    for doc in docs:
        if doc.get("ward") is None:
            continue
        day = doc["created_at"].date()
        if day < start:
            continue
        key = (int(doc["ward"]), str(doc["category"]))
        raw[key][day] = raw[key].get(day, 0) + 1

    series: dict[tuple[int, str], dict[date, int]] = {}
    for key, counts in raw.items():
        dense = {
            start + timedelta(days=offset): counts.get(start + timedelta(days=offset), 0)
            for offset in range(days)
        }
        series[key] = dense
    return series, latest


def evaluate_forecast(settings) -> dict[str, Any]:
    artifact = load_artifact()
    if artifact is None:
        raise SystemExit("Forecast model missing; run scripts/train_models.py first.")
    series, latest = _dense_series(days=120)
    horizon = settings.forecast_horizon_days
    cutoff = latest - timedelta(days=horizon - 1)

    errors: list[float] = []
    per_series: list[dict[str, Any]] = []
    for (ward, category), counts in sorted(series.items()):
        if len(counts) < settings.forecast_min_history_days + horizon:
            continue
        history = {day: value for day, value in counts.items() if day < cutoff}
        if len(history) < settings.forecast_min_history_days:
            continue
        predictions = predict_next_days(
            artifact,
            ward=ward,
            category=category,
            counts=history,
            start=cutoff,
            horizon=horizon,
        )
        actuals = [counts[day] for day, _ in predictions]
        mae = float(
            np.mean(
                [
                    abs(pred - actual)
                    for (_, pred), actual in zip(predictions, actuals, strict=True)
                ]
            )
        )
        errors.append(mae)
        per_series.append(
            {
                "ward": ward,
                "category": category,
                "mae": round(mae, 3),
                "actual_total": int(sum(actuals)),
                "predicted_total": int(sum(pred for _, pred in predictions)),
            }
        )

    return {
        "version": artifact["version"],
        "trained_at": artifact["trained_at"].isoformat(),
        "artifact_holdout_mae": artifact["holdout_mae"],
        "backtest_series": len(per_series),
        "backtest_mean_mae": round(float(np.mean(errors)), 4) if errors else None,
        "backtest_median_mae": round(float(np.median(errors)), 4) if errors else None,
        "worst_series": sorted(per_series, key=lambda row: row["mae"], reverse=True)[:3],
    }


# --- 5/6. Language and translation -------------------------------------------
def evaluate_language() -> dict[str, Any]:
    per_language: dict[str, dict[str, int]] = defaultdict(lambda: {"correct": 0, "total": 0})
    confusions: list[dict[str, str]] = []
    for _category, by_language in TEMPLATES.items():
        for language, items in by_language.items():
            for title, description in items[:2]:
                detected = detect_language(f"{title} {description}")
                bucket = per_language[language]
                bucket["total"] += 1
                if detected.code == language:
                    bucket["correct"] += 1
                elif len(confusions) < 5:
                    confusions.append(
                        {
                            "true": language,
                            "predicted": detected.code,
                            "text": title,
                        }
                    )
    total = sum(bucket["total"] for bucket in per_language.values())
    correct = sum(bucket["correct"] for bucket in per_language.values())
    return {
        "accuracy": round(correct / total, 4) if total else 0.0,
        "total": total,
        "per_language": {
            language: {
                "accuracy": round(bucket["correct"] / bucket["total"], 4),
                "samples": bucket["total"],
            }
            for language, bucket in sorted(per_language.items())
        },
        "confusions": confusions,
    }


def evaluate_translation() -> dict[str, Any]:
    samples = [
        (TEMPLATES[category]["hi"][0][0], "hi")
        for category in list(TEMPLATES)[:2]
    ] + [
        (TEMPLATES[category]["kn"][0][0], "kn")
        for category in list(TEMPLATES)[:2]
    ]
    translations = translate_to_english(
        [text for text, _ in samples], [code for _, code in samples]
    )
    non_empty = sum(1 for value in translations if value.strip())
    return {
        "samples": len(samples),
        "non_empty": non_empty,
        "non_empty_rate": round(non_empty / len(samples), 4) if samples else 0.0,
        "pairs": [
            {"source": text, "language": code, "english": translated}
            for (text, code), translated in zip(samples, translations, strict=True)
        ],
    }


# --- Rendering ----------------------------------------------------------------
def render_markdown(results: dict[str, Any]) -> str:
    classifier = results["classifier"]
    duplicates = results["duplicates"]
    resolution = results["resolution"]
    forecast = results["forecast"]
    language = results["language"]
    translation = results["translation"]

    lines: list[str] = []
    lines.append(f"Corpus fingerprint: `{results['corpus_fingerprint']}`\n")
    lines.append(
        f"**Category classifier** — holdout accuracy "
        f"**{classifier['accuracy']:.1%}** "
        f"({classifier['correct']}/{classifier['n_holdout']}).\n"
    )
    lines.append("| Category | Precision | Recall | F1 | Support |")
    lines.append("|---|---|---|---|---|")
    for row in classifier["per_category"]:
        lines.append(
            f"| {row['category']} | {row['precision']:.3f} | {row['recall']:.3f} "
            f"| {row['f1']:.3f} | {row['support']} |"
        )
    lines.append("")
    lines.append(
        "**Duplicate detection** "
        f"(same ward + category pairs within {duplicates['geo_radius_km']} km)\n"
    )
    lines.append(
        f"- Candidate pairs: **{duplicates['candidate_pairs']:,}**, "
        f"true duplicates: **{duplicates['positive_pairs']}** "
        f"(base rate {duplicates['base_rate']:.1%})"
    )
    lines.append(
        f"- Configured threshold **{duplicates['configured']['threshold']}**: "
        f"precision **{duplicates['configured']['precision']:.1%}**, "
        f"recall {duplicates['configured']['recall']:.1%}, "
        f"F1 {duplicates['configured']['f1']:.3f}"
    )
    lines.append(
        f"- F1-optimal threshold **{duplicates['chosen']['threshold']}**: "
        f"precision **{duplicates['chosen']['precision']:.1%}**, "
        f"recall {duplicates['chosen']['recall']:.1%}, "
        f"F1 {duplicates['chosen']['f1']:.3f}"
    )
    lines.append("")
    lines.append("**Resolution verification** (unseen synthetic before/after pairs)\n")
    lines.append(
        f"- Accuracy **{resolution['accuracy']:.1%}**, precision "
        f"**{resolution['precision']:.1%}**, recall {resolution['recall']:.1%} "
        f"at threshold {resolution['threshold']}"
    )
    lines.append(
        f"- Mean confidence: fixed {resolution['mean_confidence_fixed']:.3f}, "
        f"unfixed {resolution['mean_confidence_unfixed']:.3f}"
    )
    lines.append("")
    lines.append("**14-day hotspot forecast**\n")
    lines.append(
        f"- Artifact holdout MAE: **{forecast['artifact_holdout_mae']:.3f}** complaints/day"
    )
    lines.append(
        f"- Recursive 14-step backtest over {forecast['backtest_series']} series: "
        f"mean MAE **{forecast['backtest_mean_mae']:.3f}**, "
        f"median {forecast['backtest_median_mae']:.3f}"
    )
    lines.append("")
    lines.append("**Language detection** (corpus templates by native script)\n")
    lines.append(
        f"- Overall accuracy **{language['accuracy']:.1%}** over {language['total']} samples"
    )
    for code, bucket in language["per_language"].items():
        lines.append(f"- {code}: {bucket['accuracy']:.1%} ({bucket['samples']} samples)")
    lines.append("")
    lines.append("**Translation (NLLB-200 distilled 600M, 8-bit ONNX)**\n")
    lines.append(
        f"- Non-empty English translations: {translation['non_empty']}/{translation['samples']} "
        f"({translation['non_empty_rate']:.1%})"
    )
    for pair in translation["pairs"][:2]:
        lines.append(f"- {pair['language']}: {pair['source']} -> *{pair['english']}*")
    return "\n".join(lines)


def main() -> int:
    import logging

    logging.getLogger("civiclens").setLevel(logging.ERROR)
    settings = get_settings()

    print("Evaluating on the seeded labeled corpus (real model outputs only)...\n", flush=True)
    results: dict[str, Any] = {
        "generated_at": datetime.now(UTC).isoformat(),
        "corpus": "seed-v1",
        "corpus_fingerprint": directory_fingerprint(),
        "classifier": evaluate_classifier(),
    }
    print("  [1/6] classifier", flush=True)
    results["duplicates"] = evaluate_duplicates(settings)
    print("  [2/6] duplicate detection", flush=True)
    results["resolution"] = evaluate_resolution(settings)
    print("  [3/6] resolution verification", flush=True)
    results["forecast"] = evaluate_forecast(settings)
    print("  [4/6] forecast", flush=True)
    results["language"] = evaluate_language()
    print("  [5/6] language detection", flush=True)
    results["translation"] = evaluate_translation()
    print("  [6/6] translation", flush=True)

    RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    RESULTS_PATH.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    markdown = render_markdown(results)
    print("\n" + markdown)
    print(f"\nSaved {RESULTS_PATH} (results.json) for the README.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
