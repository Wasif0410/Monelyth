"""Turn the logits saved by `run_eval.py` into the metrics and tables used in RESULTS.md.

uv run python report.py            # writes results/results.json and prints Markdown tables
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any, Final

import numpy as np

from dataset import (
    CATEGORIES,
    DEFAULT_LABELS,
    KEYWORD_TABLES,
    Example,
    first_per_merchant,
    keyword_category,
    load_examples,
    majority_class,
)
from metrics import summarize

RESULTS_DIR: Final = Path(__file__).parent / "results"
RAW_DIR: Final = RESULTS_DIR / "raw"


def _pct(value: float) -> str:
    return "n/a" if math.isnan(value) else f"{100 * value:.1f}%"


def baselines(examples: list[Example], subset: list[int]) -> dict[str, Any]:
    majority = majority_class(examples)
    out: dict[str, Any] = {"majority_class": majority}
    for scope, idx in (("all_rows", list(range(len(examples)))), ("per_merchant", subset)):
        rows = [examples[i] for i in idx]
        part: dict[str, Any] = {
            "majority_accuracy": sum(e.category == majority for e in rows) / len(rows)
        }
        for name, table in KEYWORD_TABLES.items():
            guesses = [keyword_category(e, table) for e in rows]
            fired = [(g, e.category) for g, e in zip(guesses, rows, strict=True) if g is not None]
            part[name] = {
                "accuracy": sum(
                    (g or majority) == e.category for g, e in zip(guesses, rows, strict=True)
                )
                / len(rows),
                "coverage": len(fired) / len(rows),
                "precision": sum(g == c for g, c in fired) / len(fired) if fired else 0.0,
            }
        out[scope] = part
    return out


def _json_safe(value: Any) -> Any:
    """NaN (an empty bucket's accuracy) as null, so results.json is strict JSON."""
    if isinstance(value, float) and math.isnan(value):
        return None
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}  # pyright: ignore[reportUnknownVariableType]
    if isinstance(value, list | tuple):
        return [_json_safe(v) for v in value]  # pyright: ignore[reportUnknownVariableType]
    return value


def main() -> None:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n", 1)[0])
    parser.add_argument("--labels", type=Path, default=DEFAULT_LABELS)
    args = parser.parse_args()

    examples = load_examples(args.labels)
    subset = first_per_merchant(examples)
    merchants = [e.merchant for e in examples]
    report: dict[str, Any] = {
        "examples": len(examples),
        "merchants": len(subset),
        "baselines": baselines(examples, subset),
        "variants": {},
    }
    for path in sorted(RAW_DIR.glob("*.npz")):
        data = np.load(path)
        meta = json.loads(str(data["meta"]))
        logits = data["logits"].astype(np.float64)
        labels = data["labels"].astype(np.int64)
        t = float(meta["shipped_temperature"])
        report["variants"][path.stem] = {
            "meta": meta,
            "ms_per_transaction": 1000 * meta["seconds"] / len(labels),
            "all_rows": summarize(logits, labels, CATEGORIES, merchants, t),
            "per_merchant": summarize(
                logits[subset], labels[subset], CATEGORIES, [merchants[i] for i in subset], t
            ),
        }
    (RESULTS_DIR / "results.json").write_text(
        json.dumps(_json_safe(report), indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )
    print_markdown(report)


def print_markdown(report: dict[str, Any]) -> None:
    b = report["baselines"]
    rows, per = b["all_rows"], b["per_merchant"]
    print(f"\n{report['examples']} rows, {report['merchants']} distinct merchants\n")
    print(
        "| Baseline | Accuracy (rows) | Accuracy (merchants) | Fires on (merchants) "
        "| Right when it fires |"
    )
    print("|---|---|---|---|---|")
    print(
        f"| Majority class ({b['majority_class']}) | {_pct(rows['majority_accuracy'])} "
        f"| {_pct(per['majority_accuracy'])} | 100% | {_pct(per['majority_accuracy'])} |"
    )
    for name in KEYWORD_TABLES:
        print(
            f"| Keywords: {name} (else majority) | {_pct(rows[name]['accuracy'])} "
            f"| {_pct(per[name]['accuracy'])} | {_pct(per[name]['coverage'])} "
            f"| {_pct(per[name]['precision'])} |"
        )
    print()

    print(
        "| Variant | Acc. rows | Acc. merchants (95% CI) | Shipped conf>=0.8: cov / acc "
        "| Recalibrated conf>=0.8: cov / acc | ECE shipped / recal. |"
    )
    print("|---|---|---|---|---|---|")
    for name, v in report["variants"].items():
        rows, per = v["all_rows"], v["per_merchant"]
        lo, hi = per["accuracy_ci"]
        s, r = per["shipped"]["selective"]["0.80"], per["recalibrated"]["selective"]["0.80"]
        print(
            f"| {name} | {_pct(rows['accuracy'])} | {_pct(per['accuracy'])} "
            f"({_pct(lo)}-{_pct(hi)}) | {_pct(s['coverage'])} / {_pct(s['accuracy'])} "
            f"| {_pct(r['coverage'])} / {_pct(r['accuracy'])} "
            f"| {per['shipped']['ece']:.3f} / {per['recalibrated']['ece']:.3f} |"
        )

    # Ties go to the PyTorch run: the ONNX fp32 export scores identically by construction.
    best_name = max(
        report["variants"],
        key=lambda n: (report["variants"][n]["per_merchant"]["accuracy"], "onnx" not in n),
    )
    best = report["variants"][best_name]
    print(f"\nBest variant by merchant accuracy: {best_name}\n")
    for scope in ("per_merchant", "all_rows"):
        part = best[scope]
        print(f"\n#### {scope}: selective accuracy\n")
        print(
            "| Threshold | Shipped: coverage | accuracy | wrong "
            "| Recal.: coverage | accuracy | wrong |"
        )
        print("|---|---|---|---|---|---|---|")
        for th, s in part["shipped"]["selective"].items():
            r = part["recalibrated"]["selective"][th]
            print(
                f"| >= {th} | {_pct(s['coverage'])} | {_pct(s['accuracy'])} | {s['wrong']} "
                f"| {_pct(r['coverage'])} | {_pct(r['accuracy'])} | {r['wrong']} |"
            )
        print(f"\nRecalibration fold temperatures: {part['recalibrated']['fold_temperatures']}")
        print(f"\n#### {scope}: reliability (shipped)\n")
        print("| Confidence | Count | Mean confidence | Accuracy |")
        print("|---|---|---|---|")
        for row in part["shipped"]["reliability"]:
            print(
                f"| {row['low']:.2f}-{row['high']:.2f} | {row['count']} "
                f"| {_pct(row['mean_confidence'])} | {_pct(row['accuracy'])} |"
            )
    print("\n#### Per-category recall (all rows)\n")
    print("| Category | Support | Recall |")
    print("|---|---|---|")
    for category, value in best["all_rows"]["per_category_recall"].items():
        print(f"| {category} | {value['support']} | {_pct(value['recall'])} |")
    print("\n#### Most common confusions (all rows): actual -> predicted\n")
    for actual, predicted, n in best["all_rows"]["top_confusions"]:
        print(f"- {actual} -> {predicted}: {n}")


if __name__ == "__main__":
    main()
