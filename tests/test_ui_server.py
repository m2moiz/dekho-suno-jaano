"""`dsj ui`: the extra it needs (#111), and the page it serves (#154).

Every test that needs the missing state makes it, by hiding the module in
sys.modules, rather than skipping when fastapi happens to be installed. A test
that only runs on the machine without the extra is a test the suite never runs.
For the same reason nothing here skips when fastapi is absent: the server tests
then fail, which is what CI's `--extra ui` is for.
"""

from __future__ import annotations

import contextlib
import itertools
import json
import re
import signal
import socket
import stat
import subprocess
import sys
import threading
import time
import urllib.request
import zipfile
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import dsj.ui.server
from dsj.cli import main
from dsj.ui import UIUnavailable
from dsj.ui.server import IDLE_S, STATIC, Heartbeat, create_app

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


# Every request a test makes as the page carries the Host the page's own does.
LOOPBACK = "http://127.0.0.1:8721"
URL = re.compile(r"http://127\.0\.0\.1:(\d+)/#t=([A-Za-z0-9_-]{43})")


def client() -> TestClient:
    """A client that is the page: the right Host, and the token on every request."""
    app, token = create_app(port=8721)
    return TestClient(
        app, base_url=LOOPBACK, headers={"Authorization": f"Bearer {token}"}
    )


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
    assert all(URL.fullmatch(url) for url in seen), seen


