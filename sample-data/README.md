# Sample data

**Everything in this folder is fake.** The people, account numbers and local businesses are
invented; well-known chains and subscriptions appear only as merchant names. It is safe to
commit, share and use in screenshots. Real statements belong in `private-data/`, which git
ignores.

Twelve months (October 2025 to September 2026) for one checking account and one credit card,
in CAD:

| File | What it holds |
|---|---|
| `demo-checking.csv` | Checking account: `Date,Description,Amount`, ISO dates, negative = money out |
| `demo-credit-card.csv` | Credit card: `Transaction Date,Posted Date,Description,Debit,Credit`, MM/DD/YYYY dates, purchases as positive numbers under Debit |
| `demo-checking.ofx` | The same checking transactions as OFX 2.x (XML), each with a unique `FITID` |
| `labels.csv` | The correct category for every row of both CSVs: `account,date,description,amount_cents,category` |

In `labels.csv`, `date` is the posted date, `amount_cents` uses Monelyth's sign (negative =
money out, also for card purchases), and `category` is one of the default categories.

The data includes a bi-weekly salary, rent, utilities and a phone bill, groceries, coffee,
dining out, transit and rideshare, subscriptions on fixed days (one with a price increase),
one-off purchases and a refund, and monthly card payments that leave checking and reach the
card one to three days later. A few days have two identical coffees: both are real
purchases, so deduplication must keep them.

## Regenerating

The files are written by [`engine/scripts/generate_sample_data.py`](../engine/scripts/generate_sample_data.py).
A fixed seed drives it, so the same arguments always give byte-identical files. From the
`engine` folder:

```bash
uv run python scripts/generate_sample_data.py
```

`--end-month YYYY-MM` picks the last of the twelve months (default `2026-09`), and
`--output-dir DIR` writes somewhere else. A test checks that the committed files match the
generator, so after changing the generator, run it and commit the new files.
