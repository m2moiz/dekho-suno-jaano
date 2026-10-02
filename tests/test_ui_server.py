"""`dsj ui`: the extra it needs, and what it says when that extra is missing (#111).

Every test that needs the missing state makes it, by hiding the module in
sys.modules, rather than skipping when fastapi happens to be installed. A test
that only runs on the machine without the extra is a test the suite never runs.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from dsj.cli import main
from dsj.ui import UIUnavailable

REPO = Path(__file__).resolve().parent.parent

# The line that installs the extra, as the message must carry it. Not the bare
# `uv tool install 'dsj[mac,ui]'` #111 names: dsj is not on PyPI, so that line
# fails to resolve, and a remedy that does not work is not a remedy.
INSTALL_LINE = 'uv tool install "dsj[mac,ui] @ git+https://github.com/m2moiz/dekho-suno-jaano"'


@pytest.mark.parametrize("module", ["fastapi", "uvicorn"])
def test_a_missing_extra_names_the_line_that_installs_it(
    module: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    # None in sys.modules makes `import <module>` raise ImportError, which is
    # exactly what a bare install does.
    monkeypatch.setitem(sys.modules, module, None)
    with pytest.raises(UIUnavailable) as caught:
        main(["ui"])
    message = str(caught.value)
    assert INSTALL_LINE in message
    assert "--extra ui" in message
    # A whole `uv sync` line uninstalls every extra it does not name (#170).
    assert "uv sync --extra ui" not in message
    assert module in message, "the message should say which import failed"


def test_ui_unavailable_is_a_runtime_error_like_its_siblings() -> None:
    from dsj.asr import EngineUnavailable

    assert issubclass(UIUnavailable, RuntimeError)
    assert issubclass(EngineUnavailable, RuntimeError)


def test_help_and_the_cli_never_import_the_web_server() -> None:
    """The extra is paid for by `dsj ui` alone, not by every `dsj --help`."""
    probe = (
        "import sys\n"
        "from dsj.cli import main\n"
        "try:\n"
        "    main(['--help'])\n"
        "except SystemExit:\n"
        "    pass\n"
        "loaded = sorted(m for m in ('fastapi', 'uvicorn', 'starlette') if m in sys.modules)\n"
        "print('LOADED', loaded)\n"
    )
    out = subprocess.run(
        [sys.executable, "-c", probe], capture_output=True, text=True, check=True, timeout=120
    ).stdout
    assert "LOADED []" in out, out


def test_a_bare_install_carries_no_web_server() -> None:
    """Read off the lockfile, through uv, so a transitive pull counts too."""
    def exported(*extra: str) -> set[str]:
        out = subprocess.run(
            ["uv", "export", "--frozen", "--no-dev", "--no-hashes", "--no-emit-project", *extra],
            capture_output=True, text=True, check=True, cwd=REPO, timeout=120,
        ).stdout
        return {line.split("==")[0] for line in out.splitlines() if "==" in line}

    server = {"fastapi", "uvicorn"}
    assert not exported() & server
    # The other half, so the check above cannot pass by reading nothing.
    assert exported("--extra", "ui") >= server
    assert exported("--extra", "mac") >= server
