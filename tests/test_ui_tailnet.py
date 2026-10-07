"""`dsj ui --tailnet`: the phone reaches dsj ui through `tailscale serve` (#250).

Every test here runs a fake `tailscale`, a small script put first and alone on
PATH, never the real one: the real one changes the owner's tailnet. The fake
keeps its state (backend, the Mac's name, the serve config) in a JSON file and
records every command it was given, and it fails on any command it does not
know, so a `tailscale up`, `down`, `serve reset` or `funnel` from dsj would
fail the test that caused it rather than reach anything.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import re
import signal
import socket
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path
from typing import Any, cast

import pytest
import segno
from fastapi.testclient import TestClient

import dsj.ui.server
from dsj.cli import main
from dsj.ui.server import IDLE_S, create_app
from dsj.ui.tailnet import TAILNET_IDLE_S, TAILNET_PORT

CONSOLE_SCRIPT = Path(sys.executable).parent / "dsj"

NAME = "mac.tail0000.ts.net"
PHONE_URL = re.compile(rf"https://{re.escape(NAME)}:8443/#t=([A-Za-z0-9_-]{{43}})")

FAKE = """\
#!{python}
import json, os, sys
path = os.environ["FAKE_TAILSCALE_STATE"]
with open(path) as f:
    state = json.load(f)
argv = sys.argv[1:]
state["calls"].append(argv)
out = None
code = 0
web_key = state["dns"].rstrip(".") + ":8443"
if argv == ["status", "--json"]:
    out = {{"BackendState": state["backend"], "Self": {{"DNSName": state["dns"]}}}}
elif argv == ["serve", "status", "--json"]:
    out = state["serve"]
elif len(argv) == 4 and argv[:3] == ["serve", "--bg", "--https=8443"]:
    serve = state["serve"] or {{}}
    serve.setdefault("TCP", {{}})["8443"] = {{"HTTPS": True}}
    serve.setdefault("Web", {{}})[web_key] = {{"Handlers": {{"/": {{"Proxy": argv[3]}}}}}}
    state["serve"] = serve
elif argv == ["serve", "--https=8443", "off"]:
    serve = state["serve"] or {{}}
    serve.get("TCP", {{}}).pop("8443", None)
    serve.get("Web", {{}}).pop(web_key, None)
    state["serve"] = serve
else:
    print("fake tailscale: unexpected command", argv, file=sys.stderr)
    code = 2
with open(path, "w") as f:
    json.dump(state, f)
if out is not None or argv[-1:] == ["--json"]:
    print(json.dumps(out))
sys.exit(code)
"""


class FakeTailscale:
    """The fake's state file, read and written by the test as well as the fake."""

    def __init__(self, root: Path) -> None:
        self.bin = root / "bin"
        self.bin.mkdir()
        self.state = root / "tailscale.json"
        exe = self.bin / "tailscale"
        exe.write_text(FAKE.format(python=sys.executable))
        exe.chmod(0o755)
        self.write(backend="Running", dns=f"{NAME}.", serve=None, calls=[])

    def read(self) -> dict[str, Any]:
        return json.loads(self.state.read_text())

    def write(self, **changes: object) -> None:
        state = self.read() if self.state.exists() else {}
        state.update(changes)
        self.state.write_text(json.dumps(state))

    @property
    def calls(self) -> list[list[str]]:
        return self.read()["calls"]

    def proxy(self) -> str | None:
        """Where this Mac's 8443 entry points, or None when there is none."""
        serve: dict[str, Any] = self.read()["serve"] or {}
        web: dict[str, Any] = serve.get("Web", {})
        entry: dict[str, Any] | None = web.get(f"{NAME}:8443")
        return entry["Handlers"]["/"]["Proxy"] if entry else None


