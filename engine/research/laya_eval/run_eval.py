"""Run Laya (PyTorch, CPU) over the labeled transactions and save every variant's raw logits.

    uv run python run_eval.py                       # every checkpoint x state format x criteria
    uv run python run_eval.py --checkpoints typed-decisions --states text --criteria names

Logits land in results/raw/<checkpoint>__<state>__<criteria>.npz; `report.py` turns them into
the numbers in RESULTS.md. The raw files are git-ignored (regenerate them with this script).
"""

from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path
from typing import Any, Final

import numpy as np

# Set before huggingface_hub is imported, which reads it once.
os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")

import laya
import torch
from huggingface_hub import snapshot_download

from dataset import (
    CATEGORIES,
    CRITERIA,
    DEFAULT_LABELS,
    STATE_FORMATS,
    load_examples,
    question,
)

REPO_ID: Final = "convaiinnovations/laya"
REVISION: Final = "7b928d828b7b0e022f929d9bd2e44165aa270148"
"""The Hub snapshot every number in RESULTS.md was measured on."""
CHECKPOINTS: Final = {"laya": None, "typed-decisions": "typed-decisions"}
HEAD_MAX_LEN: Final = 320
"""Room for 20 described options without cutting any (the checkpoints' defaults are 192/256)."""
BATCH_SIZE: Final = 32
RAW_DIR: Final = Path(__file__).parent / "results" / "raw"


def model_root() -> Path:
    patterns = [
        f"{prefix}{name}"
        for prefix in ("", "typed-decisions/")
        for name in ("rl_agent_config.json", "tokenizer/*", "encoder/*", "model.safetensors")
    ]
    return Path(snapshot_download(REPO_ID, revision=REVISION, allow_patterns=patterns))


def run_variant(
    agent: Any, states: list[str], criteria: str
) -> tuple[np.ndarray, list[dict[str, Any]], float]:
    """Return (logits, answers, seconds) with logits captured straight from the model head."""
    captured: list[np.ndarray] = []

    def keep_logits(_module: object, _inputs: object, outputs: tuple[torch.Tensor, ...]) -> None:
        captured.append(outputs[0].detach().float().cpu().numpy())

    handle = agent.model.register_forward_hook(keep_logits)
    try:
        started = time.perf_counter()
        results = agent.predict_batch(
            states, question(criteria), batch_size=BATCH_SIZE, head_max_len=HEAD_MAX_LEN
        )
        seconds = time.perf_counter() - started
    finally:
        handle.remove()
    logits = np.concatenate(captured)[:, : len(CATEGORIES)].astype(np.float64)
    answers = [r["answers"]["category"] for r in results]
    for r in results:
        if r["usage"].get("options") or r["usage"]["truncated"]:
            raise RuntimeError(f"options or state were truncated: {r['usage']}")
    predicted = [CATEGORIES[i] for i in logits.argmax(axis=1)]
    if predicted != [a["choice"] for a in answers]:
        raise RuntimeError("captured logits do not match the agent's answers")
    return logits, answers, seconds


def main() -> None:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n", 1)[0])
    parser.add_argument("--labels", type=Path, default=DEFAULT_LABELS)
    parser.add_argument("--checkpoints", nargs="+", default=list(CHECKPOINTS))
    parser.add_argument("--states", nargs="+", default=list(STATE_FORMATS))
    parser.add_argument("--criteria", nargs="+", default=list(CRITERIA))
    args = parser.parse_args()

    examples = load_examples(args.labels)
    labels = np.array([CATEGORIES.index(e.category) for e in examples])
    root = model_root()
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    print(f"{len(examples)} examples, torch {torch.__version__}, {torch.get_num_threads()} threads")

    for checkpoint in args.checkpoints:
        agent = laya.load(str(root), device="cpu", subfolder=CHECKPOINTS[checkpoint])
        bucket = f"choice:{'11+' if len(CATEGORIES) > 10 else len(CATEGORIES)}"
        shipped_t = float(agent.temperature_by_options.get(bucket, agent.temperature[0]))
        for state_name in args.states:
            states = [STATE_FORMATS[state_name](e) for e in examples]
            for criteria in args.criteria:
                logits, answers, seconds = run_variant(agent, states, criteria)
                reported = np.array([a["answer_confidence"] for a in answers])
                z = logits / shipped_t
                p = np.exp(z - z.max(axis=1, keepdims=True))
                p /= p.sum(axis=1, keepdims=True)
                if np.abs(p.max(axis=1) - reported).max() > 1e-3:
                    raise RuntimeError("shipped temperature does not reproduce the confidence")
                name = f"{checkpoint}__{state_name}__{criteria}"
                np.savez_compressed(
                    RAW_DIR / f"{name}.npz",
                    logits=logits,
                    labels=labels,
                    meta=json.dumps(
                        {
                            "checkpoint": checkpoint,
                            "state": state_name,
                            "criteria": criteria,
                            "shipped_temperature": shipped_t,
                            "seconds": seconds,
                            "example_state": states[0],
                        }
                    ),
                )
                accuracy = float((logits.argmax(axis=1) == labels).mean())
                print(
                    f"{name:42s} accuracy {accuracy:.3f}  "
                    f"{1000 * seconds / len(states):.0f} ms/txn (torch, batch {BATCH_SIZE})"
                )
        del agent


if __name__ == "__main__":
    main()
