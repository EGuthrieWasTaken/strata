"""The `strata serve` FastAPI application: openspec:web-ui.

`create_app` is the one entry point `strata.cli.main`'s `serve` command
(and every test in this package) uses. It is a factory, not a module-level
singleton, because the server's identity -- which repository, which actor,
which session token, which host/port it was told it is bound to -- is only
known once, at `strata serve` invocation time, and tests need a fresh,
isolated instance per repository fixture.
"""

from __future__ import annotations

import copy
import importlib.resources
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException
from starlette.middleware.base import BaseHTTPMiddleware

from strata.core.repo import LockTimeoutError, Repo, open_repo, repo_lock
from strata.core.screen_batches import flush_pending_screening
from strata.web import uploads
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
        max_upload_bytes: int = uploads.DEFAULT_MAX_UPLOAD_MB * uploads.MIB,
    ) -> None:
        self.repo_root = repo_root
        self.actor = actor
        self.session_token = session_token
        self.host = host
        self.port = port
        self.public_url = public_url
        self.allowed_hosts = allowed_hosts(host, port, public_url)
        self.clock = InactivityClock(inactivity_timeout)
        self.max_upload_bytes = max_upload_bytes
        self.staging = uploads.UploadStaging(repo_root, max_total_bytes=max_upload_bytes)

    #: Set only inside a hosted instance (openspec:hosted-deployment): who is signed in, in which
    #: project, with what role. `None` in `strata serve`, which has no accounts.
    hosted: HostedView | None = None

    def open_repo(self) -> Repo:
        return open_repo(self.repo_root)

    def for_request(self, *, actor: str, session_token: str, hosted: HostedView) -> AppState:
        """This state as one hosted request sees it: the member's actor, their session's CSRF
        token (what the forms embed), and the hosted context. The shared parts (the repository
        root, the upload staging area) are the same objects."""
        view = copy.copy(self)
        view.actor = actor
        view.session_token = session_token
        view.hosted = hosted
        return view


@dataclass(frozen=True)
class HostedView:
    """What a hosted instance adds to a request inside one of its projects."""

    project_id: str
    project_title: str
    username: str
    display_name: str
    role: str
    #: The session's CSRF token, for the forms the header carries (signing out).
    csrf: str = ""
    #: The URL prefix of the instance's own pages (the sign-out form, the project list).
    instance_root: str = ""
    #: The project's sync status for the page header and dashboard (`strata.hosted.syncloop`).
    sync: dict[str, Any] = field(default_factory=dict)


#: The screens that record screening decisions. A request to one is how a decision is made, so it
#: does not first commit the decisions already waiting.
SCREENING_ROOTS = ("screen", "rescreen")


def needs_screening_flush(path: str, form: Any) -> bool:
    """Whether a mutating request should first commit every reviewer's pending screening decisions.

    Every one except the screens that make them, and a preview (which writes nothing, so it commits
    nothing). Committing them first, as batches of their own, keeps them out of whatever the request
    goes on to commit (`strata.core.screen_batches`).
    """
    if path.strip("/").split("/", 1)[0] in SCREENING_ROOTS:
        return False
    return form is None or form.get("intent") != "preview"


def flush_screening_for_request(state: AppState) -> None:
    """Commit the pending screening batches in `state`'s repository, under the repository lock.

    If another process holds the lock for long, skip: whatever commits next flushes them itself,
    under the lock it holds.
    """
    repo = state.open_repo()
    try:
        with repo_lock(repo):
            flush_pending_screening(repo)
    except LockTimeoutError:
        return


#: Where a hosted instance puts a request's own `AppState` in the ASGI scope's `state`.
REQUEST_STATE_KEY = "strata_request_state"


def state_of(request: Request) -> AppState:
    """The `AppState` a request handler works with: the hosted instance's per-request view when
    there is one, else the server's own."""
    scoped = (request.scope.get("state") or {}).get(REQUEST_STATE_KEY)
    if scoped is not None:
        state: AppState = scoped
        return state
    server_state: AppState = request.app.state.strata
    return server_state