@pytest.fixture
def tailscale(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> FakeTailscale:
    fake = FakeTailscale(tmp_path)
    # Alone on PATH: the real /usr/local/bin/tailscale must be unreachable.
    monkeypatch.setenv("PATH", str(fake.bin))
    monkeypatch.setenv("FAKE_TAILSCALE_STATE", str(fake.state))
    return fake


def no_serving(*_args: object, **_kwargs: object) -> None:
    """Stands in for uvicorn.Server.run, so `dsj ui --tailnet` returns at once."""


STATUS = ["status", "--json"]
SERVE_STATUS = ["serve", "status", "--json"]
OFF = ["serve", "--https=8443", "off"]


def serve_on(port: int) -> list[str]:
    return ["serve", "--bg", "--https=8443", f"http://127.0.0.1:{port}"]


def dead_pid() -> int:
    """The pid of a process that has already exited."""
    proc = subprocess.Popen([sys.executable, "-c", "pass"])
    proc.wait()
    return proc.pid


# --------------------------------------------------------------------------
# Refusals: nothing is bound, nothing in the tailnet changes
# --------------------------------------------------------------------------


def test_tailscale_not_installed_is_one_line_and_exit_1(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    monkeypatch.setenv("PATH", str(empty))
    monkeypatch.setattr("uvicorn.Server.run", no_serving)
    assert main(["ui", "--tailnet", "--print-url"]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "tailscale is not installed" in captured.err.lower()
    assert len(captured.err.strip().splitlines()) == 1, captured.err


def test_tailscale_stopped_says_what_to_do_and_starts_nothing(
    tailscale: FakeTailscale, monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    tailscale.write(backend="Stopped")
    monkeypatch.setattr("uvicorn.Server.run", no_serving)
    assert main(["ui", "--tailnet", "--print-url"]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert (
        "Tailscale is not running. Start it from the menu bar, "
        "then run dsj ui --tailnet again."
    ) in captured.err
    assert tailscale.calls == [STATUS], "only the status may be read; never `tailscale up`"


def test_8443_served_by_something_else_is_refused_and_left_alone(
    tailscale: FakeTailscale, monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    theirs = {
        "TCP": {"443": {"HTTPS": True}, "8443": {"HTTPS": True}},
        "Web": {
            f"{NAME}:443": {"Handlers": {"/": {"Proxy": "http://127.0.0.1:4243"}}},
            f"{NAME}:8443": {"Handlers": {"/": {"Proxy": "http://127.0.0.1:8787"}}},
        },
    }
    tailscale.write(serve=theirs)
    monkeypatch.setattr("uvicorn.Server.run", no_serving)
    assert main(["ui", "--tailnet", "--print-url"]) == 1
    err = capsys.readouterr().err
    assert "8443" in err
    assert "http://127.0.0.1:8787" in err
    assert tailscale.read()["serve"] == theirs, "someone else's serve entry was changed"
    assert tailscale.calls == [STATUS, SERVE_STATUS]


# --------------------------------------------------------------------------
# A run: the entry is made after the bind, and removed however it ends
# --------------------------------------------------------------------------


def test_a_tailnet_run_serves_8443_prints_the_phone_url_and_cleans_up(
    tailscale: FakeTailscale, monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    seen: dict[str, object] = {}

    def serving(_server: object, sockets: list[socket.socket]) -> None:
        ((host, port),) = [sock.getsockname() for sock in sockets]
        seen.update(host=host, port=port, proxy=tailscale.proxy())

    monkeypatch.setattr("uvicorn.Server.run", serving)
    opened: list[str] = []
    monkeypatch.setattr("webbrowser.open", opened.append)
    assert main(["ui", "--tailnet", "--print-url"]) == 0
    port = seen["port"]
    assert isinstance(port, int)
    # Still the loopback bind; the tailnet reaches it only through the proxy.
    assert seen["host"] == "127.0.0.1"
    assert seen["proxy"] == f"http://127.0.0.1:{port}", "the entry must exist while serving"
    captured = capsys.readouterr()
    found = PHONE_URL.fullmatch(captured.out.strip())
    assert found, captured.out
    # The QR of that same URL, on stderr, where a person reads it.
    qr = io.StringIO()
    segno.make(captured.out.strip()).terminal(out=qr, compact=True)
    assert qr.getvalue() in captured.err
    assert opened == []
    assert tailscale.proxy() is None, "the 8443 entry outlived the server"
    assert tailscale.calls == [STATUS, SERVE_STATUS, serve_on(port), SERVE_STATUS, OFF]


def test_the_entry_is_removed_when_the_server_raises(
    tailscale: FakeTailscale, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("the server broke")

    monkeypatch.setattr("uvicorn.Server.run", broken)
    with pytest.raises(RuntimeError, match="the server broke"):
        dsj.ui.server.serve(open_browser=False, tailnet=True)
    assert tailscale.proxy() is None
    assert tailscale.calls[-1] == OFF


def test_the_entry_is_removed_on_the_idle_stop(
    tailscale: FakeTailscale, capsys: pytest.CaptureFixture[str]
) -> None:
    """A real server on a real socket, stopped by the watchdog with no page open."""
    dsj.ui.server.serve(open_browser=False, tailnet=True, idle_s=0.5)
    assert "dsj ui stopped" in capsys.readouterr().err
    assert tailscale.proxy() is None
    assert tailscale.calls[-1] == OFF


@pytest.mark.parametrize("sig", [signal.SIGTERM, signal.SIGINT])
def test_the_entry_is_removed_when_the_process_is_signalled(
    sig: signal.Signals, tailscale: FakeTailscale
) -> None:
    """As a process, because a signal is where a `finally` is not enough.

    uvicorn re-raises SIGTERM after its shutdown, which kills the process
    before any `finally` in serve() runs, so the removal has to happen inside
    uvicorn's own shutdown.
    """
    proc = subprocess.Popen(
        [str(CONSOLE_SCRIPT), "ui", "--tailnet", "--print-url"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    try:
        assert proc.stdout is not None
        url = proc.stdout.readline().strip()
        assert PHONE_URL.fullmatch(url), url
        assert tailscale.proxy() is not None
        # Once uvicorn answers, so its signal handlers are in place. A SIGTERM
        # before that ends the process outright, and the next run's stale-entry
        # check is what removes the entry then.
        loopback = wait_for_holder()["url"]
        with urllib.request.urlopen(loopback, timeout=30) as reply:
            assert reply.status == 200
        proc.send_signal(sig)
        proc.wait(timeout=30)
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()
    assert tailscale.proxy() is None, proc.stderr.read() if proc.stderr else ""
    assert tailscale.calls[-1] == OFF


def test_a_stale_entry_from_a_dead_run_is_removed_first(
    tailscale: FakeTailscale, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A `kill -9` runs no cleanup: the lock file still names the run and its port."""
    dsj.ui.server.lock_path().parent.mkdir(parents=True, exist_ok=True)
    dsj.ui.server.lock_path().write_text(json.dumps({
        "url": "http://127.0.0.1:5555/#t=x", "port": 5555, "pid": dead_pid(),
        "tailnet": {"host": NAME, "port": 8443, "url": f"https://{NAME}:8443/#t=x"},
    }))
    tailscale.write(serve={
        "TCP": {"8443": {"HTTPS": True}},
        "Web": {f"{NAME}:8443": {"Handlers": {"/": {"Proxy": "http://127.0.0.1:5555"}}}},
    })
    ports: list[int] = []

    def serving(_server: object, sockets: list[socket.socket]) -> None:
        ports.append(sockets[0].getsockname()[1])

    monkeypatch.setattr("uvicorn.Server.run", serving)
    assert main(["ui", "--tailnet", "--print-url"]) == 0
    (port,) = ports
    assert tailscale.calls[:5] == [
        STATUS, SERVE_STATUS, OFF, SERVE_STATUS, serve_on(port),
    ]


def test_a_stale_lock_does_not_license_removing_an_entry_it_did_not_make(
    tailscale: FakeTailscale, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The dead run's port is 5555; the entry points at 8787, so it is someone else's."""
    dsj.ui.server.lock_path().parent.mkdir(parents=True, exist_ok=True)
    dsj.ui.server.lock_path().write_text(json.dumps({
        "url": "http://127.0.0.1:5555/#t=x", "port": 5555, "pid": dead_pid(),
        "tailnet": {"host": NAME, "port": 8443, "url": f"https://{NAME}:8443/#t=x"},
    }))
    theirs = {
        "TCP": {"8443": {"HTTPS": True}},
        "Web": {f"{NAME}:8443": {"Handlers": {"/": {"Proxy": "http://127.0.0.1:8787"}}}},
    }
    tailscale.write(serve=theirs)
    monkeypatch.setattr("uvicorn.Server.run", no_serving)
    assert main(["ui", "--tailnet", "--print-url"]) == 1
    assert tailscale.read()["serve"] == theirs
    assert OFF not in tailscale.calls


# --------------------------------------------------------------------------
# A second dsj ui
# --------------------------------------------------------------------------


def wait_for_holder() -> dict[str, Any]:
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        with contextlib.suppress(OSError, ValueError):
            holder: Any = json.loads(dsj.ui.server.lock_path().read_text())
            if isinstance(holder, dict) and "url" in holder:
                return cast("dict[str, Any]", holder)
        time.sleep(0.05)
    raise AssertionError("dsj ui never wrote its lock file")


def settle(capsys: pytest.CaptureFixture[str], url: str) -> None:
    """Wait for the server thread to print `url`, and swallow what it printed.

    The lock file is written just before the URL is printed, so a test that
    read the lock file and then the captured output could catch it between.
    """
    seen = ""
    deadline = time.monotonic() + 30
    while url not in seen:
        assert time.monotonic() < deadline, "the server never printed its URL"
        seen += capsys.readouterr().out
        time.sleep(0.05)


def test_tailnet_against_a_running_plain_dsj_ui_refuses(
    tailscale: FakeTailscale, capsys: pytest.CaptureFixture[str]
) -> None:
    server = threading.Thread(
        target=dsj.ui.server.serve, kwargs={"open_browser": False, "idle_s": 2.0}
    )
    server.start()
    try:
        settle(capsys, wait_for_holder()["url"])
        assert main(["ui", "--tailnet", "--print-url"]) == 1
        captured = capsys.readouterr()
        assert captured.out == "", "the loopback URL must not be printed as if it were the phone's"
        assert "dsj ui is already running without --tailnet; stop it first" in captured.err
        assert tailscale.calls == []
    finally:
        server.join(timeout=20)


def test_tailnet_against_a_running_tailnet_run_prints_its_phone_url(
    tailscale: FakeTailscale, capsys: pytest.CaptureFixture[str]
) -> None:
    server = threading.Thread(
        target=dsj.ui.server.serve,
        kwargs={"open_browser": False, "idle_s": 2.0, "tailnet": True},
    )
    server.start()
    try:
        holder = wait_for_holder()
        settle(capsys, holder["tailnet"]["url"])
        assert main(["ui", "--tailnet", "--print-url"]) == 0
        out = capsys.readouterr().out.strip()
        assert PHONE_URL.fullmatch(out), out
        assert out == holder["tailnet"]["url"]
        # A plain `dsj ui` beside it still gets the loopback address.
        assert main(["ui", "--print-url"]) == 0
        assert capsys.readouterr().out.strip() == holder["url"]
    finally:
        server.join(timeout=20)
    assert tailscale.proxy() is None


# --------------------------------------------------------------------------
# The Host check and the idle stop
# --------------------------------------------------------------------------


def test_with_the_tailnet_name_allowed_only_that_name_and_loopback_get_in() -> None:
    app, token = create_app(port=8721, extra_hosts=(f"{NAME}:8443",))
    client = TestClient(app, raise_server_exceptions=False)
    auth = {"Authorization": f"Bearer {token}"}
    for host in (f"{NAME}:8443", f"{NAME.upper()}:8443", "127.0.0.1:8721"):
        reply = client.get("/api/recordings", headers={"Host": host, **auth})
        assert reply.status_code == 200, (host, reply.text)
    for host in (
        "other.tail0000.ts.net:8443", NAME, f"{NAME}:443", f"{NAME}.evil.com:8443",
        "127.0.0.1:8443",
    ):
        reply = client.get("/api/recordings", headers={"Host": host, **auth})
        assert reply.status_code == 403, (host, reply.text)
    # The tailnet name does not lift the token check.
    reply = client.get("/api/recordings", headers={"Host": f"{NAME}:8443"})
    assert reply.status_code == 401


def test_a_plain_app_refuses_the_tailnet_name() -> None:
    app, token = create_app(port=8721)
    client = TestClient(app, raise_server_exceptions=False)
    reply = client.get(
        "/api/recordings",
        headers={"Host": f"{NAME}:8443", "Authorization": f"Bearer {token}"},
    )
    assert reply.status_code == 403


def test_tailnet_waits_thirty_minutes_and_the_desktop_three(
    tailscale: FakeTailscale, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert TAILNET_PORT == 8443
    assert TAILNET_IDLE_S == 30 * 60
    assert IDLE_S == 180
    used: list[float] = []

    def watch(_server: object, _beats: object, idle_s: float, *_rest: object) -> None:
        used.append(idle_s)

    monkeypatch.setattr(dsj.ui.server, "_watch", watch)
    monkeypatch.setattr("uvicorn.Server.run", no_serving)
    assert main(["ui", "--print-url"]) == 0
    assert main(["ui", "--tailnet", "--print-url"]) == 0
    assert used == [IDLE_S, TAILNET_IDLE_S]
    assert os.environ["PATH"] == str(tailscale.bin)
