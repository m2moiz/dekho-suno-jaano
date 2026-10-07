"""`dsj ui --tailnet`: the phone reaches dsj ui through `tailscale serve` (#250).

The server keeps its loopback bind (dsj/ui/server.py, rule 1). Tailscale's own
proxy listens on the Mac's tailnet address, port TAILNET_PORT, over HTTPS, and
passes each request to 127.0.0.1. Only the owner's own tailnet devices can
reach that address, and the per-run token is still asked of every request on
top of it (owner's ruling, 7 Oct 2026).

This module touches exactly one thing in the owner's tailnet: the 8443 entry
its own run makes, and removes. It never starts or stops Tailscale, never runs
`tailscale serve reset`, never runs `funnel`, and never replaces an entry it
did not make. Standard library only, like everything under dsj.ui but the
server, so it imports without the `ui` extra.
"""

from __future__ import annotations

__all__ = [
    "TAILNET_IDLE_S",
    "TAILNET_PORT",
    "Tailnet",
    "TailnetUnavailable",
]

import json
import shutil
import subprocess
from typing import cast

from dsj.ui import UIUnavailable

# HTTPS on 8443, not 443: an entry the owner already serves on 443 must never
# be touched (#250). If 8443 is taken too, dsj refuses rather than replace it.
TAILNET_PORT = 8443

# The idle stop with --tailnet, in seconds: 30 minutes, where the desktop's
# IDLE_S is 3. A phone puts a tab it is not showing to sleep, and a sleeping tab
# sends no heartbeat at all, so the desktop's three minutes would stop the
# server under a review paused to answer a message. Thirty minutes is the
# owner's ruling for #250, not a measurement.
TAILNET_IDLE_S = 30 * 60.0

# How long one `tailscale` command may take before dsj gives up on it. Measured
# 2026-10-07 on Tailscale 1.102.4, stopped: `/usr/bin/time -p tailscale status
# --json` and `... serve status --json`, three runs each, 0.03 to 0.41 s. The
# `serve --bg` that turns HTTPS on can stop to ask for HTTPS certificates to be
# enabled for the tailnet, and with nobody to answer it would wait for ever;
# that one was not measured, because Tailscale was stopped.
_COMMAND_S = 30.0

_NOT_RUNNING = (
    "Tailscale is not running. Start it from the menu bar, then run dsj ui --tailnet again."
)


class TailnetUnavailable(UIUnavailable):
    """`dsj ui --tailnet` cannot serve the tailnet here. Nothing was changed."""


def _object(value: object) -> dict[str, object]:
    return cast("dict[str, object]", value) if isinstance(value, dict) else {}


class Tailnet:
    """The `tailscale` command on PATH, used for exactly what --tailnet needs."""

    def __init__(self) -> None:
        """Find `tailscale`, or say it is not here.

        Raises:
            TailnetUnavailable: when no `tailscale` is on PATH.
        """
        exe = shutil.which("tailscale")
        if exe is None:
            raise TailnetUnavailable(
                "Tailscale is not installed (no `tailscale` on PATH). Install it from "
                "https://tailscale.com/download, then run dsj ui --tailnet again."
            )
        self.exe = exe
        self.name = ""

    def _run(self, *args: str) -> str:
        """Run one tailscale command, with no stdin, and return its stdout."""
        try:
            done = subprocess.run(
                [self.exe, *args], stdin=subprocess.DEVNULL, capture_output=True,
                text=True, timeout=_COMMAND_S, check=False,
            )
        except subprocess.TimeoutExpired:
            raise TailnetUnavailable(
                f"`tailscale {' '.join(args)}` did not finish in {_COMMAND_S:g} s."
            ) from None
        if done.returncode != 0:
            said = (done.stderr or done.stdout).strip().splitlines()
            raise TailnetUnavailable(
                f"`tailscale {' '.join(args)}` failed: {said[0] if said else done.returncode}"
            )
        return done.stdout

    def connect(self) -> str:
        """The Mac's tailnet name (`Self.DNSName`, no trailing dot), once Tailscale runs.

        Raises:
            TailnetUnavailable: when Tailscale is not running.
        """
        status = _object(json.loads(self._run("status", "--json")))
        name = _object(status.get("Self")).get("DNSName")
        if status.get("BackendState") != "Running" or not isinstance(name, str) or not name:
            raise TailnetUnavailable(_NOT_RUNNING)
        self.name = name.rstrip(".").lower()
        return self.name

    @property
    def host(self) -> str:
        """The `Host` a browser sends for the phone URL, which the proxy passes on.

        Tailscale's proxy sets the outgoing Host to the incoming one
        (ipn/ipnlocal/serve.go at v1.102.4: `r.Out.Host = r.In.Host`), and a
        browser names a port that is not 443 in its Host, so this is
        `<name>:8443`. Read from the source, not measured (#250).
        """
        return f"{self.name}:{TAILNET_PORT}"

    def _config(self) -> dict[str, object]:
        return _object(json.loads(self._run("serve", "status", "--json") or "null"))

    def serving(self) -> str | None:
        """What this Mac's TAILNET_PORT is serving: a proxy target, a description, or None."""
        config = self._config()
        configs = [config, *map(_object, _object(config.get("Foreground")).values())]
        for each in configs:
            web = _object(each.get("Web"))
            for key, entry in web.items():
                if key.endswith(f":{TAILNET_PORT}"):
                    proxy = _object(_object(_object(entry).get("Handlers")).get("/")).get("Proxy")
                    return proxy if isinstance(proxy, str) else f"a {key} entry"
            if str(TAILNET_PORT) in _object(each.get("TCP")):
                return f"a TCP entry on port {TAILNET_PORT}"
        return None

    def refuse_if_taken(self) -> None:
        """Before binding: refuse when TAILNET_PORT already serves anything.

        Raises:
            TailnetUnavailable: when it does, naming what it serves.
        """
        if (taken := self.serving()) is not None:
            raise TailnetUnavailable(
                f"port {TAILNET_PORT} of this Mac's tailnet address already serves {taken}, "
                f"and dsj will not replace it. Remove it yourself if it is no longer "
                f"needed (`tailscale serve --https={TAILNET_PORT} off`), then run "
                f"dsj ui --tailnet again."
            )

    def open(self, port: int) -> None:
        """Serve https://<name>:8443 from http://127.0.0.1:`port`, in the background.

        After refuse_if_taken(), and after the socket is bound, so the proxy
        never points at a port nobody holds.

        Raises:
            TailnetUnavailable: when tailscale fails.
        """
        self._run("serve", "--bg", f"--https={TAILNET_PORT}", f"http://127.0.0.1:{port}")

    def close(self, port: int) -> bool:
        """Remove the 8443 entry if, and only if, it still points at 127.0.0.1:`port`.

        Returns whether it removed one. An entry pointing anywhere else is not
        this run's, and is left as it is.
        """
        if self.serving() != f"http://127.0.0.1:{port}":
            return False
        self._run("serve", f"--https={TAILNET_PORT}", "off")
        return True
