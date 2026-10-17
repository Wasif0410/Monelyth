# Monelyth

**Private, offline personal finance.** Import your bank statements, see where your money goes,
and ask questions about it, with an AI model that runs entirely on your computer. Your data
never leaves your machine.

> **Status:** early development (Phase 0 of [the build plan](PLAN.md)). The desktop shell,
> the local engine and the Windows installer work end to end. Features start in Phase 1.

## How it works

| Piece | Tech | Role |
|---|---|---|
| Desktop shell | Tauri 2 (Rust) | Opens the window; starts, supervises and stops the engine |
| UI | React, TypeScript, Tailwind | Everything you see |
| Engine | Python, FastAPI | Statement import, categorization, insights, AI chat |
| Storage | SQLite (from Phase 1) | One file on your computer |

The engine listens on `127.0.0.1` only and rejects every request without a random token the
shell creates on each launch. The UI is locked down by a Content Security Policy, so it cannot
contact outside servers. Details in [PLAN.md](PLAN.md#2-how-the-app-fits-together).

## Development

Requirements: Windows 10/11, [uv](https://docs.astral.sh/uv/), Node 22+ with pnpm, Rust
1.90+ (`rustup`), and the Microsoft C++ Build Tools.

```bash
# One-time setup
uv sync --project engine
pnpm --dir apps/desktop install

# Build the engine sidecar once. Tauri refuses to compile without it, even in dev mode.
pnpm --dir apps/desktop sidecar

# Run the app. In dev mode the engine runs from source, so Python changes apply on restart.
pnpm --dir apps/desktop tauri dev
```

### Checks

```bash
# Engine
cd engine && uv run ruff format --check . && uv run ruff check . && uv run pyright && uv run pytest

# Frontend
cd apps/desktop && pnpm format:check && pnpm lint && pnpm typecheck && pnpm test

# Shell
cd apps/desktop/src-tauri && cargo fmt --check && cargo clippy --all-targets -- -D warnings && cargo test
```

CI runs all of these on every push and builds the installer
([`.github/workflows/ci.yml`](.github/workflows/ci.yml)).

### Building the installer

```bash
pnpm --dir apps/desktop sidecar
pnpm --dir apps/desktop tauri build
```

Output: `apps/desktop/src-tauri/target/release/bundle/nsis/Monelyth_<version>_x64-setup.exe`.
It installs per user, so no administrator rights are needed.

## Repository layout

```
apps/desktop/        Tauri app: React UI in src/, Rust shell in src-tauri/
engine/              Python engine (uv project) with its tests and build scripts
.github/workflows/   CI
PLAN.md              Architecture and phased build plan
```

## License

[MIT](LICENSE)
