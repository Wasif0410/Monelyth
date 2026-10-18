# Monelyth Engine

The local Python service behind the Monelyth desktop app. The desktop shell starts it as a
sidecar process; it listens on `127.0.0.1` only and rejects any request without the per-launch
token. See [`../PLAN.md`](../PLAN.md) for the architecture.

## Development

```bash
uv sync                      # create .venv with runtime + dev dependencies
uv run pytest                # tests (network access outside 127.0.0.1 is blocked)
uv run ruff check .          # lint
uv run ruff format .         # format
uv run pyright               # strict type checking
```

Run the engine on its own:

```bash
MONELYTH_TOKEN=$(python -c "import secrets; print(secrets.token_hex(32))") \
  uv run monelyth-engine --data-dir ./.dev-data --port 8765
```

It prints `MONELYTH_READY {"port": 8765, "version": "..."}` once it is listening. Requests need
`Authorization: Bearer <token>`.

## HTTP API

Every route needs `Authorization: Bearer <token>`. Errors the user should see come back as
`{"detail": "<message>"}`.

| Route | Purpose |
|---|---|
| `GET /health` | Liveness and version |
| `GET /accounts`, `POST /accounts` | List and add accounts. Each comes with its transaction count, latest transaction date and `net_amount_cents` (the sum of its imported transactions, not a bank balance) |
| `PATCH /accounts/{id}` | Rename an account or change its institution |
| `DELETE /accounts/{id}` | Delete an account with all of its imports and transactions, in one step |
| `GET /categories` | Default and user categories |
| `POST /imports/preview` | Upload a statement (multipart `file`); returns the detected format, CSV layout, open questions and supported date formats, and the first rows. With an optional `layout` (JSON, as for `POST /imports`) every row is read with it, or `422` names the row that does not fit. Saves nothing |
| `POST /imports` | Upload it again with `account_id` (and the confirmed CSV `layout` as JSON) to store it. `409` if the exact file was imported before; overlapping rows are skipped |
| `GET /transactions` | Filter by `account_id`, `date_from`, `date_to` (inclusive), `category_id`, `categorized` (`false` = only uncategorized), `needs_review` (`true` = only the review queue) and search text `q`; conditions combine with AND. Newest first, paged with `limit`/`offset`, with the `total` match count |
| `GET /transactions/range` | `first_date` and `last_date` of all stored transactions (both `null` when there are none) |
| `PATCH /transactions/{id}` | Set the category and/or merchant name (marked as the user's choice). A category set here is also remembered for the merchant |
| `GET /transactions/{id}/same-merchant` | `merchant` and `count`: how many other transactions from the same merchant (by `merchant_key`) have a different or no category and weren't set by the user, for "Apply to all 14 from Blue Bottle?" |
| `POST /transactions/{id}/same-merchant/apply` | Give this transaction's category to those transactions; returns `updated`. `409` if it has no category |
| `GET /categorization/status` | The background categorization run: `state` (`idle`, `queued`, `running`), `processed` of `total`, `last_error` (plain language, or `null`) and `runs_finished`, which counts up when a run ends |
| `POST /categorization/run` | `{"scope": "uncategorized" \| "all"}`: categorize in the background (`202`). `all` asks every tier again for every transaction whose category the user didn't set |
| `GET /review/summary` | `waiting` (transactions flagged `needs_review`) and `with_suggestion` (of those, how many have a suggested category). The queue itself is `GET /transactions?needs_review=true` |
| `POST /review/accept` | `{"transaction_ids": [...]}` (1 to 1000): accept each suggestion, which becomes the user's choice and is remembered for the merchant; returns `accepted` |
| `POST /review/accept-all` | Accept every suggestion in the queue matching `account_id`, `date_from`, `date_to`, `category_id` and `q` (all optional, as for `GET /transactions`) |
| `GET /rules` | Every rule in the order they are tried: the user's (`created_by: "user"`) first, then Monelyth's defaults, each by `priority` and then longest pattern |
| `POST /rules` | `{"pattern", "match_type": "contains" \| "regex", "category_id", "priority"}`. `422` explains a pattern that can't be used, `409` if the user already has that pattern. Re-categorizes what the rule matches |
| `PATCH /rules/{id}`, `DELETE /rules/{id}` | Change or delete one of the user's rules (`403` for a default rule). Both re-categorize what the rule matched before and matches now |
| `POST /rules/preview` | `{"pattern", "match_type"}`: `matching` (stored transactions the pattern matches), `user_set` (of those, how many keep the category the user set) and a few `examples`. Saves nothing |
| `DELETE /transfers/{transfer_group}` | Unlink two transactions wrongly paired as a transfer; returns both. A side in Transfers only because of the link becomes uncategorized and needs review; a category the user chose stays. `404` if they are no longer linked |
| `GET /system/info` | Engine version, data folder, database size, and how many accounts and transactions there are |
| `POST /data/export` | `{"folder": "<full path>"}`: writes a new `Monelyth export <date> <time>` folder there with a copy of the database (SQLite backup API), `transactions.csv` and a README; returns its `path` |
| `POST /data/erase` | `{"confirm": "DELETE"}`: deletes all user data in one step and leaves a freshly seeded database |
| `POST /demo` | `{"currency": "CAD"}`: adds a "Demo Checking" account and a "Demo Visa" card with a year of made-up transactions ending today, imported exactly like an uploaded statement. `409` if the demo accounts already exist |

Sample statements to try it with are in [`../sample-data/`](../sample-data/).

## Categorization

Imported transactions are categorized in the background (`monelyth_engine.categorize`). The
tiers are asked in order and the first answer wins:

1. **Merchant memory from the user's corrections.** Setting a category remembers it for the
   merchant (keyed by `merchant_key`, so "Blue Bottle" and "BLUE-BOTTLE" are one merchant).
2. **Rules**: the user's, then about 140 defaults (`db/migrations/002_default_rules.sql`).
   `contains` matches whole words of the merchant name or bank description, ignoring case,
   accents and punctuation; `regex` is searched case-insensitively, and patterns whose
   matching time could explode are refused. A new or changed rule takes over from merchant
   memory for the merchants it matches.
3. **Merchant memory from earlier confident classifier or LLM answers.**
4. **Optional tiers** (classifier, local LLM), plugged in through
   `installed_extensions()` in `categorize/tiers.py`, which also takes pre-passes such as
   transfer linking.

A category the user set is never changed, and neither is a linked transfer. Answers below
`REVIEW_THRESHOLD` (0.80) are stored but flagged `needs_review`; a transaction no tier answers
stays uncategorized in the review queue. A tier that fails is logged and skipped for the rest
of the run.

Runs happen after every successful import and demo-data load, at startup for anything never
categorized, after a rule changes (over the transactions it affects) and on demand. One worker
thread does them in order, merging requests that arrive meanwhile into one run.

### Measuring it

```bash
uv run python scripts/eval_categorizer.py
```

Categorizes `../sample-data/labels.csv` (and `../private-data/labels.csv`, git-ignored, when
it exists) in memory and prints accuracy, coverage per tier, per-category precision, recall
and F1, the most common mix-ups, and the same after one round of corrections (the user fixes
the first transaction of each merchant). With memory and rules only, on the sample data:

| | Accuracy | Coverage |
|---|---|---|
| Before any corrections | 95.9% | 95.9% (every answer correct) |
| After one round of corrections | 100.0% | 100.0% |

The sample data is generated, and the default rules were written with it in view, so these
numbers flatter the rules; `private-data/labels.csv` gives the honest ones.

## Command-line options

| Option | Default | Purpose |
|---|---|---|
| `--data-dir PATH` | required | Folder for the database and other user data |
| `--port N` | `0` | Port to listen on; `0` lets the OS pick a free one |
| `--allowed-origin URL` | none | Origin allowed to call the API from a webview (repeatable) |
| `--exit-on-stdin-eof` | off | Exit when stdin closes or receives `shutdown`; used by the desktop shell so the engine never outlives the app |
| `--log-level LEVEL` | `info` | `debug`, `info`, `warning` or `error` |

The token is read from the `MONELYTH_TOKEN` environment variable (at least 32 characters of
`A-Z a-z 0-9 _ -`), never from the command line, where other processes could read it.

## Building the sidecar

```bash
uv run python scripts/build_sidecar.py
```

Builds a single executable with PyInstaller, smoke-tests it, and copies it to
`apps/desktop/src-tauri/binaries/` under the file name Tauri expects.
