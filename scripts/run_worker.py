"""Run one worker and open its own dashboard in this computer's browser.

Opening the worker's /dashboard does not submit work or provide remote desktop
access. Use --no-open-dashboard for headless operation; existing Uvicorn factory
commands remain supported.
"""

import argparse
from ipaddress import ip_address
import re
import sys
from threading import Thread
import webbrowser

import uvicorn


def _host(value: str) -> str:
    if value == "localhost":
        return value
    try:
        if len(value) > 45 or "%" in value:
            raise ValueError
        return str(ip_address(value))
    except ValueError:
        raise argparse.ArgumentTypeError("Host must be localhost or a literal IPv4/IPv6 address.") from None


def _port(value: str) -> int:
    if not re.fullmatch(r"[0-9]{1,5}", value) or not 1 <= int(value) <= 65535:
        raise argparse.ArgumentTypeError("Port must be an integer from 1 to 65535.")
    return int(value)


def _dashboard_url(host: str, port: int) -> str:
    """Use this worker's listener; wildcard binds open through local loopback."""
    host = {"0.0.0.0": "127.0.0.1", "::": "::1"}.get(host, host)
    authority = f"[{host}]" if ":" in host else host
    return f"http://{authority}:{port}/dashboard"


def _browser_fallback(url: str) -> None:
    print(f"Dashboard could not open automatically. Open this URL in a browser: {url}",
          file=sys.stderr, flush=True)


def _open_dashboard(url: str) -> None:
    try:
        opened = webbrowser.open_new_tab(url)
    except Exception:
        opened = False
    if not opened:
        _browser_fallback(url)


class WorkerServer(uvicorn.Server):
    """Open once after Uvicorn's lifespan and socket startup both succeed."""

    def __init__(self, config: uvicorn.Config, dashboard_url: str | None = None):
        super().__init__(config)
        self.dashboard_url = dashboard_url
        self._dashboard_attempted = False

    async def startup(self, sockets=None):
        # The pinned Uvicorn sets started only after application startup and
        # listener creation. Startup failures must never launch a browser.
        await super().startup(sockets=sockets)
        if not self.started or self.should_exit or self.dashboard_url is None or self._dashboard_attempted:
            return
        self._dashboard_attempted = True
        print(f"Worker dashboard: {self.dashboard_url}", flush=True)
        try:
            # Desktop browser discovery can block on some systems. It must not
            # delay API responsiveness or prevent a headless server from exiting.
            Thread(target=_open_dashboard, args=(self.dashboard_url,),
                   name="worker-dashboard", daemon=True).start()
        except Exception:
            _browser_fallback(self.dashboard_url)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("role", choices=("hydro", "flood", "dam"))
    parser.add_argument("--host", type=_host, default="127.0.0.1")
    parser.add_argument("--port", type=_port, help="Default: Hydro 8002; Flood 8003; Dam 8004.")
    parser.add_argument("--no-open-dashboard", action="store_true",
                        help="Run headless without opening this worker's dashboard in a browser.")
    args = parser.parse_args(argv)
    port = args.port or {"hydro": 8002, "flood": 8003, "dam": 8004}[args.role]
    url = None if args.no_open_dashboard else _dashboard_url(args.host, port)
    config = uvicorn.Config(
        f"backend.workers.{args.role}.main:create_app", factory=True,
        host=args.host, port=port,
        workers=1, reload=False,
    )
    server = WorkerServer(config, dashboard_url=url)
    server.run()
    return 0 if server.started else 1


if __name__ == "__main__":
    raise SystemExit(main())
