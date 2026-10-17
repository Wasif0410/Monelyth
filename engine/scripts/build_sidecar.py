"""Build the engine into one executable and install it as the desktop app's Tauri sidecar.

Usage (from the ``engine`` folder)::

    uv run python scripts/build_sidecar.py

Steps:

1. Build ``monelyth-engine`` with PyInstaller in a temporary folder.
2. Smoke-test the executable: start it, wait for the READY line, call ``/health`` with the
   token, then ask it to shut down. A binary that is missing a module fails here instead of
   on a user's machine.
3. Copy it to ``apps/desktop/src-tauri/binaries/monelyth-engine-<target-triple>[.exe]``,
   the name Tauri requires for ``bundle.externalBin``.
"""

from __future__ import annotations

import json
import os
import queue
import secrets
import shutil
import subprocess
import sys
import tempfile
import threading
import urllib.request
from pathlib import Path
from typing import IO, Final

ENGINE_DIR: Final = Path(__file__).resolve().parents[1]
REPO_DIR: Final = ENGINE_DIR.parent
BINARIES_DIR: Final = REPO_DIR / "apps" / "desktop" / "src-tauri" / "binaries"
ENTRY_SCRIPT: Final = ENGINE_DIR / "scripts" / "sidecar_entry.py"
NAME: Final = "monelyth-engine"
EXE_SUFFIX: Final = ".exe" if sys.platform == "win32" else ""
SMOKE_TIMEOUT_S: Final = 60.0


def main() -> int:
    triple = _host_target_triple()
    with tempfile.TemporaryDirectory(prefix="monelyth-sidecar-") as tmp:
        built = _build(Path(tmp))
        _smoke_test(built)
        BINARIES_DIR.mkdir(parents=True, exist_ok=True)
        destination = BINARIES_DIR / f"{NAME}-{triple}{EXE_SUFFIX}"
        shutil.copy2(built, destination)

    size_mb = destination.stat().st_size / 1_000_000
    print(f"Sidecar ready: {destination.relative_to(REPO_DIR)} ({size_mb:.1f} MB)")
    return 0


def _host_target_triple() -> str:
    """Return the Rust target triple (e.g. ``x86_64-pc-windows-msvc``) Tauri builds for."""
    output = subprocess.run(["rustc", "-vV"], check=True, capture_output=True, text=True).stdout
    for line in output.splitlines():
        key, _, value = line.partition(": ")
        if key == "host":
            return value.strip()
    raise RuntimeError("could not find the host target triple in `rustc -vV` output")


def _build(work_dir: Path) -> Path:
    dist_dir = work_dir / "dist"
    subprocess.run(
        [
            sys.executable,
            "-m",
            "PyInstaller",
            "--noconfirm",
            "--clean",
            "--onefile",
            "--name",
            NAME,
            "--distpath",
            str(dist_dir),
            "--workpath",
            str(work_dir / "build"),
            "--specpath",
            str(work_dir),
            # __version__ is read from the package metadata at runtime.
            "--copy-metadata",
            "monelyth-engine",
            # uvicorn imports its protocol and loop implementations by name.
            "--collect-submodules",
            "uvicorn",
            "--exclude-module",
            "tkinter",
            str(ENTRY_SCRIPT),
        ],
        check=True,
        cwd=ENGINE_DIR,
    )
    executable = dist_dir / f"{NAME}{EXE_SUFFIX}"
    if not executable.is_file():
        raise RuntimeError(f"PyInstaller did not produce {executable}")
    return executable


def _smoke_test(executable: Path) -> None:
    token = secrets.token_hex(32)
    with tempfile.TemporaryDirectory(prefix="monelyth-smoke-") as data_dir:
        process = subprocess.Popen(
            [str(executable), "--data-dir", data_dir, "--exit-on-stdin-eof"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            env={**os.environ, "MONELYTH_TOKEN": token},
            text=True,
        )
        try:
            port = _wait_for_ready(process)
            request = urllib.request.Request(
                f"http://127.0.0.1:{port}/health",
                headers={"Authorization": f"Bearer {token}"},
            )
            with urllib.request.urlopen(request, timeout=10) as response:  # noqa: S310 -- fixed loopback URL
                body: object = json.loads(response.read())
            if not isinstance(body, dict) or body.get("status") != "ok":  # pyright: ignore[reportUnknownMemberType]
                raise RuntimeError(f"unexpected /health response: {body!r}")

            if process.stdin is None:
                raise RuntimeError("sidecar stdin is not a pipe")
            process.stdin.write("shutdown\n")
            process.stdin.flush()
            exit_code = process.wait(timeout=SMOKE_TIMEOUT_S)
            if exit_code != 0:
                raise RuntimeError(f"sidecar exited with code {exit_code} after shutdown")
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()
    print("Smoke test passed.")


def _wait_for_ready(process: subprocess.Popen[str]) -> int:
    if process.stdout is None:
        raise RuntimeError("sidecar stdout is not a pipe")
    lines: queue.Queue[str | None] = queue.Queue()

    def pump(stream: IO[str]) -> None:
        for line in stream:
            lines.put(line)
        lines.put(None)

    threading.Thread(target=pump, args=(process.stdout,), daemon=True).start()
    try:
        line = lines.get(timeout=SMOKE_TIMEOUT_S)
    except queue.Empty:
        raise RuntimeError("sidecar did not announce READY in time") from None
    if line is None or not line.startswith("MONELYTH_READY "):
        raise RuntimeError(f"sidecar did not start correctly (first stdout line: {line!r})")
    port = json.loads(line.removeprefix("MONELYTH_READY "))["port"]
    if not isinstance(port, int):
        raise RuntimeError(f"invalid port in READY line: {line!r}")
    return port


if __name__ == "__main__":
    raise SystemExit(main())
