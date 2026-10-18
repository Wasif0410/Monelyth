"""Accuracy and calibration metrics over a matrix of per-option logits (NumPy only)."""

from __future__ import annotations

import itertools
import math
from collections import Counter
from collections.abc import Sequence
from typing import Final

import numpy as np
from numpy.typing import NDArray

THRESHOLDS: Final = (0.5, 0.8, 0.9, 0.95)
_TEMPERATURE_GRID: Final = np.exp(np.linspace(math.log(0.05), math.log(20.0), 400))

FloatArray = NDArray[np.float64]
IntArray = NDArray[np.int64]


def softmax(logits: FloatArray, temperature: float = 1.0) -> FloatArray:
    z = logits / temperature
    z = z - z.max(axis=1, keepdims=True)
    e = np.exp(z)
    return e / e.sum(axis=1, keepdims=True)


def nll(logits: FloatArray, labels: IntArray, temperature: float) -> float:
    p = softmax(logits, temperature)
    return float(-np.log(np.clip(p[np.arange(len(labels)), labels], 1e-12, 1.0)).mean())


def fit_temperature(logits: FloatArray, labels: IntArray) -> float:
    """The temperature minimising negative log-likelihood (grid search, log-spaced)."""
    losses = [nll(logits, labels, float(t)) for t in _TEMPERATURE_GRID]
    return float(_TEMPERATURE_GRID[int(np.argmin(losses))])


def cross_validated_confidence(
    logits: FloatArray, labels: IntArray, groups: Sequence[str], folds: int = 5
) -> tuple[FloatArray, list[float]]:
    """Max-probability confidence after temperature scaling fitted out of fold.

    Folds are split by group (the cleaned merchant), so no merchant's own rows ever tune the
    temperature that scores it. Returns the confidences and each fold's temperature.
    """
    unique = sorted(set(groups))
    rng = np.random.default_rng(0)
    order = rng.permutation(len(unique))
    fold_of = {unique[i]: rank % folds for rank, i in enumerate(order)}
    fold_ids = np.array([fold_of[g] for g in groups])
    confidence = np.zeros(len(labels))
    temperatures: list[float] = []
    for fold in range(folds):
        test = fold_ids == fold
        if not test.any():
            continue
        t = fit_temperature(logits[~test], labels[~test])
        temperatures.append(t)
        confidence[test] = softmax(logits[test], t).max(axis=1)
    return confidence, temperatures


def wilson(successes: int, total: int, z: float = 1.96) -> tuple[float, float]:
    """95% Wilson score interval for a proportion."""
    if total == 0:
        return (0.0, 0.0)
    p = successes / total
    denom = 1 + z * z / total
    centre = (p + z * z / (2 * total)) / denom
    half = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / denom
    return (max(0.0, centre - half), min(1.0, centre + half))


def ece(confidence: FloatArray, correct: NDArray[np.bool_], bins: int = 10) -> float:
    """Expected calibration error with equal-width bins."""
    edges = np.linspace(0.0, 1.0, bins + 1)
    total = 0.0
    for i in range(bins):
        lo, hi = edges[i], edges[i + 1]
        sel = (confidence >= lo if i == 0 else confidence > lo) & (confidence <= hi)
        if sel.any():
            total += sel.mean() * abs(confidence[sel].mean() - correct[sel].mean())
    return float(total)


def selective(confidence: FloatArray, correct: NDArray[np.bool_]) -> dict[str, dict[str, float]]:
    """Coverage and accuracy of the answers at or above each threshold."""
    out: dict[str, dict[str, float]] = {}
    for threshold in THRESHOLDS:
        sel = confidence >= threshold
        n = int(sel.sum())
        right = int(correct[sel].sum())
        lo, hi = wilson(right, n)
        out[f"{threshold:.2f}"] = {
            "coverage": n / len(confidence),
            "answered": n,
            "accuracy": right / n if n else float("nan"),
            "accuracy_ci_low": lo,
            "accuracy_ci_high": hi,
            "wrong": n - right,
        }
    return out


def reliability(
    confidence: FloatArray, correct: NDArray[np.bool_], edges: Sequence[float]
) -> list[dict[str, float]]:
    rows: list[dict[str, float]] = []
    for lo, hi in itertools.pairwise(edges):
        sel = (confidence >= lo) & (confidence < hi if hi < 1.0 else confidence <= hi)
        n = int(sel.sum())
        rows.append(
            {
                "low": lo,
                "high": hi,
                "count": n,
                "mean_confidence": float(confidence[sel].mean()) if n else float("nan"),
                "accuracy": float(correct[sel].mean()) if n else float("nan"),
            }
        )
    return rows


def per_category_recall(
    predicted: Sequence[str], actual: Sequence[str], categories: Sequence[str]
) -> dict[str, dict[str, float]]:
    out: dict[str, dict[str, float]] = {}
    for category in categories:
        idx = [i for i, a in enumerate(actual) if a == category]
        if not idx:
            continue
        right = sum(predicted[i] == category for i in idx)
        out[category] = {"support": len(idx), "recall": right / len(idx)}
    return out


def top_confusions(
    predicted: Sequence[str], actual: Sequence[str], limit: int = 8
) -> list[tuple[str, str, int]]:
    pairs = Counter((a, p) for p, a in zip(predicted, actual, strict=True) if p != a)
    return [(a, p, n) for (a, p), n in pairs.most_common(limit)]


def summarize(
    logits: FloatArray,
    labels: IntArray,
    categories: Sequence[str],
    groups: Sequence[str],
    shipped_temperature: float,
) -> dict[str, object]:
    """Everything RESULTS.md reports for one variant on one set of rows."""
    predicted_idx = logits.argmax(axis=1)
    correct = predicted_idx == labels
    predicted = [categories[int(i)] for i in predicted_idx]
    actual = [categories[int(i)] for i in labels]
    shipped = softmax(logits, shipped_temperature).max(axis=1)
    calibrated, temperatures = cross_validated_confidence(logits, labels, groups)
    n = len(labels)
    right = int(correct.sum())
    lo, hi = wilson(right, n)
    edges = (0.0, 0.5, 0.8, 0.9, 0.95, 1.0)
    return {
        "rows": n,
        "accuracy": right / n,
        "accuracy_ci": [lo, hi],
        "per_category_recall": per_category_recall(predicted, actual, categories),
        "top_confusions": top_confusions(predicted, actual),
        "shipped_temperature": shipped_temperature,
        "shipped": {
            "ece": ece(shipped, correct),
            "selective": selective(shipped, correct),
            "reliability": reliability(shipped, correct, edges),
        },
        "recalibrated": {
            "fold_temperatures": temperatures,
            "ece": ece(calibrated, correct),
            "selective": selective(calibrated, correct),
            "reliability": reliability(calibrated, correct, edges),
        },
    }
