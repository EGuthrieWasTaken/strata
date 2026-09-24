"""The `strata serve` FastAPI application: docs/spec/11-web-ui.md.

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
from fastapi.responses import PlainTextResponse
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
    server is stateless with respect to the repository," §1), but the
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
    ) -> None:
        self.repo_root = repo_root
        self.actor = actor
        self.session_token = session_token
        self.host = host
        self.port = port
        self.allowed_hosts = allowed_hosts(host, port)
        self.clock = InactivityClock(inactivity_timeout)

    def open_repo(self) -> Repo:
        return open_repo(self.repo_root)


def create_app(
    *,
    repo_root: Path,
    actor: str,
    session_token: str,
    host: str = "127.0.0.1",
    port: int = 8000,
    inactivity_timeout: float = DEFAULT_INACTIVITY_TIMEOUT_SECONDS,
) -> FastAPI:
    state = AppState(
        repo_root=repo_root,
        actor=actor,
        session_token=session_token,
        host=host,
        port=port,
        inactivity_timeout=inactivity_timeout,
    )

    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    app.state.strata = state
    app.state.templates = Jinja2Templates(directory=_templates_dir())
    app.state.templates.env.globals["csrf_field_name"] = CSRF_FIELD_NAME

    class SecurityMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request: Request, call_next: Any) -> Any:
            s: AppState = request.app.state.strata

            if not is_host_allowed(request.headers.get("host"), s.allowed_hosts):
                return PlainTextResponse("invalid Host header", status_code=400)
            if not is_origin_allowed(request.headers.get("origin"), s.host, s.port):
                return PlainTextResponse("invalid Origin header", status_code=400)

            if s.clock.is_expired():
                return PlainTextResponse(
                    "session expired after inactivity; restart `strata serve`",
                    status_code=503,
                )

            # Every request needs the session (stricter than §7's letter,
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
            response.headers["Content-Security-Policy"] = _CSP
            response.headers["X-Content-Type-Options"] = "nosniff"
            response.headers["X-Frame-Options"] = "DENY"
            response.headers["Referrer-Policy"] = "no-referrer"
            return response

    app.add_middleware(SecurityMiddleware)

    app.mount("/static", StaticFiles(directory=_static_dir()), name="static")

    from strata.web.routes import router

    app.include_router(router)

    return app
