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
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, cast

import pytest
import segno
from fastapi.testclient import TestClient

import dsj.ui.server
from dsj.cli import main
from dsj.ui.server import IDLE_S, create_app
from dsj.ui.tailnet import TAILNET_IDLE_S, TAILNET_PORTS

CONSOLE_SCRIPT = Path(sys.executable).parent / "dsj"

NAME = "mac.tail0000.ts.net"
PHONE_URL = re.compile(rf"https://{re.escape(NAME)}:8443/#t=([A-Za-z0-9_-]{{43}})")
ANY_PHONE_URL = re.compile(rf"https://{re.escape(NAME)}:(\d+)/#t=([A-Za-z0-9_-]{{43}})")

FAKE = """\
#!{python}
import json, os, sys, time
path = os.environ["FAKE_TAILSCALE_STATE"]
with open(path) as f:
    state = json.load(f)
argv = sys.argv[1:]
state["calls"].append(argv)
out = None
code = 0
port = next((a.removeprefix("--https=") for a in argv if a.startswith("--https=")), "")
web_key = state["dns"].rstrip(".") + ":" + port
if argv == ["status", "--json"]:
    out = {{"BackendState": state["backend"], "Self": {{"DNSName": state["dns"]}}}}
elif argv == ["serve", "status", "--json"]:
    out = state["serve"]
elif len(argv) == 4 and argv[:2] == ["serve", "--bg"] and argv[2].startswith("--https="):
    serve = state["serve"] or {{}}
    serve.setdefault("TCP", {{}})[port] = {{"HTTPS": True}}
    serve.setdefault("Web", {{}})[web_key] = {{"Handlers": {{"/": {{"Proxy": argv[3]}}}}}}
    state["serve"] = serve
    with open(path, "w") as f:
        json.dump(state, f)
    # The entry is in place; a slow command keeps dsj waiting after it.
    time.sleep(state["bg_sleep"])
elif argv[2:] == ["off"] and state["off_fails"]:
    print("fake tailscale: off failed", file=sys.stderr)
    code = 1
elif len(argv) == 3 and argv[0] == "serve" and argv[1].startswith("--https=") and argv[2] == "off":
    serve = state["serve"] or {{}}
    serve.get("TCP", {{}}).pop(port, None)
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
        self.write(
            backend="Running", dns=f"{NAME}.", serve=None, calls=[], off_fails=False,
            bg_sleep=0,
        )

    def read(self) -> dict[str, Any]:
        return json.loads(self.state.read_text())

    def write(self, **changes: object) -> None:
        state = self.read() if self.state.exists() else {}
        state.update(changes)
        self.state.write_text(json.dumps(state))

    @property
    def calls(self) -> list[list[str]]:
        return self.read()["calls"]

    def proxy(self, https: int = 8443) -> str | None:
        """Where this Mac's entry on port `https` points, or None when there is none."""
        serve: dict[str, Any] = self.read()["serve"] or {}
        web: dict[str, Any] = serve.get("Web", {})
        entry: dict[str, Any] | None = web.get(f"{NAME}:{https}")
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


def off(https: int) -> list[str]:
    return ["serve", f"--https={https}", "off"]


def serve_on(port: int, https: int = 8443) -> list[str]:
    return ["serve", "--bg", f"--https={https}", f"http://127.0.0.1:{port}"]


def entry(target: str) -> dict[str, Any]:
    return {"Handlers": {"/": {"Proxy": target}}}


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