def test_dsj_ui_print_url_serves_the_page_on_loopback() -> None:
    """The command itself, as a process, fetched over a real socket."""
    proc = subprocess.Popen(
        [str(CONSOLE_SCRIPT), "ui", "--print-url"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    try:
        assert proc.stdout is not None
        url = proc.stdout.readline().strip()
        found = URL.fullmatch(url)
        assert found, url
        root = f"http://127.0.0.1:{found[1]}"
        # The page itself needs no token: a browser navigation cannot send one.
        with urllib.request.urlopen(url, timeout=30) as reply:
            assert reply.status == 200
            page = reply.read().decode()
        assert page == (STATIC / "index.html").read_text()
        with urllib.request.urlopen(root + built_assets(page)[0], timeout=30) as reply:
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


# --------------------------------------------------------------------------
# Only this machine may reach the server (#112)
# --------------------------------------------------------------------------
#
# The first four are the tests #112's first comment wrote out, with the Host
# pair kept together: a guard that refuses everything passes the hostile half.


def bare_client() -> tuple[TestClient, str]:
    """A client that sends only what each test gives it."""
    app, token = create_app(port=8721)
    # raise_server_exceptions=False so a 500 arrives as a response, not an
    # exception, and a guard that crashes instead of refusing cannot read as a pass.
    return TestClient(app, raise_server_exceptions=False), token


def test_a_foreign_host_header_is_rejected() -> None:
    client, token = bare_client()
    for path in ("/api/recordings", "/"):
        response = client.get(
            path, headers={"Host": "evil.example.com", "Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 403, (path, response.text)
        # The body must not leak the answer it refused to give.
        assert "recordings" not in response.text
        assert "<html" not in response.text.lower()


def test_the_loopback_host_header_is_accepted() -> None:
    """The precondition. Without it, a server that 403s everything passes the test above."""
    client, token = bare_client()
    for host in ("127.0.0.1:8721", "localhost:8721"):
        response = client.get(
            "/api/recordings", headers={"Host": host, "Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 200, (host, response.text)


@pytest.mark.parametrize("host", ["127.0.0.1", "127.0.0.1:9999", "localhost:8721.evil.com", ""])
def test_a_loopback_host_on_another_port_is_rejected(host: str) -> None:
    client, token = bare_client()
    response = client.get(
        "/api/recordings", headers={"Host": host, "Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 403, (host, response.text)


@pytest.mark.parametrize("auth", [None, "", "Bearer ", "Bearer wrong", "{token}", "Basic {token}"])
def test_no_token_is_rejected(auth: str | None) -> None:
    client, token = bare_client()
    headers = {"Host": "127.0.0.1:8721"}
    if auth is not None:
        headers["Authorization"] = auth.format(token=token)
    for path in ("/api/recordings", "/media/1"):
        response = client.get(path, headers=headers)
        assert response.status_code == 401, (path, response.text)


def test_the_host_check_runs_before_the_token_check() -> None:
    """A foreign origin with no token is told 403, never 401: it learns nothing."""
    client, _ = bare_client()
    response = client.get("/api/recordings", headers={"Host": "evil.example.com"})
    assert response.status_code == 403, response.text


def test_the_page_is_served_without_a_token() -> None:
    """A browser navigation cannot send a header, so the page itself needs none (rule 2)."""
    client, _ = bare_client()
    response = client.get("/", headers={"Host": "127.0.0.1:8721"})
    assert response.status_code == 200
    assert response.text == (STATIC / "index.html").read_text()


def test_no_cors_header_is_ever_sent() -> None:
    client, token = bare_client()
    origin = {"Host": "127.0.0.1:8721", "Origin": "https://evil.example.com"}
    replies = [
        client.get("/api/recordings", headers={**origin, "Authorization": f"Bearer {token}"}),
        client.get("/", headers=origin),
        # A preflight, the request CORS middleware exists to answer.
        client.options(
            "/api/recordings",
            headers={**origin, "Access-Control-Request-Method": "GET",
                     "Access-Control-Request-Headers": "authorization"},
        ),
    ]
    for reply in replies:
        assert not any(k.lower().startswith("access-control-") for k in reply.headers), (
            reply.request.method, dict(reply.headers),
        )


def test_no_route_takes_a_filesystem_path() -> None:
    """Rule 5: the page names a recording by id; the server looks the path up itself."""
    from fastapi.routing import APIRoute

    app, _ = create_app(port=8721)
    routes = [route for route in app.routes if isinstance(route, APIRoute)]
    assert routes, "no API routes found, so this test would check nothing"
    for route in routes:
        dependant = route.dependant
        params = [
            *dependant.path_params, *dependant.query_params, *dependant.body_params,
            *dependant.header_params, *dependant.cookie_params,
        ]
        for param in params:
            assert "path" not in param.name.lower(), (route.path, param.name)
            assert param.field_info.annotation not in (Path, str | Path), (route.path, param.name)


def test_the_heartbeat_route_counts_as_the_page_being_open() -> None:
    app, token = create_app(port=8721)
    beats = app.state.heartbeat
    beats._last -= 100  # pyright: ignore[reportPrivateUsage]  # as if a hundred seconds ago
    assert beats.idle_s() >= 100
    reply = TestClient(app, base_url=LOOPBACK).post(
        "/api/heartbeat", headers={"Authorization": f"Bearer {token}"}
    )
    assert reply.status_code == 204, reply.text
    assert beats.idle_s() < 5


def test_a_refused_request_is_not_a_heartbeat() -> None:
    app, _ = create_app(port=8721)
    beats = app.state.heartbeat
    beats._last -= 100  # pyright: ignore[reportPrivateUsage]
    TestClient(app, base_url=LOOPBACK).post("/api/heartbeat")
    assert beats.idle_s() >= 100


def test_the_server_listens_on_loopback_only(monkeypatch: pytest.MonkeyPatch) -> None:
    bound: list[tuple[str, int]] = []

    def capture(_server: object, sockets: list[socket.socket]) -> None:
        bound.extend(sock.getsockname() for sock in sockets)

    monkeypatch.setattr("uvicorn.Server.run", capture)
    dsj.ui.server.serve(open_browser=False)
    ((host, port),) = bound
    assert host == "127.0.0.1"
    assert port != 0


def test_the_server_stops_when_no_page_beats(capsys: pytest.CaptureFixture[str]) -> None:
    """Rule 6: a real server, on a real socket, with nobody at it."""
    started = time.monotonic()
    dsj.ui.server.serve(open_browser=False, idle_s=0.5)
    took = time.monotonic() - started
    assert took < 10, took
    captured = capsys.readouterr()
    assert URL.fullmatch(captured.out.strip()), captured.out
    assert "dsj ui stopped" in captured.err
    # The token goes with the server: the lock file no longer holds it.
    assert dsj.ui.server.lock_path().read_text() == ""


def wait_for_url() -> str:
    """The URL a `dsj ui` started by this test wrote into its lock file."""
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        with contextlib.suppress(OSError, ValueError):
            url = json.loads(dsj.ui.server.lock_path().read_text())["url"]
            if isinstance(url, str):
                return url
        time.sleep(0.05)
    raise AssertionError("dsj ui never wrote its URL")


def beat(url: str) -> int:
    found = URL.fullmatch(url)
    assert found
    request = urllib.request.Request(
        f"http://127.0.0.1:{found[1]}/api/heartbeat", method="POST",
        headers={"Authorization": f"Bearer {found[2]}"},
    )
    with urllib.request.urlopen(request, timeout=10) as reply:
        return reply.status


def test_a_beating_page_keeps_the_server_up_until_it_stops() -> None:
    idle = 1.0
    server = threading.Thread(
        target=dsj.ui.server.serve, kwargs={"open_browser": False, "idle_s": idle}
    )
    server.start()
    try:
        url = wait_for_url()
        until = time.monotonic() + 3 * idle
        while time.monotonic() < until:
            assert beat(url) == 204
            time.sleep(idle / 5)
        assert server.is_alive(), "the server stopped while the page was still beating"
    finally:
        server.join(timeout=10 * idle)
    assert not server.is_alive(), "the server outlived the last heartbeat"


def test_the_lock_file_is_readable_by_its_owner_only() -> None:
    server = threading.Thread(
        target=dsj.ui.server.serve, kwargs={"open_browser": False, "idle_s": 1.0}
    )
    server.start()
    try:
        wait_for_url()
        assert stat.S_IMODE(dsj.ui.server.lock_path().stat().st_mode) == 0o600
    finally:
        server.join(timeout=10)


def test_a_second_dsj_ui_prints_the_first_ones_url_and_binds_nothing(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    server = threading.Thread(
        target=dsj.ui.server.serve, kwargs={"open_browser": False, "idle_s": 2.0}
    )
    server.start()
    try:
        url = wait_for_url()

        def no_second_app(*_args: object, **_kwargs: object) -> None:
            raise AssertionError("the second dsj ui built an app")

        monkeypatch.setattr(dsj.ui.server, "create_app", no_second_app)
        opened: list[str] = []
        monkeypatch.setattr("webbrowser.open", opened.append)
        capsys.readouterr()
        assert main(["ui"]) == 0
        assert capsys.readouterr().out.strip() == url
        assert opened == [url], "the second dsj ui should open the first one's page"
    finally:
        server.join(timeout=20)


def test_a_second_dsj_ui_process_prints_the_running_url() -> None:
    """The same, as two real processes, so the lock is two processes' and not two fds'."""
    first = subprocess.Popen(
        [str(CONSOLE_SCRIPT), "ui", "--print-url"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    try:
        assert first.stdout is not None
        url = first.stdout.readline().strip()
        assert URL.fullmatch(url), url
        second = subprocess.run(
            [str(CONSOLE_SCRIPT), "ui", "--print-url"],
            capture_output=True, text=True, timeout=60, check=False,
        )
        assert second.returncode == 0, second.stderr
        assert second.stdout.strip() == url
        assert "already running" in second.stderr
        assert first.poll() is None
    finally:
        first.terminate()
        first.wait(timeout=30)


def test_a_killed_dsj_ui_does_not_lock_out_the_next() -> None:
    """flock(2) dies with its holder, so `kill -9` leaves nothing to clean up."""
    first = subprocess.Popen(
        [str(CONSOLE_SCRIPT), "ui", "--print-url"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    assert first.stdout is not None
    old = first.stdout.readline().strip()
    first.kill()
    first.wait(timeout=30)
    second = subprocess.Popen(
        [str(CONSOLE_SCRIPT), "ui", "--print-url"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    try:
        assert second.stdout is not None
        new = second.stdout.readline().strip()
        assert URL.fullmatch(new), new
        assert new != old
    finally:
        second.terminate()
        second.wait(timeout=30)


# When each request from a dsj ui tab reached the server, in seconds from the
# first, measured on 2026-10-02 (#204): headless Chromium through agent-browser,
# the tab put behind another at about 27 s and left there. Every 15 s while it was
# in front; from 105 s on, Chromium's throttling of hidden tabs held the page's
# 15 s timer to one beat a minute. With the old one-minute cutoff the server
# stopped itself 531 s after the tab was hidden, on a 60.045 s gap.
HIDDEN_TAB_BEATS = (
    0.0, 15.0, 30.342, 45.384, 60.39, 75.365, 90.381, 105.372, 138.379, 198.385,
    258.482, 318.458, 378.388, 438.313, 498.336, 558.381,
)


def test_a_tab_hidden_behind_another_does_not_let_the_server_stop() -> None:
    """Replay the measured beats on a fake clock: the server must still be up at each one."""
    now = [0.0]
    beats = Heartbeat(clock=lambda: now[0])
    for at in HIDDEN_TAB_BEATS[1:]:
        # The moment just before this beat lands is the longest the page is silent.
        now[0] = at - 1e-6
        assert beats.idle_s() < IDLE_S, f"stopped before the beat at {at} s"
        now[0] = at
        beats.beat()


def test_the_cutoff_leaves_a_whole_throttled_beat_to_spare() -> None:
    """One hidden-tab beat lost (a busy moment, a sleeping network) still must not stop it."""
    worst = max(b - a for a, b in itertools.pairwise(HIDDEN_TAB_BEATS))
    assert worst > 60  # the measurement that made the old 60 s cutoff wrong
    # Silent for two slowed beats instead of one: still half a minute short of the cutoff.
    spare = IDLE_S - 2 * worst
    assert spare >= 30
