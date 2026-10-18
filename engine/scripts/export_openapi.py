"""Write the engine's OpenAPI schema to the desktop app, where TypeScript types are made from it.

Usage (from the ``engine`` folder)::

    uv run python scripts/export_openapi.py [OUTPUT]

``OUTPUT`` defaults to ``apps/desktop/src/api/openapi.json``. The desktop app's
``pnpm api:types`` script runs this and then ``openapi-typescript``, and CI fails if the
committed types differ from a fresh export, so the UI can't drift from the engine.
"""

from __future__ import annotations

import json
import secrets
import sys
import tempfile
from pathlib import Path
from typing import Final

from monelyth_engine.app import create_app
from monelyth_engine.config import Settings

REPO_DIR: Final = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT: Final = REPO_DIR / "apps" / "desktop" / "src" / "api" / "openapi.json"


def main(argv: list[str]) -> int:
    output = Path(argv[0]).resolve() if argv else DEFAULT_OUTPUT
    # create_app opens a database, so give it a throwaway one; the schema doesn't depend on it.
    with tempfile.TemporaryDirectory(prefix="monelyth-openapi-") as data_dir:
        app = create_app(
            Settings(
                data_dir=Path(data_dir),
                token=secrets.token_hex(32),
                port=0,
                allowed_origins=(),
                exit_on_stdin_eof=False,
                log_level="warning",
            )
        )
        schema = app.openapi()
    output.parent.mkdir(parents=True, exist_ok=True)
    # Sorted keys and a trailing newline make the file stable, so diffs show real changes only.
    output.write_text(
        json.dumps(schema, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
    )
    print(f"OpenAPI schema written to {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