def test_8443_taken_goes_to_the_next_port_and_leaves_8443_alone(
    tailscale: FakeTailscale, monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The owner's Mac serves 8443 to another live service (R5): it must stay as it is."""
    theirs = {
        "TCP": {"443": {"HTTPS": True}, "8443": {"HTTPS": True}},
        "Web": {
            f"{NAME}:443": entry("http://127.0.0.1:4243"),
            f"{NAME}:8443": entry("http://127.0.0.1:8787"),
        },
    }
    tailscale.write(serve=theirs)
    seen: dict[str, object] = {}

    def serving(_server: object, sockets: list[socket.socket]) -> None:
        port = sockets[0].getsockname()[1]
        seen.update(port=port, ours=tailscale.proxy(8444))

    monkeypatch.setattr("uvicorn.Server.run", serving)
    assert main(["ui", "--tailnet", "--print-url"]) == 0
    port = seen["port"]
    assert isinstance(port, int)
    assert seen["ours"] == f"http://127.0.0.1:{port}"
    found = ANY_PHONE_URL.fullmatch(capsys.readouterr().out.strip())
    assert found
    assert found[1] == "8444"
    # Only its own entry went; 443 and 8443 are exactly as they were.
    assert tailscale.read()["serve"] == theirs
    assert tailscale.calls == [
        STATUS, SERVE_STATUS, serve_on(port, 8444), SERVE_STATUS, off(8444), SERVE_STATUS,
    ]


def test_every_port_taken_is_refused_naming_each_and_left_alone(
    tailscale: FakeTailscale, monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert TAILNET_PORTS == (8443, 8444, 8445, 10000)
    theirs = {
        "TCP": {str(p): {"HTTPS": True} for p in TAILNET_PORTS},
        "Web": {f"{NAME}:{p}": entry(f"http://127.0.0.1:{p + 1}") for p in TAILNET_PORTS},
    }
    tailscale.write(serve=theirs)
    monkeypatch.setattr("uvicorn.Server.run", no_serving)
    assert main(["ui", "--tailnet", "--print-url"]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    for p in TAILNET_PORTS:
        assert f"{p}: http://127.0.0.1:{p + 1}" in captured.err, captured.err
    assert len(captured.err.strip().splitlines()) == 1, captured.err
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
    # The off, then a read to confirm the entry is gone.
    assert tailscale.calls == [
        STATUS, SERVE_STATUS, serve_on(port), SERVE_STATUS, OFF, SERVE_STATUS,
    ]
    assert dsj.ui.server.lock_path().read_text() == ""


def test_the_entry_is_removed_when_the_server_raises(
    tailscale: FakeTailscale, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("the server broke")

    monkeypatch.setattr("uvicorn.Server.run", broken)
    with pytest.raises(RuntimeError, match="the server broke"):
        dsj.ui.server.serve(open_browser=False, tailnet=True)
    assert tailscale.proxy() is None
    assert tailscale.calls[-2:] == [OFF, SERVE_STATUS]


def test_the_entry_is_removed_on_the_idle_stop(
    tailscale: FakeTailscale, capsys: pytest.CaptureFixture[str]
) -> None:
    """A real server on a real socket, stopped by the watchdog with no page open."""
    dsj.ui.server.serve(open_browser=False, tailnet=True, idle_s=0.5)
    assert "dsj ui stopped" in capsys.readouterr().err
    assert tailscale.proxy() is None
    assert tailscale.calls[-2:] == [OFF, SERVE_STATUS]


@pytest.mark.parametrize("sig", [signal.SIGTERM, signal.SIGINT, signal.SIGHUP])
def test_the_entry_is_removed_when_the_process_is_signalled(
    sig: signal.Signals, tailscale: FakeTailscale
) -> None:
    """As a process, because a signal is where a `finally` is not enough.

    uvicorn re-raises SIGTERM after its shutdown, which kills the process
    before any `finally` in serve() runs, so the removal has to happen inside
    uvicorn's own shutdown. SIGHUP is what closing the Terminal window sends,
    and uvicorn does not handle it at all. Each still ends the process by its
    own signal, so the shell sees 143, 130 or 129.
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
        # Once uvicorn answers; the window before it has its own test below.
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
    assert tailscale.calls[-2:] == [OFF, SERVE_STATUS]
    assert proc.returncode == -sig
    assert dsj.ui.server.lock_path().read_text() == ""


@pytest.mark.parametrize("sig", [signal.SIGTERM, signal.SIGHUP])
def test_a_signal_before_uvicorn_starts_still_removes_the_entry(
    sig: signal.Signals, tailscale: FakeTailscale
) -> None:
    """The entry exists from `tailscale serve --bg` on; uvicorn's handlers come later.

    The fake holds `serve --bg` open for a while after writing the entry, so the
    signal lands while dsj waits on it: the narrowest point of that window.
    """
    tailscale.write(bg_sleep=20)
    proc = subprocess.Popen(
        [str(CONSOLE_SCRIPT), "ui", "--tailnet", "--print-url"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    try:
        deadline = time.monotonic() + 30
        while tailscale.proxy() is None:
            assert time.monotonic() < deadline, "dsj never made its entry"
            assert proc.poll() is None, proc.stderr.read() if proc.stderr else ""
            time.sleep(0.05)
        proc.send_signal(sig)
        proc.wait(timeout=30)
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()
    assert tailscale.proxy() is None, proc.stderr.read() if proc.stderr else ""
    assert proc.returncode == -sig
    assert dsj.ui.server.lock_path().read_text() == ""


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
    # The recorded entry first, confirmed gone, then the run's own start.
    assert tailscale.calls[:6] == [
        SERVE_STATUS, OFF, SERVE_STATUS, STATUS, SERVE_STATUS, serve_on(port),
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
    assert main(["ui", "--tailnet", "--print-url"]) == 0
    assert tailscale.read()["serve"] == theirs
    assert OFF not in tailscale.calls
    assert off(8444) in tailscale.calls, "it should have served, and cleaned up, 8444"
    # Its entry is gone (replaced by someone else's), so the record is dropped.
    assert dsj.ui.server.lock_path().read_text() == ""


def write_killed_run(port: int = 5555, https: int = 8443) -> None:
    """The lock file a `--tailnet` run killed with -9 leaves, and its live entry."""
    dsj.ui.server.lock_path().parent.mkdir(parents=True, exist_ok=True)
    dsj.ui.server.lock_path().write_text(json.dumps({
        "url": f"http://127.0.0.1:{port}/#t=x", "port": port, "pid": dead_pid(),
        "tailnet": {"host": NAME, "port": https, "url": f"https://{NAME}:{https}/#t=x"},
    }))


def recorded() -> list[Any]:
    """The un-removed entries the lock file still records."""
    text = dsj.ui.server.lock_path().read_text()
    return json.loads(text).get("stale", []) if text else []


def dead_entry(port: int = 5555, https: int = 8443) -> dict[str, Any]:
    return {
        "TCP": {str(https): {"HTTPS": True}},
        "Web": {f"{NAME}:{https}": entry(f"http://127.0.0.1:{port}")},
    }


def test_a_plain_dsj_ui_removes_a_killed_runs_entry(
    tailscale: FakeTailscale, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Probe P2: a plain run used to overwrite the record and lose the entry for ever."""
    write_killed_run()
    tailscale.write(serve=dead_entry())
    monkeypatch.setattr("uvicorn.Server.run", no_serving)
    assert main(["ui", "--print-url"]) == 0
    assert tailscale.proxy() is None
    assert tailscale.calls == [SERVE_STATUS, OFF, SERVE_STATUS]
    assert dsj.ui.server.lock_path().read_text() == ""


def test_the_record_outlives_runs_that_cannot_remove_the_entry(
    tailscale: FakeTailscale, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Probe P3: a plain run with no tailscale, then a refused --tailnet, keep the record."""
    write_killed_run()
    tailscale.write(serve=dead_entry())
    monkeypatch.setattr("uvicorn.Server.run", no_serving)
    # A plain run on a PATH with no tailscale: it serves, and keeps the record.
    monkeypatch.setenv("PATH", str(tailscale.bin.parent))
    assert main(["ui", "--print-url"]) == 0
    assert recorded() == [{"port": 5555, "https": 8443}]
    # Tailscale stopped, and its off failing: refused, record kept, entry untouched.
    monkeypatch.setenv("PATH", str(tailscale.bin))
    tailscale.write(backend="Stopped", off_fails=True)
    assert main(["ui", "--tailnet", "--print-url"]) == 1
    assert recorded() == [{"port": 5555, "https": 8443}]
    assert tailscale.proxy() == "http://127.0.0.1:5555"
    # Tailscale back: the next --tailnet start removes it, then serves.
    tailscale.write(backend="Running", off_fails=False)
    assert main(["ui", "--tailnet", "--print-url"]) == 0
    assert tailscale.proxy() is None
    assert dsj.ui.server.lock_path().read_text() == ""


def test_a_failed_removal_at_stop_is_recorded_and_retried(
    tailscale: FakeTailscale, monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    ports: list[int] = []

    def serving(_server: object, sockets: list[socket.socket]) -> None:
        ports.append(sockets[0].getsockname()[1])
        tailscale.write(off_fails=True)

    monkeypatch.setattr("uvicorn.Server.run", serving)
    assert main(["ui", "--tailnet", "--print-url"]) == 0
    (port,) = ports
    assert "could not remove" in capsys.readouterr().err
    assert tailscale.proxy() == f"http://127.0.0.1:{port}"
    assert recorded() == [{"port": port, "https": 8443}]
    tailscale.write(off_fails=False)
    monkeypatch.setattr("uvicorn.Server.run", no_serving)
    assert main(["ui", "--print-url"]) == 0
    assert tailscale.proxy() is None
    assert dsj.ui.server.lock_path().read_text() == ""


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


def test_a_tailnet_server_lets_the_phone_host_in_and_only_it(
    tailscale: FakeTailscale,
) -> None:
    """Through serve() itself, not create_app(): the Host it was built with is the one used."""
    tailscale.write(serve={
        "TCP": {"8443": {"HTTPS": True}},
        "Web": {f"{NAME}:8443": entry("http://127.0.0.1:8787")},
    })
    server = threading.Thread(
        target=dsj.ui.server.serve,
        kwargs={"open_browser": False, "idle_s": 3.0, "tailnet": True},
    )
    server.start()
    try:
        holder = wait_for_holder()
        port, token = re.findall(r"http://127\.0\.0\.1:(\d+)/#t=(.+)", holder["url"])[0]

        def get(host: str, auth: bool) -> int:
            request = urllib.request.Request(
                f"http://127.0.0.1:{port}/api/recordings",
                headers={"Host": host, **({"Authorization": f"Bearer {token}"} if auth else {})},
            )
            try:
                with urllib.request.urlopen(request, timeout=10) as reply:
                    return reply.status
            except urllib.error.HTTPError as refused:
                return refused.code

        assert holder["tailnet"]["port"] == 8444
        assert get(f"{NAME}:8444", auth=True) == 200
        assert get(f"{NAME}:8444", auth=False) == 401
        assert get(f"{NAME}:8443", auth=True) == 403
        assert get(NAME, auth=True) == 403
    finally:
        server.join(timeout=30)


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


# --------------------------------------------------------------------------
# A goodbye does not stop a --tailnet run (R5)
# --------------------------------------------------------------------------


def post(url: str, path: str, page: str) -> int:
    """POST `path` to the loopback server `url` names, as page `page`."""
    port, token = re.findall(r"http://127\.0\.0\.1:(\d+)/#t=(.+)", url)[0]
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}", method="POST",
        headers={"Authorization": f"Bearer {token}", "X-Dsj-Page": page},
    )
    with urllib.request.urlopen(request, timeout=10) as reply:
        return reply.status


@pytest.mark.parametrize("tailnet", [False, True])
def test_a_goodbye_stops_a_plain_run_and_not_a_tailnet_one(
    tailnet: bool, tailscale: FakeTailscale, capsys: pytest.CaptureFixture[str]
) -> None:
    """With --tailnet only the idle stop may end the server.

    A phone says goodbye on `pagehide` when the owner switches apps or locks
    the screen, not only when the tab closes.
    """
    idle, bye = 6.0, 0.5
    server = threading.Thread(
        target=dsj.ui.server.serve,
        kwargs={"open_browser": False, "idle_s": idle, "bye_s": bye, "tailnet": tailnet},
    )
    server.start()
    try:
        url = wait_for_holder()["url"]
        assert post(url, "/api/heartbeat", "phone") == 204
        said = time.monotonic()
        assert post(url, "/api/bye", "phone") == 204
        server.join(timeout=bye + 3)
        stopped_by_bye = not server.is_alive()
    finally:
        server.join(timeout=idle + 30)
    took = time.monotonic() - said
    assert not server.is_alive()
    err = capsys.readouterr().err
    if tailnet:
        assert not stopped_by_bye, "a goodbye stopped the --tailnet server"
        assert took >= idle - 1, took
        assert f"No dsj page has been open for {idle:g} s" in err
        assert tailscale.proxy() is None
    else:
        assert stopped_by_bye, "a goodbye no longer stops a plain dsj ui"
        assert "The dsj page was closed" in err
