"""`dsj ui`: the extra it needs (#111), and the page it serves (#154).

Every test that needs the missing state makes it, by hiding the module in
sys.modules, rather than skipping when fastapi happens to be installed. A test
that only runs on the machine without the extra is a test the suite never runs.
For the same reason nothing here skips when fastapi is absent: the server tests
then fail, which is what CI's `--extra ui` is for.
"""

from __future__ import annotations

import json
import re
import signal
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import dsj.ui.server
from dsj.cli import main
from dsj.ui import UIUnavailable
from dsj.ui.server import STATIC, create_app

REPO = Path(__file__).resolve().parent.parent
UI = REPO / "ui"
CONSOLE_SCRIPT = Path(sys.executable).parent / "dsj"

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


def test_everything_under_dsj_ui_but_the_server_imports_without_the_extra() -> None:
    """The library store is plain sqlite3, and a terminal `dsj suno` records itself in it.

    So only dsj/ui/server.py may need fastapi. Every other module in the package,
    found by listing it rather than by name so one added later is covered too, is
    imported with the extra's packages hidden, in a fresh interpreter, so nothing
    this suite already imported can stand in for them.
    """
    probe = (
        "import importlib, pkgutil, sys\n"
        "for name in ('fastapi', 'uvicorn', 'starlette'):\n"
        "    sys.modules[name] = None\n"
        "import dsj.ui\n"
        "names = [m.name for m in pkgutil.iter_modules(dsj.ui.__path__) if m.name != 'server']\n"
        "for name in names:\n"
        "    importlib.import_module(f'dsj.ui.{name}')\n"
        "print('IMPORTED', ['dsj.ui', *names])\n"
    )
    done = subprocess.run(
        [sys.executable, "-c", probe], capture_output=True, text=True, check=False, timeout=120
    )
    assert done.returncode == 0, done.stderr
    assert "IMPORTED ['dsj.ui'" in done.stdout, done.stdout


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


# --------------------------------------------------------------------------
# The server and the page (#154)
# --------------------------------------------------------------------------


def client() -> TestClient:
    return TestClient(create_app(port=8721)[0])


def no_serving(*_args: object, **_kwargs: object) -> None:
    """Stands in for uvicorn.Server.run, so a test can call `dsj ui` and return."""


def built_assets(page: str) -> list[str]:
    """Every /assets/ path the built index.html asks the browser for."""
    return re.findall(r'(?:src|href)="(/assets/[^"]+)"', page)


def test_create_app_returns_an_app_and_a_token() -> None:
    app, token = create_app(port=8721)
    assert isinstance(app, FastAPI)
    assert len(token) >= 32
    # A token per launch, not a constant: one baked in would be in every copy.
    assert create_app(port=8721)[1] != token


def test_the_root_is_the_built_page_and_every_asset_it_names_loads() -> None:
    browser = client()
    page = browser.get("/")
    assert page.status_code == 200
    assert page.headers["content-type"].startswith("text/html")
    assert page.text == (STATIC / "index.html").read_text()
    assets = built_assets(page.text)
    assert any(asset.endswith(".js") for asset in assets), assets
    for asset in assets:
        got = browser.get(asset)
        assert got.status_code == 200, asset
        assert got.content == (STATIC / asset.removeprefix("/")).read_bytes()


def test_the_recordings_route_answers_an_empty_list() -> None:
    got = client().get("/api/recordings")
    assert got.status_code == 200
    assert got.json() == []


def test_a_missing_build_says_which_recipe_writes_it(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(dsj.ui.server, "STATIC", tmp_path)
    with pytest.raises(UIUnavailable, match="just ui-build"):
        create_app(port=8721)


@pytest.mark.parametrize(("flag", "opened"), [([], True), (["--print-url"], False)])
def test_print_url_is_what_keeps_the_browser_closed(
    flag: list[str], opened: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[str] = []
    monkeypatch.setattr("webbrowser.open", seen.append)
    monkeypatch.setattr("uvicorn.Server.run", no_serving)
    assert main(["ui", *flag]) == 0
    assert bool(seen) is opened
    assert all(re.fullmatch(r"http://127\.0\.0\.1:\d+/", url) for url in seen), seen


def test_dsj_ui_print_url_serves_the_page_on_loopback() -> None:
    """The command itself, as a process, fetched over a real socket."""
    proc = subprocess.Popen(
        [str(CONSOLE_SCRIPT), "ui", "--print-url"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    try:
        assert proc.stdout is not None
        url = proc.stdout.readline().strip()
        assert re.fullmatch(r"http://127\.0\.0\.1:\d+/", url), url
        with urllib.request.urlopen(url, timeout=30) as reply:
            assert reply.status == 200
            page = reply.read().decode()
        assert page == (STATIC / "index.html").read_text()
        with urllib.request.urlopen(url.rstrip("/") + built_assets(page)[0], timeout=30) as reply:
            assert reply.status == 200
        assert proc.poll() is None, "--print-url must keep serving, not print and exit"
    finally:
        proc.terminate()
        proc.wait(timeout=30)
    # uvicorn shuts down, then re-raises SIGTERM: the exit a shell expects for kill.
    assert proc.returncode == -signal.SIGTERM, proc.stderr.read() if proc.stderr else ""


def test_the_wheel_ships_the_built_page(tmp_path: Path) -> None:
    """Hatchling's `packages = ["dsj"]` picks up the non-Python files under it.

    Read off a real wheel, because that is what `uv tool install` unpacks: a page
    that is in the checkout and not in the wheel is a page no install has.
    """
    subprocess.run(
        ["uv", "build", "--wheel", "-q", "-o", str(tmp_path)],
        cwd=REPO, check=True, capture_output=True, timeout=300,
    )
    (wheel,) = tmp_path.glob("*.whl")
    names = set(zipfile.ZipFile(wheel).namelist())
    built = {
        path.relative_to(REPO).as_posix() for path in STATIC.rglob("*") if path.is_file()
    }
    assert "dsj/ui/static/index.html" in built
    assert built <= names, sorted(built - names)


def test_the_frontend_pins_every_version_exactly() -> None:
    """No `^` or `~`, TypeScript at 6.0.3, and the lockfile agreeing with both.

    6.0.3 rather than 7.x: typescript-eslint 8.70.1 accepts only `<6.1.0`
    (#57's body, correction 1).
    """
    package = json.loads((UI / "package.json").read_text())
    pins: dict[str, str] = {**package["dependencies"], **package["devDependencies"]}
    loose = {name: v for name, v in pins.items() if not re.fullmatch(r"\d+\.\d+\.\d+", v)}
    assert not loose, f"versions that are not exact: {loose}"
    assert pins["typescript"] == "6.0.3"
    locked = json.loads((UI / "package-lock.json").read_text())["packages"]
    drift = {
        name: (version, locked[f"node_modules/{name}"]["version"])
        for name, version in pins.items()
        if locked[f"node_modules/{name}"]["version"] != version
    }
    assert not drift, f"package.json and package-lock.json disagree: {drift}"