def _template_context(request: Request) -> dict[str, Any]:
    """Values every page needs that depend on the request: who is signed in, the URL prefix
    every link starts with (empty in `strata serve`; `/p/<project>` on a hosted instance), and
    the hosted context, if any."""
    scoped = (request.scope.get("state") or {}).get(REQUEST_STATE_KEY)
    server = getattr(request.app.state, "strata", None)
    state = scoped if scoped is not None else server
    return {
        "root": request.scope.get("root_path", ""),
        "signed_in_actor": state.actor if state is not None else "",
        "hosted": state.hosted if state is not None else None,
    }


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
    max_upload_bytes: int = uploads.DEFAULT_MAX_UPLOAD_MB * uploads.MIB,
) -> FastAPI:
    state = AppState(
        repo_root=repo_root,
        actor=actor,
        session_token=session_token,
        host=host,
        port=port,
        inactivity_timeout=inactivity_timeout,
        public_url=public_url,
        max_upload_bytes=max_upload_bytes,
    )
    # Whatever an earlier server left staged is gone: nobody can come back to it.
    state.staging.purge(everything=True)

    app = create_project_app()
    app.state.strata = state

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

            form = None
            if request.method in MUTATING_METHODS:
                form_token = None
                content_type = request.headers.get("content-type", "")
                if "form" in content_type:
                    # The size is checked from the declared length *before* the body is read
                    # (openspec:web-uploads#upload-limits), and only after the session, Host and
                    # Origin checks above (openspec:web-uploads#security-checks-come-first).
                    try:
                        uploads.check_declared_length(
                            request.headers, content_type, max_upload_bytes=s.max_upload_bytes
                        )
                    except uploads.UploadRefused as refusal:
                        return PlainTextResponse(refusal.message, status_code=refusal.status_code)
                    # Read the form here, once, and stash it on `request.state`
                    # (backed by `scope["state"]`, shared across every Request
                    # wrapper built from this same ASGI scope) for the route
                    # handler to reuse -- `BaseHTTPMiddleware` gives the
                    # downstream app its own `Request` instance, which cannot
                    # re-read a body this middleware already consumed.
                    try:
                        form = await request.form(
                            max_files=uploads.MAX_FILES_PER_REQUEST,
                            max_fields=uploads.MAX_FIELDS_PER_REQUEST,
                            max_part_size=uploads.MAX_FIELD_BYTES,
                        )
                    except HTTPException as exc:
                        return PlainTextResponse(str(exc.detail), status_code=exc.status_code)
                    request.state.form = form
                    form_token = form.get(CSRF_FIELD_NAME)
                if form_token != s.session_token:
                    if form is not None:
                        await form.close()
                    return PlainTextResponse("missing or invalid CSRF token", status_code=403)

            # Pending screening decisions are committed, as batches of their own, before anything
            # else commits, so they never ride along in someone else's commit. A hosted instance
            # does this itself, per member, before it dispatches to the project
            # (`strata.web.hosted`).
            if (
                request.method in MUTATING_METHODS
                and state_of(request).hosted is None
                and needs_screening_flush(request.url.path, form)
            ):
                await run_in_threadpool(flush_screening_for_request, s)

            s.clock.touch()
            try:
                response = await call_next(request)
            finally:
                if form is not None:
                    await form.close()

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
            # `same-origin`, not `no-referrer`: under `no-referrer` a browser sends `Origin: null`
            # on *every* form post, same-origin ones included (Fetch: "append a request `Origin`
            # header"), and the Origin check above then refuses all of the interface's own forms.
            # `same-origin` sends the real Origin to this server and no referrer to anyone else.
            response.headers["Referrer-Policy"] = "same-origin"
            return response

    app.add_middleware(SecurityMiddleware)
    return app


def create_project_app() -> FastAPI:
    """The review's screens with no server identity and no security middleware of their own.

    `create_app` wraps this for `strata serve`; a hosted instance wraps it once and supplies, per
    request, the signed-in member's state (`REQUEST_STATE_KEY`) after its own checks
    (openspec:hosted-deployment). Every link a page renders starts with the request's
    `root_path`, so the same screens work under a hosted project's URL prefix.
    """
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    app.state.templates = Jinja2Templates(
        directory=_templates_dir(), context_processors=[_template_context]
    )
    app.state.templates.env.globals["csrf_field_name"] = CSRF_FIELD_NAME

    app.mount("/static", StaticFiles(directory=_static_dir()), name="static")

    from strata.web.analysis_routes import router as analysis_router
    from strata.web.extraction_routes import router as extraction_router
    from strata.web.report_routes import router as report_router
    from strata.web.retrieval_routes import router as retrieval_router
    from strata.web.routes import router
    from strata.web.search_routes import router as search_router
    from strata.web.study_routes import router as study_router
    from strata.web.suggestion_routes import router as suggestion_router
    from strata.web.workflow_routes import router as workflow_router

    app.include_router(router)
    app.include_router(extraction_router)
    app.include_router(analysis_router)
    app.include_router(report_router)
    app.include_router(search_router)
    app.include_router(workflow_router)
    app.include_router(retrieval_router)
    app.include_router(study_router)
    app.include_router(suggestion_router)

    return app
