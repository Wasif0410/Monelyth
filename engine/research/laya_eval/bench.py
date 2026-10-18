"""Measure latency and peak memory of one Laya runtime in a fresh process.

    uv run python bench.py torch
    uv run python bench.py onnx --onnx-path models/laya-int8.onnx

Run one backend per process so the peak-memory figure belongs to that backend alone.
"""

from __future__ import annotations

import argparse
import os
import platform
import statistics
import time
from pathlib import Path
from typing import Any

# Set before huggingface_hub is imported, which reads it once.
os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")

import psutil

from dataset import DEFAULT_LABELS, STATE_FORMATS, load_examples, question
from run_eval import CHECKPOINTS, HEAD_MAX_LEN, model_root


def peak_mb(process: psutil.Process) -> float:
    info: Any = process.memory_info()
    # Windows reports the peak working set; elsewhere fall back to the current RSS.
    return float(getattr(info, "peak_wset", info.rss)) / 2**20


def main() -> None:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n", 1)[0])
    parser.add_argument("backend", choices=("torch", "onnx"))
    parser.add_argument("--checkpoint", choices=list(CHECKPOINTS), default="typed-decisions")
    parser.add_argument("--onnx-path", type=Path)
    parser.add_argument("--state", choices=list(STATE_FORMATS), default="plain")
    parser.add_argument("--criteria", default="names")
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument("--labels", type=Path, default=DEFAULT_LABELS)
    args = parser.parse_args()

    process = psutil.Process()
    examples = load_examples(args.labels)
    states = [STATE_FORMATS[args.state](e) for e in examples]
    q = question(args.criteria)
    baseline_mb = process.memory_info().rss / 2**20

    started = time.perf_counter()
    root = model_root()
    subfolder = CHECKPOINTS[args.checkpoint]
    if args.backend == "torch":
        import laya
        import torch

        agent: Any = laya.load(str(root), device="cpu", subfolder=subfolder)
        runtime = f"torch {torch.__version__}, {torch.get_num_threads()} threads"
    else:
        import onnxruntime
        from laya.onnx_agent import ONNXAgent

        if args.onnx_path is None:
            parser.error("--onnx-path is required for the onnx backend")
        agent = ONNXAgent(str(root), onnx_path=str(args.onnx_path), subfolder=subfolder)
        runtime = f"onnxruntime {onnxruntime.__version__}"
    load_s = time.perf_counter() - started
    loaded_mb = process.memory_info().rss / 2**20

    agent.predict_batch(states[: args.batch_size], q, head_max_len=HEAD_MAX_LEN)  # warm-up
    per_batch: list[float] = []
    started = time.perf_counter()
    for i in range(0, len(states), args.batch_size):
        t = time.perf_counter()
        agent.predict_batch(states[i : i + args.batch_size], q, head_max_len=HEAD_MAX_LEN)
        per_batch.append((time.perf_counter() - t) / len(states[i : i + args.batch_size]))
    total_s = time.perf_counter() - started

    single: list[float] = []
    for state in states[:20]:
        t = time.perf_counter()
        agent.predict_batch([state], q, head_max_len=HEAD_MAX_LEN)
        single.append(time.perf_counter() - t)

    print(f"cpu: {platform.processor()} ({psutil.cpu_count(logical=False)} cores)")
    print(f"runtime: {runtime}; checkpoint {args.checkpoint}; batch {args.batch_size}")
    print(f"load: {load_s:.1f} s; rss baseline {baseline_mb:.0f} MB, after load {loaded_mb:.0f} MB")
    print(
        f"batched: {1000 * total_s / len(states):.1f} ms/txn mean over {len(states)} txns "
        f"(median batch {1000 * statistics.median(per_batch):.1f} ms/txn)"
    )
    print(f"single: {1000 * statistics.median(single):.1f} ms median for one transaction")
    print(f"peak working set: {peak_mb(process):.0f} MB")


if __name__ == "__main__":
    main()
