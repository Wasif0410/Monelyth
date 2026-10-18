# Laya on bank transactions: evaluation results

PLAN.md step 3.4 asks whether the Laya classifier earns a place as tier 3 of the categorization
pipeline (memory → rules → **classifier** → LLM → review). This folder holds the measurement;
nothing here is a runtime dependency of the engine.

## Decision: path (c), don't ship Laya

**Laya doesn't earn the tier.** The tier only needs to be right when it is confident, since
anything below `REVIEW_THRESHOLD` (0.80) goes to the LLM and the review queue. Laya fails exactly
that test:

- **Best accuracy: 52.8% of merchants** (95% CI 39.7–65.6%). That is the best of 16 prompt
  variants across two checkpoints, picked on the same data. A list of generic keywords
  ("coffee", "pharmacy", "payment") scores 58.5%.
- **Its confident answers are not safe.** At confidence ≥ 0.80 as the library reports it, the best
  variant answers 45% of merchants and **one in three of those answers is wrong** (66.7% correct).
  At ≥ 0.95 it is still only 64.3% correct.
- **Recalibrating doesn't help.** Temperature scaling, fitted out of fold on held-out merchants,
  makes the scores honest by shrinking them. Then only 19% of merchants reach 0.80, at 70%
  accuracy, and none reach 0.90. No threshold gives both safe answers and useful coverage.
- **It is heavy.** 421M parameters: 1.6 GB as ONNX fp32 and 423 MB as int8. Int8 also drops
  per-merchant accuracy from 52.8% to 41.5%. On this CPU it takes 56–205 ms per transaction and
  peaks at 1.2–2.8 GB of RAM. That is a lot to ship for a tier that only sees merchants memory
  and rules couldn't answer.

