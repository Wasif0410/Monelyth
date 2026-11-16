# Checkpoint — where Monelyth stands

Last updated: 2026-11-16. Read this first when picking the project up in a new chat, then
[PLAN.md](../PLAN.md) for the full architecture and phase plan.

## What Monelyth is

A private, offline personal-finance **desktop app** for Windows. Import bank statements, get
automatic categories, track income and spending, and (later) ask a local AI about your money.
Nothing leaves the computer. It is a portfolio project that will also be released publicly
(LinkedIn), so the bar is production quality: strict types, linting, tests, and verification in
the real installed app.

**Stack:** Tauri 2 (Rust shell, `apps/desktop/src-tauri/`) + React 19 / TypeScript / Tailwind 4
UI (`apps/desktop/src/`) + Python 3.12 FastAPI engine run as a sidecar (`engine/`, managed with
uv). It is a real desktop app (own window, ~18 MB installer); the UI is drawn by WebView2.

## Status

| Phase | State | Merged in |
|---|---|---|
| 0 Foundations, installer, CI | Done | PR #1 |
| 1 Data engine (CSV/OFX import, merchant cleaning, dedupe) | Done | PR #2 |
| 2 Screens (onboarding + demo data, import, transactions, accounts, settings) | Done | PR #3 |
| 3 Categorization (memory, 138 rules, review queue, corrections, transfers, local-LLM tier) | Done (no classifier tier) | PR #4 |
| Desktop feel (icon, tray, start at sign-in, window memory, notifications) | **In progress** | branch `desktop/native-feel` |
| 4 Insights and dashboard | Next | — |
| 5 Local AI chat · 6 Packaging + v0.1 release · 7 PDF + autopilot · 8 Hardening | Later | — |

`main` is protected: the three CI checks (Engine, Frontend, Shell + installer) must pass.
Test suites at last run: engine ~1,390 pytest, UI 243 vitest, Rust 7 tests, all passing.

## In progress: branch `desktop/native-feel` (committed locally, not pushed, no PR yet)

What it adds:
- **Real app icon** (`src-tauri/icons/source/app-icon.svg`, all sizes generated with
  `pnpm tauri icon`); the in-app `Logo` component draws the same mark.
- **Single instance** — a second launch focuses the running window (one engine per database).
- **Window memory** (size, position, maximized) via `tauri-plugin-window-state`.
- **System tray** — Open / Import a statement… / Quit; optional **close to tray**.
- **Start at sign-in** (`tauri-plugin-autostart`, starts with `--minimized` into the tray).
- **Windows notifications** when a background categorization run finishes while the app isn't
  in front.
- **Settings → Desktop** card with the three switches; preferences live in Tauri's
  `preferences.json` store (Rust reads `closeToTray`). Rust code: `src-tauri/src/desktop.rs`.

Verified in the installed release build: icon in the title bar, single instance, window memory
(1000×700 at 200,150 restored exactly), close-to-tray hides and a relaunch restores, start at
sign-in writes and removes the `HKCU\…\Run` entry. All UI tests and clippy pass.

**Still to do before the PR:**
1. Rebuild (`pnpm --dir apps/desktop tauri build`) and re-check closing: a normal close must quit
   the app *and* engine; close-to-tray must only hide. The last change (`WindowEvent::Destroyed`
   → `app.exit(0)` in `desktop.rs`) is a safety net for a one-off seen once in testing (window
   destroyed, process kept running) that could not be reproduced in 8 attempts.
2. Commit any fixes, push the branch, open the PR, enable auto-merge after CI.

## Open decisions and loose ends

- **Laya** (the classifier the user first asked about) was evaluated and **not shipped**: 52.8%
  of merchants right at best, wrong 1 in 3 even at ≥0.8 confidence. Details:
  `engine/research/laya_eval/RESULTS.md`. Its downloads (~4.3 GB: model in
  `%USERPROFILE%\.cache\huggingface\hub\models--convaiinnovations--laya` and a PyTorch research
  env) are still on disk — ask the user whether to delete them.
- **Embedding nearest-neighbour classifier** (PLAN 3.4 path c) — user approved evaluating it
  (~130 MB model download). Not started yet.
- The **local-LLM tier** has never run against a real model (none installed). Configure with
  `MONELYTH_LLM_URL` + `MONELYTH_LLM_MODEL` (loopback only).
- **Clean-machine install test** in Windows Sandbox (PLAN 0.6) never done.
- `page-transactions.png` in the repo root is an untracked leftover from a browser test; safe to
  delete with the user's OK.
- **Unlinked transfers are remembered** (migration 003). The categorization eval (95.9% before
  corrections, 100% after) is optimistic: sample data is synthetic and the rules were written
  against it; a real `private-data/labels.csv` is needed for an honest number.

## How work has been done (keep doing it this way)

- **Multi-agent phases:** write a small shared contract first on a phase branch, then start
  parallel sessions (one per independent piece, each in its own worktree, owning separate files),
  review their branches, test-merge them in a throwaway worktree, ask the user before merging,
  integrate, verify in the installed app, open the PR with auto-merge. Merges use merge commits.
- **Verification in the real app:** launch
  `apps/desktop/src-tauri/target/release/monelyth.exe` with
  `WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS=--remote-debugging-port=<port>` and drive the UI over the
  Chrome DevTools Protocol (real mouse events, `DOM.setFileInputFiles` for uploads,
  `Page.captureScreenshot`). Reset afterwards with Settings → Delete everything.
- **Gotcha:** processes started from inside the Claude desktop app inherit its package identity,
  so AppData is redirected to `%LOCALAPPDATA%\Packages\Claude_…\LocalCache\…` and the window
  groups under Claude's taskbar icon. Launch through `explorer.exe` to see the real behaviour.
- **Gotcha:** the shadcn CLI rewrites component imports to an npm package named `cn` and adds it
  as a dependency. Always point imports back at `@/lib/utils` and `pnpm remove cn`.
- pnpm enforces a minimum release age: pick dependency versions at least a week old. Tauri npm
  and crate versions must share major.minor (the build checks).
- No attribution lines in commits or PR descriptions.

## Commands

```bash
# Engine checks (from engine/)
uv run ruff format --check . && uv run ruff check . && uv run pyright && uv run pytest
uv run python scripts/eval_categorizer.py      # categorization accuracy report

# UI checks (from apps/desktop/)
pnpm format:check && pnpm lint && pnpm typecheck && pnpm test
pnpm api:types                                  # regenerate TS types after engine API changes

# Shell checks (from apps/desktop/src-tauri/)
cargo fmt --check && cargo clippy --all-targets --locked -- -D warnings && cargo test --locked

# Build (from apps/desktop/)
pnpm sidecar            # engine executable + smoke test (needed before any Rust build)
pnpm tauri build        # installer: src-tauri/target/release/bundle/nsis/
pnpm tauri dev          # run in development (engine from source)
```
