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
| `PATCH /transactions/{id}` | Set the category and/or merchant name (marked as the user's choice) |
| `DELETE /transfers/{transfer_group}` | Unlink two transactions wrongly paired as a transfer; returns both. A side in Transfers only because of the link becomes uncategorized and needs review; a category the user chose stays. `404` if they are no longer linked |
| `GET /system/info` | Engine version, data folder, database size, and how many accounts and transactions there are |
| `POST /data/export` | `{"folder": "<full path>"}`: writes a new `Monelyth export <date> <time>` folder there with a copy of the database (SQLite backup API), `transactions.csv` and a README; returns its `path` |
| `POST /data/erase` | `{"confirm": "DELETE"}`: deletes all user data in one step and leaves a freshly seeded database |
| `POST /demo` | `{"currency": "CAD"}`: adds a "Demo Checking" account and a "Demo Visa" card with a year of made-up transactions ending today, imported exactly like an uploaded statement. `409` if the demo accounts already exist |

Sample statements to try it with are in [`../sample-data/`](../sample-data/).

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
