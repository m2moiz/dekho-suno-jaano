#!/usr/bin/env python3
"""Write or check the hash that says whether the committed page is stale (#114).

The page `dsj ui` serves is built from ui/ into dsj/ui/static/ and committed,
so an install needs no Node. The hazard: edit ui/, forget `just ui-build`, and
the app serves last week's bundle while every check stays green. Comparing the
built files is no use, because Vite names them by content hash and they change
for reasons that are not staleness. So the build records a hash of its INPUTS,
and `just check` recomputes it.

    uv run python scratch/ui_manifest.py write   # end of `just ui-build`
    uv run python scratch/ui_manifest.py check   # `just ui-fresh`, in `check`

The inputs are every file under ui/ but node_modules, Playwright's output and
dotfiles, not only ui/src/ and the two package files #114 named. Tailwind reads
every file under ui/ for class names, tests included: a word in a test comment
was measured to add a CSS rule to the build (2026-10-02). A hash over less than
what the build reads would call a changed build fresh.

Standard library only, and no Node: `check` must work, and fail, on a machine
with no ui/node_modules, since a check that cannot run must not pass.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
MANIFEST = ".build-manifest.json"
# Directories under ui/ that are tool output or installed packages, not inputs.
SKIPPED_DIRS = {"node_modules", "test-results", "playwright-report"}
REMEDY = "run: just ui-build"


def inputs(ui: Path) -> list[Path]:
    """Every file the build can read, sorted by path so the hash is stable."""
    found = [
        path
        for path in ui.rglob("*")
        if path.is_file()
        and not any(part in SKIPPED_DIRS for part in path.relative_to(ui).parts)
        # .DS_Store, .npmrc: Finder litter and npm settings, never read by the build.
        and not any(part.startswith(".") for part in path.relative_to(ui).parts)
    ]
    return sorted(found, key=lambda path: path.relative_to(ui).as_posix())


def source_hash(ui: Path) -> tuple[str, int]:
    """SHA-256 over each input's path and contents, and how many inputs there were.

    The path and the length go in ahead of each file's bytes, so moving bytes
    from one file to the next, or renaming a file, changes the hash too.
    """
    digest = hashlib.sha256()
    files = inputs(ui)
    for path in files:
        data = path.read_bytes()
        digest.update(f"{path.relative_to(ui).as_posix()}\0{len(data)}\0".encode())
        digest.update(data)
    return digest.hexdigest(), len(files)


def write(ui: Path, static: Path) -> None:
    sha, count = source_hash(ui)
    # No timestamp: a rebuild of unchanged sources must leave this file as it was.
    body = {"sha256": sha, "inputs": count, "from": "the files under ui/ that scratch/ui_manifest.py hashes"}
    (static / MANIFEST).write_text(json.dumps(body, indent=2) + "\n")


def check(ui: Path, static: Path) -> str | None:
    """None when the build is fresh, else the reason it is not."""
    manifest = static / MANIFEST
    if not manifest.is_file():
        return f"stale frontend build: dsj/ui/static/{MANIFEST} is missing -- {REMEDY}"
    recorded = json.loads(manifest.read_text())["sha256"]
    sha, _ = source_hash(ui)
    if sha != recorded:
        return f"stale frontend build: ui/ changed since dsj/ui/static/ was built -- {REMEDY}"
    return None


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    parser.add_argument("action", choices=["write", "check"])
    parser.add_argument("--root", type=Path, default=REPO, help="the repo root (tests)")
    args = parser.parse_args(argv)
    ui, static = args.root / "ui", args.root / "dsj" / "ui" / "static"
    if args.action == "write":
        write(ui, static)
        return 0
    problem = check(ui, static)
    if problem is not None:
        print(problem, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
