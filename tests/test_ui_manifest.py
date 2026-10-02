"""The stale-build check (#114): scratch/ui_manifest.py, run as `just ui-fresh`.

Each test builds a small repo in tmp_path, so the real ui/ is never touched,
and runs the script the way the recipe does, as a subprocess.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scratch" / "ui_manifest.py"


def run(root: Path, action: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), action, "--root", str(root)],
        capture_output=True, text=True, timeout=60,
    )


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    ui = tmp_path / "ui"
    (ui / "src").mkdir(parents=True)
    (ui / "tests" / "unit").mkdir(parents=True)
    (ui / "src" / "main.tsx").write_text("export const a = 1;\n")
    (ui / "tests" / "unit" / "a.test.ts").write_text("// a test\n")
    (ui / "package.json").write_text("{}\n")
    (ui / "package-lock.json").write_text("{}\n")
    (tmp_path / "dsj" / "ui" / "static").mkdir(parents=True)
    assert run(tmp_path, "write").returncode == 0
    return tmp_path


def test_a_fresh_build_passes(repo: Path) -> None:
    done = run(repo, "check")
    assert done.returncode == 0, done.stderr


def test_the_manifest_has_no_timestamp_so_an_unchanged_rebuild_leaves_it_alone(
    repo: Path,
) -> None:
    manifest = repo / "dsj" / "ui" / "static" / ".build-manifest.json"
    before = manifest.read_bytes()
    run(repo, "write")
    assert manifest.read_bytes() == before
    assert json.loads(before)["inputs"] == 4


@pytest.mark.parametrize(
    "edit",
    [
        "src/main.tsx",              # the source itself
        "package-lock.json",         # a dependency moved
        "tests/unit/a.test.ts",      # Tailwind reads tests for class names too
        "src/new.ts",                # a file added
    ],
)
def test_any_edit_the_build_can_see_is_stale_and_names_the_remedy(
    repo: Path, edit: str
) -> None:
    path = repo / "ui" / edit
    path.write_text(path.read_text() + "// probe\n" if path.exists() else "// new\n")
    done = run(repo, "check")
    assert done.returncode == 1
    assert "stale frontend build" in done.stderr
    assert "run: just ui-build" in done.stderr


def test_a_renamed_file_is_stale(repo: Path) -> None:
    ui = repo / "ui"
    (ui / "src" / "main.tsx").rename(ui / "src" / "index.tsx")
    assert run(repo, "check").returncode == 1


@pytest.mark.parametrize(
    "noise", ["node_modules/vite/index.js", "test-results/run.json", ".DS_Store", "src/.DS_Store"]
)
def test_installed_packages_test_output_and_dotfiles_are_not_inputs(
    repo: Path, noise: str
) -> None:
    path = repo / "ui" / noise
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("noise\n")
    done = run(repo, "check")
    assert done.returncode == 0, done.stderr


def test_a_missing_manifest_fails_rather_than_passing(repo: Path) -> None:
    """What Vite's emptyOutDir leaves when someone builds without `just ui-build`."""
    (repo / "dsj" / "ui" / "static" / ".build-manifest.json").unlink()
    done = run(repo, "check")
    assert done.returncode == 1
    assert ".build-manifest.json is missing" in done.stderr
    assert "run: just ui-build" in done.stderr

