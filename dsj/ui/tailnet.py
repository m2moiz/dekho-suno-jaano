"""`dsj ui --tailnet`: the phone reaches dsj ui through `tailscale serve` (#250).

The server keeps its loopback bind (dsj/ui/server.py, rule 1). Tailscale's own
proxy listens on the Mac's tailnet address, on the first free port of
TAILNET_PORTS, over HTTPS, and
passes each request to 127.0.0.1. Only the owner's own tailnet devices can
reach that address, and the per-run token is still asked of every request on
top of it (owner's ruling, 7 Oct 2026).

This module touches exactly one thing in the owner's tailnet: the one entry
its own run makes, and removes. It never starts or stops Tailscale, never runs
`tailscale serve reset`, never runs `funnel`, and never replaces an entry it
did not make. Standard library only, like everything under dsj.ui but the
server, so it imports without the `ui` extra.
"""

from __future__ import annotations

__all__ = [
    "TAILNET_IDLE_S",
    "TAILNET_PORTS",
    "Tailnet",
    "TailnetUnavailable",
]

import json
import shutil
import subprocess
from typing import cast

from dsj.ui import UIUnavailable

# The HTTPS ports a run may take, first free wins; never 443, which the owner
# already serves (#250). The owner's Mac also serves 8443 to another live
# service, which must stay as it is (ruling R5, 7 Oct 2026), hence a list. A
# port serving anything is skipped, never replaced; all taken, dsj refuses.
# Serve itself accepts any port: the 443, 8443 and 10000 limit is Funnel's
# alone (`ipn.CheckFunnelPort` in ipn/serve.go, called only from
# cmd/tailscale/cli/funnel.go, Tailscale v1.102.4); `srvTypeAndPortFromFlags`
# in cmd/tailscale/cli/serve_v2.go checks only that the port fits in 16 bits.
TAILNET_PORTS = (8443, 8444, 8445, 10000)

# The idle stop with --tailnet, in seconds: 30 minutes, where the desktop's
# IDLE_S is 180 s, three minutes. A phone puts a tab it is not showing to sleep, and a sleeping tab
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

# Running, with no name for this Mac on the tailnet: MagicDNS gives it one, and
# the phone's URL is that name (Task 15b review, Minor 4).
_NO_NAME = (
    "Tailscale is running, but this Mac has no tailnet name, so MagicDNS is off. Turn on "
    "MagicDNS and HTTPS certificates in the Tailscale admin console's DNS page, then run "
    "dsj ui --tailnet again."
)


class TailnetUnavailable(UIUnavailable):
    """`dsj ui --tailnet` cannot serve the tailnet here. Nothing was changed."""


def _text(output: bytes | str | None) -> str:
    """A stream a timed-out command left: bytes in practice, whatever `text` says."""
    if output is None:
        return ""
    return output.decode(errors="replace") if isinstance(output, bytes) else output


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
        # The HTTPS port this run serves on, once choose_port() picks it.
        self.port = TAILNET_PORTS[0]

    def _run(self, *args: str) -> str:
        """Run one tailscale command, with no stdin, and return its stdout."""
        try:
            done = subprocess.run(
                [self.exe, *args], stdin=subprocess.DEVNULL, capture_output=True,
                text=True, timeout=_COMMAND_S, check=False,
            )
        except subprocess.TimeoutExpired as exc:
            # What it printed while it waited: `serve --bg` with HTTPS
            # certificates off is expected to print the URL that turns them on
            # (read from tailscale's source, not observed), and the owner needs
            # it (Task 15b review, Minor 3). Both streams, since which one it
            # uses is unobserved (Task 16a review, I1).
            said = " ".join(f"{_text(exc.stdout)} {_text(exc.stderr)}".split())
            raise TailnetUnavailable(
                f"`tailscale {' '.join(args)}` did not finish in {_COMMAND_S:g} s."
                + (f" Tailscale said: {said}" if said else "")
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
        status = _object(self._json("status", "--json"))
        name = _object(status.get("Self")).get("DNSName")
        if status.get("BackendState") != "Running":
            raise TailnetUnavailable(_NOT_RUNNING)
        if not isinstance(name, str) or not name:
            raise TailnetUnavailable(_NO_NAME)
        self.name = name.rstrip(".").lower()
        return self.name

    @property
    def host(self) -> str:
        """The `Host` a browser sends for the phone URL, which the proxy passes on.

        Tailscale's proxy sets the outgoing Host to the incoming one
        (ipn/ipnlocal/serve.go at v1.102.4: `r.Out.Host = r.In.Host`), and a
        browser names a port that is not 443 in its Host, so this is
        `<name>:<port>`. Read from the source, not measured (#250).
        """
        return f"{self.name}:{self.port}"

    def _json(self, *args: str) -> object:
        out = self._run(*args)
        try:
            return json.loads(out or "null")
        except ValueError:
            raise TailnetUnavailable(
                f"`tailscale {' '.join(args)}` did not print JSON: {out[:80]!r}"
            ) from None

    def _config(self) -> dict[str, object]:
        return _object(self._json("serve", "status", "--json"))

    @staticmethod
    def _serving(config: dict[str, object], https: int) -> str | None:
        """What `config` serves on port `https`: a proxy target, a description, or None."""
        configs = [config, *map(_object, _object(config.get("Foreground")).values())]
        for each in configs:
            web = _object(each.get("Web"))
            for key, entry in web.items():
                if key.endswith(f":{https}"):
                    proxy = _object(_object(_object(entry).get("Handlers")).get("/")).get("Proxy")
                    return proxy if isinstance(proxy, str) else f"a {key} entry"
            if str(https) in _object(each.get("TCP")):
                return f"a TCP entry on port {https}"
        return None

    def choose_port(self) -> int:
        """Before binding: take the first of TAILNET_PORTS that serves nothing.

        Raises:
            TailnetUnavailable: when every one serves something, naming each.
        """
        config = self._config()
        taken: list[str] = []
        for https in TAILNET_PORTS:
            what = self._serving(config, https)
            if what is None:
                self.port = https
                return https
            taken.append(f"{https}: {what}")
        raise TailnetUnavailable(
            f"every port dsj ui --tailnet may use on this Mac's tailnet address already "
            f"serves something ({'; '.join(taken)}), and dsj will not replace any of them. "
            f"Free one (`tailscale serve --https=<port> off`) if it is no longer needed, "
            f"then run dsj ui --tailnet again."
        )

    def open(self, port: int) -> None:
        """Serve https://<name>:<self.port> from http://127.0.0.1:`port`, in the background.

        After choose_port(), and after the socket is bound, so the proxy never
        points at a port nobody holds.

        Raises:
            TailnetUnavailable: when tailscale fails.
        """
        self._run("serve", "--bg", f"--https={self.port}", f"http://127.0.0.1:{port}")

    def remove(self, port: int, https: int) -> str:
        """Remove the entry on `https` if, and only if, it points at 127.0.0.1:`port`.

        Returns "absent" when no such entry is there (none, or someone else's,
        which is left as it is), "removed" when the off command took it and a
        second read confirms it is gone, and "left" when it is still there
        after the off. Only "left" means the entry may still be dsj's.

        Raises:
            TailnetUnavailable: when a tailscale command fails.
        """
        target = f"http://127.0.0.1:{port}"
        if self._serving(self._config(), https) != target:
            return "absent"
        self._run("serve", f"--https={https}", "off")
        return "left" if self._serving(self._config(), https) == target else "removed"
