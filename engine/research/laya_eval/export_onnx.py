"""Export a Laya checkpoint to ONNX, quantize it to int8, and check both against PyTorch.

    uv run python export_onnx.py                      # typed-decisions -> models/
    uv run python export_onnx.py --checkpoint laya

Writes models/<checkpoint>-fp32.onnx and models/<checkpoint>-int8.onnx (git-ignored), prints
their sizes and how far their logits drift from PyTorch on the labeled transactions, and saves
both runs' logits to results/raw/ so `report.py` scores them like the PyTorch variants.
"""

from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path
from typing import Any, Final

# Set before huggingface_hub is imported, which reads it once.
os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")

import laya
import numpy as np
import onnxruntime
import torch
from laya.common import QTYPES, build_sequence
from laya.onnx_agent import ONNXAgent, _collate_items_numpy  # pyright: ignore[reportPrivateUsage]
from onnxruntime.quantization import QuantType, quantize_dynamic

from dataset import CATEGORIES, DEFAULT_LABELS, STATE_FORMATS, load_examples, question
from run_eval import BATCH_SIZE, CHECKPOINTS, HEAD_MAX_LEN, RAW_DIR, model_root

MODELS_DIR: Final = Path(__file__).parent / "models"
INPUTS: Final = ("input_ids", "attention_mask", "marker_pos", "marker_mask", "qtype")
OUTPUTS: Final = ("logits", "act_logits")
OPSET: Final = 17


def encode(agent: Any, states: list[str], criteria: str) -> dict[str, np.ndarray]:
    internal = ONNXAgent._to_internal(question(criteria)["category"])  # pyright: ignore[reportPrivateUsage]
    max_len = int(agent.cfg.get("max_len", 512))
    items = []
    for state in states:
        built = build_sequence(agent.tok, state, internal, max_len, HEAD_MAX_LEN)
        ids, markers = built[0], built[1]
        items.append([{"ids": ids, "markers": markers, "qtype": QTYPES["choice"]}])
    return _collate_items_numpy(items, agent.tok.pad_token_id)


def export(agent: Any, sample: dict[str, np.ndarray], path: Path) -> None:
    model = agent.model.eval().float()
    args = tuple(torch.from_numpy(sample[name]) for name in INPUTS)
    rows_seq = {0: "rows", 1: "sequence"}
    rows_opts = {0: "rows", 1: "options"}
    # The fused TransformerEncoderLayer fast path is a single aten op ONNX has no mapping for.
    torch.backends.mha.set_fastpath_enabled(False)
    with torch.no_grad():
        torch.onnx.export(
            model,
            args,
            str(path),
            input_names=list(INPUTS),
            output_names=list(OUTPUTS),
            dynamic_axes={
                "input_ids": rows_seq,
                "attention_mask": rows_seq,
                "marker_pos": rows_opts,
                "marker_mask": rows_opts,
                "qtype": {0: "rows"},
                "logits": rows_opts,
                "act_logits": {0: "rows"},
            },
            opset_version=OPSET,
            dynamo=False,
        )


def run_onnx(path: Path, batches: list[dict[str, np.ndarray]]) -> tuple[np.ndarray, float]:
    options = onnxruntime.SessionOptions()
    options.graph_optimization_level = onnxruntime.GraphOptimizationLevel.ORT_ENABLE_ALL
    session = onnxruntime.InferenceSession(
        str(path), sess_options=options, providers=["CPUExecutionProvider"]
    )
    started = time.perf_counter()
    out = [np.asarray(session.run(["logits"], batch)[0]) for batch in batches]
    return np.concatenate(out).astype(np.float64), time.perf_counter() - started


def main() -> None:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n", 1)[0])
    parser.add_argument("--checkpoint", choices=list(CHECKPOINTS), default="typed-decisions")
    parser.add_argument("--state", choices=list(STATE_FORMATS), default="plain")
    parser.add_argument("--criteria", default="names")
    parser.add_argument("--labels", type=Path, default=DEFAULT_LABELS)
    args = parser.parse_args()

    examples = load_examples(args.labels)
    labels = np.array([CATEGORIES.index(e.category) for e in examples])
    states = [STATE_FORMATS[args.state](e) for e in examples]
    agent: Any = laya.load(str(model_root()), device="cpu", subfolder=CHECKPOINTS[args.checkpoint])
    batches = [
        encode(agent, states[i : i + BATCH_SIZE], args.criteria)
        for i in range(0, len(states), BATCH_SIZE)
    ]

    with torch.inference_mode():
        reference = np.concatenate(
            [
                agent.model(*(torch.from_numpy(b[name]) for name in INPUTS))[0].float().numpy()
                for b in batches
            ]
        ).astype(np.float64)

    MODELS_DIR.mkdir(exist_ok=True)
    fp32 = MODELS_DIR / f"{args.checkpoint}-fp32.onnx"
    int8 = MODELS_DIR / f"{args.checkpoint}-int8.onnx"
    export(agent, batches[0], fp32)
    # Per-channel weights (one scale per output row) measured a little better than per-tensor
    # here; both change about a third of the answers (RESULTS.md, "Quantization").
    quantize_dynamic(str(fp32), str(int8), weight_type=QuantType.QInt8, per_channel=True)

    shipped_t = float(agent.temperature_by_options.get("choice:11+", agent.temperature[0]))
    for label, path in (("fp32", fp32), ("int8", int8)):
        logits, seconds = run_onnx(path, batches)
        k = len(CATEGORIES)
        drift = float(np.abs(logits[:, :k] - reference[:, :k]).max())
        agree = float((logits[:, :k].argmax(1) == reference[:, :k].argmax(1)).mean())
        accuracy = float((logits[:, :k].argmax(1) == labels).mean())
        size_mb = sum(p.stat().st_size for p in MODELS_DIR.glob(f"{path.name}*")) / 2**20
        print(
            f"{label}: {size_mb:.0f} MB, accuracy {accuracy:.3f}, agrees with torch on "
            f"{100 * agree:.1f}%, max |logit drift| {drift:.3f}, "
            f"{1000 * seconds / len(states):.1f} ms/txn (onnxruntime, batch {BATCH_SIZE})"
        )
        name = f"{args.checkpoint}-onnx-{label}__{args.state}__{args.criteria}"
        np.savez_compressed(
            RAW_DIR / f"{name}.npz",
            logits=logits[:, :k],
            labels=labels,
            meta=json.dumps(
                {
                    "checkpoint": f"{args.checkpoint} (ONNX {label})",
                    "state": args.state,
                    "criteria": args.criteria,
                    "shipped_temperature": shipped_t,
                    "seconds": seconds,
                    "example_state": states[0],
                }
            ),
        )


if __name__ == "__main__":
    main()
