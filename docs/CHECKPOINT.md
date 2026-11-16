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
| Desktop feel (icon, tray, start at sign-in, window memory, notifications) | Done, **PR open** (waiting on CI/merge) | branch `desktop/native-feel` |
| 4 Insights and dashboard | Next | — |
| 5 Local AI chat · 6 Packaging + v0.1 release · 7 PDF + autopilot · 8 Hardening | Later | — |

`main` is protected: the three CI checks (Engine, Frontend, Shell + installer) must pass.
Test suites at last run: engine ~1,390 pytest, UI 243 vitest, Rust 7 tests, all passing.

## Desktop feel: branch `desktop/native-feel` (pushed, PR open)

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

Closing re-verified on the final release build (2026-11-16), 10 runs each, launched through
`explorer.exe`: a normal close quits the app and both engine processes (the PyInstaller launcher
and the server); with close-to-tray on, the window is hidden (not destroyed), app and engine keep
running, and a relaunch shows the same window with one instance. `desktop.rs` now logs "Window
closed; hiding to the tray" / "Window destroyed; quitting", which makes this visible in the log.

**Next:** once CI is green, merge the PR (merge commit), then start Phase 4.

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
- **Gotcha (testing settings):** the same package identity also redirects *file writes* to
  `%APPDATA%` from Claude's shells into `%LOCALAPPDATA%\Packages\Claude_…\LocalCache\Roaming\…`,
  while reads still show the redirected copy. So editing `preferences.json` from a Claude shell
  never reaches an app launched through `explorer.exe`. Run such test scripts themselves through
  `explorer.exe` (e.g. a `.cmd` wrapper), and back up / restore the real file around them.
  .NET's `Process.MainWindowHandle` is unreliable for hidden windows; check the saved handle with
  `IsWindowVisible` / `IsWindow` instead (user32 calls only work outside Claude's sandbox).
- **Gotcha (Rust builds):** run `cargo` / `pnpm tauri build` from PowerShell, not Git Bash (Git's
  `/usr/bin/link` shadows the MSVC linker). On this machine the Visual Studio instance registry
  (`C:\ProgramData\Microsoft\VisualStudio\Packages\_Instances`) is missing, so Rust can't find
  `link.exe` on its own: wrap builds as
  `cmd /c "\"C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvars64.bat\" >nul && pnpm tauri build"`.
  (A Visual Studio Installer "Repair" would likely restore the registry.)
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