**Recommendation:** build the fallback PLAN 3.4(c) already names: a small sentence-embedding
model (e.g. `bge-small-en-v1.5`, about 33M parameters) that categorizes by nearest neighbours
among already-labeled transactions. See [Recommendation](#recommendation) for why this beats
fine-tuning Laya (path b) and how to evaluate it with this harness.

No `classifier.py`, runtime dependency or ONNX model was added to the engine.

## What was measured

| | |
|---|---|
| Model | [`convaiinnovations/laya`](https://huggingface.co/convaiinnovations/laya), Apache-2.0, Hub snapshot `7b928d828b7b0e022f929d9bd2e44165aa270148` |
| Checkpoints | `laya` (repo root: English, ModernBERT-large, 421M params, 842 MB fp16 safetensors) and `typed-decisions` (the same backbone fine-tuned on typed decisions, which the model card reports at 0.766 against the root's 0.362 on its benchmark) |
| How it is asked | One `choice` question, *"Which budget category does this bank transaction belong to?"*, with the 20 seeded default categories as options. Laya is zero-shot: the option list is part of the input, and there are no fixed labels |
| Labeled data | `sample-data/labels.csv`: **639 rows, 53 distinct cleaned merchants**, 20 categories |
| Hardware | AMD Ryzen 5 9600X (6 cores / 12 threads), 31 GB RAM, Windows 11, CPU only |

**Two scopes are reported.** *Rows* counts every transaction. *Merchants* counts the first
transaction of each cleaned merchant (`normalize_merchant`) once. The merchant scope is the one
that matters. The classifier tier only sees merchants that memory and rules couldn't answer, so
it judges unfamiliar merchants one at a time. In the rows scope, Tim Hortons counts 37 times.

### State formats

Each state is built from the cleaned merchant, the raw description, the amount and its sign.
Shown here for one row:

| Format | State |
|---|---|
| `text` | `Merchant: Greenleaf Organic Market. Bank description: POS PURCHASE GREENLEAF ORGANIC MARKET. Amount: 17.13 CAD (money out).` |
| `json` | `{"merchant": "Greenleaf Organic Market", "bank_description": "POS PURCHASE GREENLEAF ORGANIC MARKET", "amount": "17.13 CAD", "direction": "money out"}` |
| `sentence` | `I paid 17.13 CAD - Greenleaf Organic Market (POS PURCHASE GREENLEAF ORGANIC MARKET)` |
| `plain` | `Spent 17.13 CAD at Greenleaf Organic Market.` (or `Received ... from ...` for money in) |
| `merchant` | `Greenleaf Organic Market` |

### Criteria wordings

- `names`: the category names alone (`{"Coffee": null, ...}`).
- `described`: each name with a short description (`"Coffee": "coffee shop, cafe"`,
  `"Transfers": "card payment or transfer between own accounts"`, ...; see `dataset.py`).

`head_max_len` was raised to 320, so all 20 described options fit without being cut (the
checkpoints default to 192 and 256). The harness fails if any option or state is truncated.

## Results

### Baselines

| Baseline | Accuracy (rows) | Accuracy (merchants) | Answers (merchants) | Right when it answers |
|---|---|---|---|---|
| Majority class (Coffee) | 32.9% | 9.4% | 100% | 9.4% |
| **Keywords, generic** (47 words naming a kind of business; else majority) | 67.8% | **58.5%** | 54.7% | 96.6% |
| Keywords, with brand names (adds 27 brands seen in the data) | 100.0% | 100.0% | 98.1% | 100.0% |

The brand-name table shows how far plain rules (PLAN 3.3) can go on this data: all the way.
The sample data draws from a small fixed merchant pool, so in practice memory and rules would
leave the classifier almost nothing here. The generic table is the fair baseline for unfamiliar
merchants.

### Every variant

Merchant scope, except the "Acc. rows" column. "Shipped" confidence is the probability the
library reports (`answer_confidence`). "Recalibrated" uses a temperature fitted by 5-fold
cross-validation split by merchant, so no merchant tunes its own score.

| Checkpoint | State | Criteria | Acc. rows | Acc. merchants (95% CI) | Shipped ≥0.8: coverage / accuracy | Recal. ≥0.8: coverage / accuracy | ECE shipped / recal. |
|---|---|---|---|---|---|---|---|
| laya | text | names | 26.1% | 24.5% (14.9–37.6%) | 66.0% / 28.6% | 1.9% / 0.0% | 0.609 / 0.130 |
| laya | text | described | 26.1% | 20.8% (12.0–33.5%) | 58.5% / 22.6% | 1.9% / 0.0% | 0.574 / 0.083 |
| laya | json | names | 29.0% | 22.6% (13.5–35.5%) | 90.6% / 18.8% | 0.0% / n/a | 0.742 / 0.148 |
| laya | json | described | 29.7% | 22.6% (13.5–35.5%) | 71.7% / 18.4% | 0.0% / n/a | 0.637 / 0.154 |
| laya | sentence | names | 48.7% | 47.2% (34.4–60.3%) | 69.8% / 56.8% | 15.1% / 50.0% | 0.384 / 0.175 |
| laya | sentence | described | 41.5% | 43.4% (31.0–56.7%) | 54.7% / 62.1% | 5.7% / 66.7% | 0.322 / 0.136 |
| laya | plain | names | 52.4% | 50.9% (37.9–63.9%) | 71.7% / 63.2% | 24.5% / 76.9% | 0.346 / 0.174 |
| laya | merchant | names | 21.3% | 26.4% (16.4–39.6%) | 13.2% / 57.1% | 3.8% / 100.0% | 0.186 / 0.137 |
| typed-decisions | text | names | 31.5% | 30.2% (19.5–43.5%) | 18.9% / 40.0% | 0.0% / n/a | 0.302 / 0.120 |
| typed-decisions | text | described | 31.3% | 26.4% (16.4–39.6%) | 9.4% / 60.0% | 0.0% / n/a | 0.310 / 0.052 |
| typed-decisions | json | names | 30.7% | 24.5% (14.9–37.6%) | 28.3% / 26.7% | 0.0% / n/a | 0.442 / 0.075 |
| typed-decisions | json | described | 36.3% | 26.4% (16.4–39.6%) | 28.3% / 46.7% | 0.0% / n/a | 0.403 / 0.101 |
| typed-decisions | sentence | names | 46.9% | 41.5% (29.3–54.9%) | 47.2% / 68.0% | 1.9% / 0.0% | 0.286 / 0.182 |
| typed-decisions | sentence | described | 43.5% | 39.6% (27.6–53.1%) | 28.3% / 73.3% | 1.9% / 0.0% | 0.236 / 0.134 |
| **typed-decisions** | **plain** | **names** | **53.1%** | **52.8% (39.7–65.6%)** | **45.3% / 66.7%** | **18.9% / 70.0%** | 0.258 / 0.142 |
| typed-decisions | merchant | names | 25.0% | 20.8% (12.0–33.5%) | 1.9% / 100.0% | 0.0% / n/a | 0.155 / 0.096 |
| typed-decisions, ONNX int8 | plain | names | 51.8% | 41.5% (29.3–54.9%) | 39.6% / 61.9% | 5.7% / 100.0% | 0.257 / 0.177 |

What stands out:

- **The wording of the state matters more than the checkpoint.** The same transaction scores
  21–53% depending on phrasing. Natural sentences (`plain`, `sentence`) work. Field lists and
  JSON fall to the level of the bare merchant name, even though they hold more information.
- **The typed-decisions fine-tune barely helps** (+1.9 points per merchant on the best format).
  It is better behaved, though: the root checkpoint reports ≥ 0.8 on 91% of merchants in the
  `json` format while being right 19% of the time.
- **Describing the categories didn't help** in any format, and costs 2–3× the latency (longer
  head).
- The `plain` format was chosen after seeing the other results, on the same 53 merchants. So
  the best row is optimistic for Laya, which makes the negative conclusion safer, not weaker.

### Best variant in detail (typed-decisions, plain, names)

**Is it right when confident?**

| Confidence ≥ | Merchants: coverage | accuracy | wrong | Rows: coverage | accuracy | wrong |
|---|---|---|---|---|---|---|
| *shipped* 0.50 | 73.6% | 61.5% | 15 | 78.7% | 60.0% | 201 |
| *shipped* **0.80** | 45.3% | **66.7%** | 8 | 55.2% | **70.8%** | 103 |
| *shipped* 0.90 | 37.7% | 65.0% | 7 | 37.9% | 80.6% | 47 |
| *shipped* 0.95 | 26.4% | 64.3% | 5 | 27.2% | 78.2% | 38 |
| *recalibrated* 0.50 | 47.2% | 68.0% | 8 | 56.5% | 70.6% | 106 |
| *recalibrated* **0.80** | 18.9% | **70.0%** | 3 | 26.1% | **77.2%** | 38 |
| *recalibrated* 0.90 | 0.0% | n/a | 0 | 3.6% | 100.0% | 0 |
| *recalibrated* 0.95 | 0.0% | n/a | 0 | 0.0% | n/a | 0 |

**Reliability (shipped confidence, merchants):** confidence and accuracy barely move together.
The most confident bucket is no more accurate than the 0.8–0.9 one.

| Confidence | Merchants | Mean confidence | Accuracy |
|---|---|---|---|
| 0.00–0.50 | 14 | 34.8% | 28.6% |
| 0.50–0.80 | 15 | 61.0% | 53.3% |
| 0.80–0.90 | 4 | 87.5% | 75.0% |
| 0.90–0.95 | 6 | 92.3% | 66.7% |
| 0.95–1.00 | 14 | 98.0% | 64.3% |

**Why the shipped confidence is inflated.** For questions with 11 or more options, the checkpoint
config ships the temperature `choice:11+ = 0.1006`, a 10× sharpener. laya 0.4.11 clamps it to
0.5, which still doubles the logits. The temperatures fitted on this data range from 0.67 to
2.59 depending on the checkpoint and prompt (0.71–0.91 for this variant), and every one is
above 0.5. A reported 0.95 is not 95%.

**Per-category recall (rows).** Perfect on categories whose name appears in the merchant
("Payroll" → Salary, "Property Mgmt" → Rent, "Uber Trip" → Rideshare, "Monthly Account Fee" →
Fees). It fails where the category takes world knowledge or a bank convention:

| Category | Support | Recall | | Category | Support | Recall |
|---|---|---|---|---|---|---|
| Salary | 26 | 100% | | Shopping | 17 | 70.6% |
| Other Income | 2 | 50.0% | | Subscriptions | 36 | **0%** |
| Rent/Mortgage | 12 | 100% | | Entertainment | 6 | 100% |
| Utilities | 48 | 20.8% | | Health | 9 | 22.2% |
| Groceries | 94 | 46.8% | | Education | 2 | 100% |
| Dining Out | 62 | 80.6% | | Travel | 3 | 33.3% |
| Coffee | 210 | 59.0% | | Fees & Interest | 13 | 100% |
| Transport | 32 | **0%** | | Gifts & Donations | 3 | 0% |
| Gas | 6 | 100% | | Transfers | 22 | **0%** |
| Rideshare | 30 | 100% | | Other | 6 | 0% |

Most common confusions (rows, actual → predicted): Coffee → Dining Out 47, Coffee → Other 38,
Subscriptions → Entertainment 36 (Netflix, Spotify, Apple), Transport → Other 32 (Presto,
Green P), Groceries → Other 30, Groceries → Shopping 20, Utilities → Gas 14 (Lakeport Gas,
the utility), Utilities → Coffee 12.

### Speed, memory and size

typed-decisions checkpoint, `plain` / `names`, all 639 transactions. Each runtime was measured in
its own fresh process (`bench.py`). "Batched" means batches of 32, after one warm-up batch.

| Runtime | File size | Batched (ms / transaction) | One transaction (ms) | Load (s) | RSS after load | Peak working set | Accuracy (merchants) |
|---|---|---|---|---|---|---|---|
| PyTorch 2.14.1 fp32, 6 threads | 842 MB (fp16 safetensors) | 204.8 | 227.1 | 7.3 | 1,959 MB | 2,762 MB | 52.8% |
| ONNX Runtime 1.31.0, fp32 | 1,608 MB | 94.0 | 101.4 | 6.4 | 1,964 MB | 2,350 MB | 52.8% |
| ONNX Runtime 1.31.0, int8 (dynamic, per-channel) | 423 MB | 56.7 | 44.1 | 5.6 | 785 MB | 1,179 MB | 41.5% |

The memory figures include the Python interpreter and the `transformers` tokenizer stack that
laya's `ONNXAgent` imports (about 215 MB before the model loads).

**Quantization.** `export_onnx.py` exports the model with the TorchScript exporter (opset 17),
then applies ONNX Runtime dynamic int8 quantization. The fp32 export matches PyTorch exactly
(max logit difference 0.000, same answer on 100% of rows). Int8 does not:

| Int8 scheme | Size | Same answer as fp32 | Max logit drift | Accuracy rows / merchants |
|---|---|---|---|---|
| Per-tensor weights | 421 MB | 63.7% | 4.57 | 49.6% / not kept |
| Per-channel weights (kept) | 423 MB | 65.4% | 4.63 | 51.8% / 41.5% |

PLAN 3.4 expected int8 to cost "little accuracy". Here it changes a third of the answers. A
calibrated static quantization, or keeping the attention projections in fp32, might do better.
It is not worth pursuing for a model that isn't shipping.

## Recommendation

**Why not (a), ship as is:** see the decision above. The tier would put a wrong category on one
in three of the transactions it claims, and no threshold fixes that.

**Why not (b), fine-tune Laya:** fine-tuning would very likely fix the accuracy, since a 421M
encoder trained on labeled merchants is a strong classifier. But it doesn't fix the rest:

1. The size stays 1.6 GB, or 423 MB int8 with the accuracy loss measured above, at 56–100 ms
   per transaction. That is a heavy first-run download for a tier that, after the first month,
   sees almost nothing (PLAN: memory answers most transactions).
2. There is nothing to train on yet. The sample data has 53 synthetic merchants from a fixed
   pool. Training on it would teach the generator, not banking. Real labels (PLAN 3.1,
   `private-data/labels.csv`) are personal and few.
3. A fine-tuned model is frozen. Every user correction would need retraining to take effect.
4. The 20-option choice question shares one head-token budget (`head_max_len`). Categories
   users add later make it worse, and the shipped calibration for 11+ options is already
   broken.

**Why (c), embedding nearest neighbours:** a ~33M-parameter sentence-embedding model
(`bge-small-en-v1.5`: about 130 MB fp32, about 35 MB int8) embeds the cleaned merchant and
description, then votes among the k most similar already-categorized transactions.

- It learns from every correction instantly.
- Its confidence is a neighbour vote, which can be checked against held-out data directly.
- It runs in a few ms per transaction.
- Cold start: seed the neighbour set with labeled example merchants (the sample data and the
  default-rule merchants), so a new user isn't starting from nothing.

**Evaluating (c) next:** reuse this harness. Load `sample-data/labels.csv` (and the private
labels, kept local) and embed each transaction. Then run leave-one-merchant-out: score each
merchant only against neighbours from other merchants, which is exactly the classifier tier's
situation. Report the same metrics with `metrics.summarize`, merchant scope first. The bar
Laya missed: about 95% accuracy on the answers at or above the review threshold, with
meaningful coverage.

## Reproducing

From `engine/research/laya_eval/` (needs about 2 GB disk for the two checkpoints, plus 2 GB for
the ONNX exports). The environment is isolated from the engine: CPU-only PyTorch, laya and
ONNX Runtime live only in this folder's `.venv`.

```bash
uv sync                                   # isolated env; PyTorch from the CPU-only index
uv run python run_eval.py                 # 12 variants (3 formats x 2 criteria x 2 checkpoints), ~40 min
uv run python run_eval.py --states plain merchant --criteria names
uv run python export_onnx.py              # fp32 + int8 ONNX into models/, scores both
uv run python report.py > results/report.md   # tables + results/results.json
uv run python bench.py torch
uv run python bench.py onnx --onnx-path models/typed-decisions-fp32.onnx
uv run python bench.py onnx --onnx-path models/typed-decisions-int8.onnx
```

`run_eval.py` downloads the pinned snapshot on first run (set `HF_HUB_OFFLINE=1` afterwards). It
captures the logits straight from the model head, checks that they reproduce the library's own
answers and confidences, and saves them to `results/raw/` (git-ignored). `report.py` recomputes
every metric from those files. Committed outputs: `results/report.md` and
`results/results.json`.

Settings: batch size 32, `head_max_len` 320, `max_len` from each checkpoint (512 for laya,
1024 for typed-decisions), fp32 on CPU with PyTorch's default 6 threads. Recalibration uses
5-fold cross-validation split by merchant (seed 0), with temperatures grid-searched on NLL.
Calibration error uses 10 equal-width bins. Confidence intervals are 95% Wilson intervals.

| Package | Version |
|---|---|
| Python | 3.12.13 |
| laya | 0.4.11 |
| torch | 2.14.1+cpu |
| transformers | 5.20.1 |
| tokenizers | 0.23.3 |
| onnx | 1.23.2 |
| onnxruntime | 1.31.0 |
| onnxscript | 0.7.2 |
| numpy | 1.26.4 |
| huggingface-hub | 2.2.0 |

## Limits of this evaluation

- **Small and synthetic.** 53 merchants give wide confidence intervals (±13 points). The sample
  generator's merchant pool is not a real bank statement. Rerun with real labels (PLAN 3.1)
  before drawing fine-grained conclusions. The direction of this one is not close: the best of
  16 tries is below a keyword list and wrong one time in three when confident.
- **Prompt search was modest.** Five state formats, two criteria wordings and one instruction.
  A better phrasing may exist. But the spread across formats (21–53%) is itself a reason not to
  trust the model in production, where descriptions vary far more than here.
- **Laya's own shortlist/tournament helpers** for many-option questions (`laya.shortlist`) were
  not tried. They need an embedding model, which is path (c) anyway.
