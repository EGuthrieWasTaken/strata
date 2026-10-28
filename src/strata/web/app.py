"""The `strata serve` FastAPI application: openspec:web-ui.

`create_app` is the one entry point `strata.cli.main`'s `serve` command
(and every test in this package) uses. It is a factory, not a module-level
singleton, because the server's identity -- which repository, which actor,
which session token, which host/port it was told it is bound to -- is only
known once, at `strata serve` invocation time, and tests need a fresh,
isolated instance per repository fixture.
"""

from __future__ import annotations

import importlib.resources
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.base import BaseHTTPMiddleware

from strata.core.repo import Repo, open_repo
from strata.web.security import (
    CSRF_FIELD_NAME,
    DEFAULT_INACTIVITY_TIMEOUT_SECONDS,
    MUTATING_METHODS,
    SESSION_COOKIE_NAME,
    InactivityClock,
    PublicUrl,
    allowed_hosts,
    is_host_allowed,
    is_origin_allowed,
)

_CSP = (
    "default-src 'self'; "
    "script-src 'self'; "
    "style-src 'self'; "
    "img-src 'self'; "
    "connect-src 'self'; "
    "form-action 'self'; "
    "frame-ancestors 'none'"
)


def _templates_dir() -> str:
    return str(importlib.resources.files("strata.web") / "templates")


def _static_dir() -> str:
    return str(importlib.resources.files("strata.web") / "static")


class AppState:
    """Everything a request handler needs beyond the ASGI request itself.

    Deliberately not the repository's own mutable state -- `repo` is
    re-opened fresh per handler call (`strata.core.repo.open_repo`'s own
    contract: every read reflects the current working tree, matching "the
    server is stateless with respect to the repository," openspec:web-ui#strictly-local), but the
    *server's* identity (which token, which actor, which host it was told
    to bind to) is fixed for the process's lifetime.
    """

    def __init__(
        self,
        *,
        repo_root: Path,
        actor: str,
        session_token: str,
        host: str,
        port: int,
        inactivity_timeout: float = DEFAULT_INACTIVITY_TIMEOUT_SECONDS,
        public_url: PublicUrl | None = None,
    ) -> None:
        self.repo_root = repo_root
        self.actor = actor
        self.session_token = session_token
        self.host = host
        self.port = port
        self.public_url = public_url
        self.allowed_hosts = allowed_hosts(host, port, public_url)
        self.clock = InactivityClock(inactivity_timeout)

    def open_repo(self) -> Repo:
        return open_repo(self.repo_root)


def _health_response(state: AppState) -> JSONResponse:
    try:
        state.open_repo()
    except Exception:  # noqa: BLE001 - any failure to read the repository is "not healthy"
        return JSONResponse({"status": "unavailable"}, status_code=503)
    return JSONResponse({"status": "ok"})


def create_app(
    *,
    repo_root: Path,
    actor: str,
    session_token: str,
    host: str = "127.0.0.1",
    port: int = 8000,
    inactivity_timeout: float = DEFAULT_INACTIVITY_TIMEOUT_SECONDS,
    public_url: PublicUrl | None = None,
) -> FastAPI:
    state = AppState(
        repo_root=repo_root,
        actor=actor,
        session_token=session_token,
        host=host,
        port=port,
        inactivity_timeout=inactivity_timeout,
        public_url=public_url,
    )

    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    app.state.strata = state
    app.state.templates = Jinja2Templates(directory=_templates_dir())
    app.state.templates.env.globals["csrf_field_name"] = CSRF_FIELD_NAME
    # The page header's "signed in as": the server's own actor, so a page whose context carries
    # no `actor` (the criteria pages) or one that means something else (the history filter) is
    # right too.
    app.state.templates.env.globals["signed_in_actor"] = actor

    class SecurityMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request: Request, call_next: Any) -> Any:
            s: AppState = request.app.state.strata

            # openspec:web-ui#health-endpoint: a liveness probe needs no session and no matching
            # Host (an orchestrator calls the container by whatever address it has), and it must
            # not count as activity or it would keep an idle server alive forever. It reveals
            # only whether the repository can be read.
            if request.url.path == "/healthz" and request.method in ("GET", "HEAD"):
                return _health_response(s)

            if not is_host_allowed(request.headers.get("host"), s.allowed_hosts):
                return PlainTextResponse("invalid Host header", status_code=400)
            if not is_origin_allowed(request.headers.get("origin"), s.host, s.port, s.public_url):
                return PlainTextResponse("invalid Origin header", status_code=400)

            if s.clock.is_expired():
                return PlainTextResponse(
                    "session expired after inactivity; restart `strata serve`",
                    status_code=503,
                )

            # Every request needs the session (stricter than openspec:web-ui#localhost-security's
            # letter,
            # which only requires it on mutating requests -- deliberately:
            # nothing about "local" should mean another process or browser
            # tab can read repository content without the token too).
            cookie_token = request.cookies.get(SESSION_COOKIE_NAME)
            authenticated = cookie_token == s.session_token
            if not authenticated and request.query_params.get("token") == s.session_token:
                authenticated = True
            if not authenticated:
                return PlainTextResponse("missing or invalid session", status_code=403)

            if request.method in MUTATING_METHODS:
                form_token = None
                if "form" in request.headers.get("content-type", ""):
                    # Read the form here, once, and stash it on `request.state`
                    # (backed by `scope["state"]`, shared across every Request
                    # wrapper built from this same ASGI scope) for the route
                    # handler to reuse -- `BaseHTTPMiddleware` gives the
                    # downstream app its own `Request` instance, which cannot
                    # re-read a body this middleware already consumed.
                    form = await request.form()
                    request.state.form = form
                    form_token = form.get(CSRF_FIELD_NAME)
                if form_token != s.session_token:
                    return PlainTextResponse("missing or invalid CSRF token", status_code=403)

            s.clock.touch()
            response = await call_next(request)

            if cookie_token != s.session_token:
                response.set_cookie(
                    SESSION_COOKIE_NAME,
                    s.session_token,
                    httponly=True,
                    samesite="strict",
                    path="/",
                )
            # A route may set a stricter policy of its own (the generated plots, which carry an
            # inline stylesheet for light and dark mode).
            response.headers.setdefault("Content-Security-Policy", _CSP)
            response.headers["X-Content-Type-Options"] = "nosniff"
            response.headers["X-Frame-Options"] = "DENY"
            response.headers["Referrer-Policy"] = "no-referrer"
            return response

    app.add_middleware(SecurityMiddleware)

    app.mount("/static", StaticFiles(directory=_static_dir()), name="static")

    from strata.web.analysis_routes import router as analysis_router
    from strata.web.extraction_routes import router as extraction_router
    from strata.web.report_routes import router as report_router
    from strata.web.routes import router

    app.include_router(router)
    app.include_router(extraction_router)
    app.include_router(analysis_router)
    app.include_router(report_router)

    return app
