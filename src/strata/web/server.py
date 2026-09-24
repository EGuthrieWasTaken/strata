"""`strata serve`'s process-level wiring: actor/host/token resolution,
ephemeral port selection, and running uvicorn with an inactivity watchdog
(docs/spec/11-web-ui.md §1, §7). Kept separate from `strata.cli.main` so
the resolution logic is unit-testable without going through Typer/uvicorn,
and separate from `strata.web.app` so the ASGI app itself has no knowledge
of process concerns (port binding, `webbrowser.open`, event-loop
lifecycle).
"""

from __future__ import annotations

import asyncio
import socket
from dataclasses import dataclass
from pathlib import Path

from strata.core.repo import Repo
from strata.web.security import DEFAULT_INACTIVITY_TIMEOUT_SECONDS, generate_token

LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})


class ServeConfigError(ValueError):
    pass


def is_loopback_host(host: str) -> bool:
    return host in LOOPBACK_HOSTS


def resolve_actor(repo: Repo, requested: str | None) -> str:
    """The actor `strata serve` runs as (docs/spec/11-web-ui.md §1:
    "selectable at startup when more than one actor is configured").

    `requested=None` auto-selects only when exactly one *active* (not
    `role = "inactive"`) actor is configured; otherwise the caller must
    say who they are, so a shared machine with several reviewers never
    silently screens as the wrong person.
    """
    actors = repo.config.get("actors", [])
    by_handle = {a["handle"]: a for a in actors}
    if requested is not None:
        if requested not in by_handle:
            raise ServeConfigError(f"unknown actor {requested!r}")
        return requested
    active: list[str] = [a["handle"] for a in actors if a.get("role") != "inactive"]
    if len(active) == 1:
        return active[0]
    if not active:
        raise ServeConfigError("no active actors are configured; run `strata actor add` first")
    raise ServeConfigError(
        f"multiple actors are configured ({', '.join(sorted(active))}); pass --actor <handle>"
    )


def resolve_token(host: str, requested: str | None) -> str:
    """The session token to run with, enforcing §1's "binding to any other
    interface requires --host **and** --token" (the `--host` half is
    enforced by the caller passing a non-loopback `host` here at all)."""
    if not is_loopback_host(host) and not requested:
        raise ServeConfigError(
            f"binding to {host!r} exposes this server beyond localhost and requires --token"
        )
    return requested or generate_token()


def pick_ephemeral_port(host: str) -> int:
    """An OS-assigned free port, probed and released immediately.

    A small TOCTOU race exists between this call and uvicorn's own bind
    (another process could take the port first) -- acceptable for a local
    developer tool where the failure mode is "try again," not a hardened
    service. Only used when the user did not pass `--port`.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind((host, 0))
        return int(probe.getsockname()[1])


@dataclass(frozen=True)
class ServeParams:
    repo_root: Path
    actor: str
    host: str
    port: int
    session_token: str
    inactivity_timeout: float = DEFAULT_INACTIVITY_TIMEOUT_SECONDS


def opened_url(params: ServeParams) -> str:
    return f"http://{params.host}:{params.port}/?token={params.session_token}"


async def serve_until_idle_or_interrupted(params: ServeParams) -> None:
    """Runs the ASGI app until either the process is interrupted (Ctrl-C,
    a normal `strata serve` shutdown) or §7's inactivity timeout elapses,
    whichever comes first -- unlike the plain blocking `uvicorn.run()`,
    this actually exits the process afterward rather than just having the
    security middleware start rejecting requests on a still-open port.
    """
    import uvicorn

    from strata.web.app import create_app

    app = create_app(
        repo_root=params.repo_root,
        actor=params.actor,
        session_token=params.session_token,
        host=params.host,
        port=params.port,
        inactivity_timeout=params.inactivity_timeout,
    )
    clock = app.state.strata.clock

    config = uvicorn.Config(app, host=params.host, port=params.port, log_level="warning")
    server = uvicorn.Server(config)

    async def _watchdog() -> None:
        poll_interval = min(30.0, max(1.0, params.inactivity_timeout / 10))
        while not server.should_exit:
            await asyncio.sleep(poll_interval)
            if clock.is_expired():
                server.should_exit = True

    await asyncio.gather(server.serve(), _watchdog())
