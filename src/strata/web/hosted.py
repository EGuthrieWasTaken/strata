"""`strata host`'s web application: openspec:hosted-deployment.

One process serves every project of an instance to every member. The review's own screens are
the ones `strata serve` has (`strata.web.app.create_project_app`, one instance shared by all
projects), mounted under `/p/<project-id>/`; what this module adds is everything a shared,
always-on server needs and a local one does not:

- **Who is asking.** Sign-in with a local account (`/signin`), an invitation (`/invite/<token>`)
  or a configured provider (`/auth/<provider>/...`), then a server-side session carried by a
  `Secure`, `HttpOnly`, `SameSite=Strict` cookie
  (openspec:hosted-deployment#per-user-authentication).
- **What they may see and do.** A request inside a project needs a membership in it, which gives
  the actor every write is attributed to and a role checked against the request before any screen
  sees it (`strata.hosted.members`). A non-member is told there is no such project, whatever the
  URL (openspec:hosted-deployment#isolation-between-projects).
- **The security baseline.** HTTPS only (a plain-HTTP request is redirected or refused unless the
  instance was started for local testing), `Host` and `Origin` checked against the public URL,
  CSRF tokens on every mutating form, a size check before an upload is read, and no inactivity
  exit (openspec:hosted-deployment#hosted-security-baseline).
- **Attribution.** Each request's git commands run with the member's actor as author and the
  instance as committer (openspec:hosted-deployment#commit-attribution).
- **The sync loop.** A page that reads a project pulls first when the last fetch is stale; a
  request that committed marks the project for pushing; screening decisions are counted into
  per-actor batches (`strata.hosted.syncloop`). `/p/<id>/-/sync` shows the status and, to leads,
  the conflicts to resolve.
- **Remote MCP.** `/p/<id>/mcp` serves the read-only MCP tools over MCP's streamable HTTP
  transport to a client with an API token (openspec:hosted-deployment#remote-mcp-access).

No domain logic lives here: accounts, memberships, blinding and the sync loop are
`strata.hosted` and `strata.protocol`, and the screens are the same ones the local server runs.
"""

from __future__ import annotations

import contextlib
import hashlib
import hmac
import re
import time
from collections.abc import AsyncIterator, Callable
from typing import Any
from urllib.parse import parse_qs, quote, urlsplit

import anyio
from starlette.applications import Starlette
from starlette.datastructures import FormData, Headers, MutableHeaders
from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import JSONResponse, PlainTextResponse, RedirectResponse, Response
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles
from starlette.templating import Jinja2Templates
from starlette.types import Message, Receive, Scope, Send

from strata import gitio
from strata.core.repo import RepoNotFoundError
from strata.core.screen_batches import batch_identities
from strata.core.sync import Edited
from strata.hosted import accounts
from strata.hosted import members as members_mod
from strata.hosted.instance import Instance, OidcProvider, Project
from strata.hosted.oidc import OidcClient, OidcError, link_identity, user_for_identity
from strata.hosted.secrets import random_token
from strata.hosted.syncloop import SyncLoop, SyncWorker, identity_for
from strata.web import uploads
from strata.web.app import (
    _CSP,
    REQUEST_STATE_KEY,
    AppState,
    HostedView,
    _static_dir,
    _templates_dir,
    create_project_app,
    needs_screening_flush,
)
from strata.web.security import CSRF_FIELD_NAME, MUTATING_METHODS, PublicUrl, cookie_name

_HSTS = "max-age=31536000"
#: The review's own screens and the MCP endpoint, which check a body's size themselves (an
#: upload may be large; MCP has its own limit).
_PROJECT_SCREENS = re.compile(r"^/p/[^/]+/(?!-/)")
_OIDC_STATE_COOKIE = "strata_oidc_state"
_SCREENING_PATHS = ("screen", "rescreen")


class HostedConfigError(ValueError):
    pass


def _client_of(scope: Scope) -> str:
    client = scope.get("client")
    return str(client[0]) if client else "unknown"


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _safe_next(raw: str | None) -> str:
    """A same-site path to go to after signing in; anything else becomes `/`."""
    if not raw or not raw.startswith("/") or raw.startswith("//") or "\\" in raw:
        return "/"
    parts = urlsplit(raw)
    return raw if not parts.scheme and not parts.netloc else "/"


class HostedServer:
    """The state of one running hosted instance."""

    def __init__(
        self,
        instance: Instance,
        *,
        public_url: PublicUrl,
        allow_plain_http: bool = False,
        background: bool = True,
        oidc_http: Any = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        instance.require_initialised()
        if public_url.scheme != "https" and not allow_plain_http:
            raise HostedConfigError(
                "a hosted instance needs an https:// public URL (TLS is normally terminated by a "
                "reverse proxy in front of it); start it with --insecure-local-testing only to "
                "try it on your own machine"
            )
        self.instance = instance
        self.public_url = public_url
        self.allow_plain_http = allow_plain_http
        self.clock = clock
        self.oidc_http = oidc_http
        self.background = background
        self.worker: SyncWorker | None = None
        self.sync = SyncLoop(instance, clock=clock, on_change=self._wake)
        if background:
            self.worker = SyncWorker(self.sync)
        self.project_app = create_project_app()
        self.templates = Jinja2Templates(directory=_templates_dir())
        self.templates.env.globals["csrf_field_name"] = CSRF_FIELD_NAME
        self._states: dict[str, AppState] = {}
        self._oidc: dict[str, OidcClient] = {}
        # A project added by an older version, or whose config was changed by hand, still runs
        # only the instance's hooks (see `strata.hosted.instance`).
        for project in instance.list_projects():
            instance.secure_project(project.id)

    # -- small helpers ---------------------------------------------------------------------

    @property
    def secure(self) -> bool:
        return self.public_url.scheme == "https"

    def _cookie(self, base: str, *, host_only: bool = True) -> str:
        """`base` for this instance. Cookies are shared by every port of a host name, so an
        instance on a port of its own (and a `strata serve` beside it) gets names of its own;
        on the scheme's default port the name is bare, as it always was. `__Host-` makes the
        browser refuse the cookie unless it is Secure, host-only and `/`."""
        name = cookie_name(base, self.public_url.port)
        return f"__Host-{name}" if self.secure and host_only else name

    @property
    def session_cookie(self) -> str:
        return self._cookie("strata_session")

    @property
    def signin_cookie(self) -> str:
        return self._cookie("strata_signin")

    @property
    def oidc_state_cookie(self) -> str:
        # Scoped to `/auth/`, which `__Host-` does not allow.
        return self._cookie(_OIDC_STATE_COOKIE, host_only=False)

    def _wake(self) -> None:
        if self.worker is not None:
            self.worker.wake()

    def render(
        self, request: Request, name: str, context: dict[str, Any], *, status_code: int = 200
    ) -> Response:
        response: Response = self.templates.TemplateResponse(
            request, name, context, status_code=status_code
        )
        return response

    def message(self, request: Request, heading: str, text: str, status_code: int) -> Response:
        return self.render(
            request,
            "hosted/message.html",
            {"heading": heading, "message": text, "user": None, "csrf": ""},
            status_code=status_code,
        )

    def set_cookie(self, response: Response, name: str, value: str, *, max_age: int) -> None:
        response.set_cookie(
            name,
            value,
            max_age=max_age,
            path="/",
            secure=self.secure,
            httponly=True,
            samesite="strict",
        )

    def current(self, request: Request) -> tuple[accounts.Session, accounts.User] | None:
        """The signed-in session and account, if the request carries a live session."""
        settings = self.instance.settings
        session = accounts.session_for(
            self.instance.store,
            request.cookies.get(self.session_cookie),
            idle_minutes=settings.session_idle_minutes,
            now=self.clock(),
        )
        if session is None:
            return None
        user = accounts.get_user(self.instance.store, session.username)
        if user is None or user.disabled:
            return None
        return session, user

    def start_session(self, response: Response, username: str) -> None:
        hours = self.instance.settings.session_hours
        token, _session = accounts.create_session(
            self.instance.store, username, hours=hours, now=self.clock()
        )
        self.set_cookie(response, self.session_cookie, token, max_age=int(hours * 3600))
        response.delete_cookie(self.signin_cookie, path="/")

    def project_state(self, project: Project) -> AppState:
        state = self._states.get(project.id)
        if state is None:
            state = AppState(
                repo_root=self.instance.project_dir(project.id),
                actor="",
                session_token="",
                host=self.public_url.hostname,
                port=self.public_url.port or (443 if self.secure else 80),
                # openspec:hosted-deployment#hosted-security-baseline: no inactivity exit.
                inactivity_timeout=float("inf"),
                public_url=self.public_url,
                max_upload_bytes=self.instance.settings.max_upload_mb * uploads.MIB,
            )
            state.staging.purge(everything=True)
            self._states[project.id] = state
        return state

    def oidc(self, provider: OidcProvider) -> OidcClient:
        client = self._oidc.get(provider.id)
        if client is None:
            redirect = f"{self.public_url.origin}/auth/{quote(provider.id, safe='')}/callback"
            client = OidcClient(
                self.instance, provider, redirect_uri=redirect, http=self.oidc_http,
                clock=self.clock,
            )  # fmt: skip
            self._oidc[provider.id] = client
        return client

    def provider(self, provider_id: str) -> OidcProvider | None:
        return next((p for p in self.instance.settings.oidc if p.id == provider_id), None)

    def hosted_view(
        self,
        project: Project,
        session: accounts.Session,
        user: accounts.User,
        membership: members_mod.Membership,
    ) -> HostedView:
        return HostedView(
            project_id=project.id,
            project_title=project.title,
            username=user.username,
            display_name=user.display_name,
            role=membership.role,
            csrf=session.csrf,
            instance_root="",
            sync=self.sync.status(project.id).as_view(),
        )


# ------------------------------------------------------------------------------ the gate


class _Gate:
    """Checks every request makes before routing: health, `Host`, `Origin`, TLS; then adds the
    security headers to every response."""

    def __init__(self, server: HostedServer, app: Any) -> None:
        self.server = server
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        server = self.server
        method = scope["method"]
        if scope["path"] == "/healthz" and method in ("GET", "HEAD"):
            healthy = server.instance.store.exists()
            await JSONResponse(
                {"status": "ok" if healthy else "unavailable"}, status_code=200 if healthy else 503
            )(scope, receive, send)
            return
        headers = Headers(scope=scope)
        if headers.get("host") != server.public_url.host_header:
            await PlainTextResponse("invalid Host header", status_code=400)(scope, receive, send)
            return
        origin = headers.get("origin")
        if origin is not None and origin != server.public_url.origin:
            await PlainTextResponse("invalid Origin header", status_code=400)(scope, receive, send)
            return
        if scope.get("scheme") != "https" and not server.allow_plain_http:
            # openspec:hosted-deployment#hosted-security-baseline: no session over plain HTTP.
            if method in ("GET", "HEAD"):
                query = scope.get("query_string", b"").decode("latin-1")
                target = server.public_url.origin + scope["path"] + (f"?{query}" if query else "")
                await RedirectResponse(target, status_code=308)(scope, receive, send)
            else:
                await PlainTextResponse(
                    "this instance only accepts HTTPS", status_code=403
                )(scope, receive, send)  # fmt: skip
            return

        if method in MUTATING_METHODS and not _PROJECT_SCREENS.match(scope["path"]):
            # The instance's own forms are small, and most are answered before anyone has
            # signed in: refuse a large or unsized body before reading it.
            try:
                uploads.check_declared_length(
                    headers, "application/x-www-form-urlencoded", max_upload_bytes=0
                )
            except uploads.UploadRefused as refusal:
                await PlainTextResponse(refusal.message, status_code=refusal.status_code)(
                    scope, receive, send
                )
                return

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                response_headers = MutableHeaders(scope=message)
                if "content-security-policy" not in response_headers:
                    response_headers["Content-Security-Policy"] = _CSP
                response_headers["X-Content-Type-Options"] = "nosniff"
                response_headers["X-Frame-Options"] = "DENY"
                response_headers["Referrer-Policy"] = "same-origin"
                if "cache-control" not in response_headers:
                    response_headers["Cache-Control"] = "no-store"
                if server.secure:
                    response_headers["Strict-Transport-Security"] = _HSTS
            await send(message)

        await self.app(scope, receive, send_with_headers)


# ----------------------------------------------------------------------- instance pages


def _routes(server: HostedServer) -> list[Route | Mount]:
    instance = server.instance
    store = instance.store

    async def projects_page(request: Request) -> Response:
        current = server.current(request)
        if current is None:
            return RedirectResponse("/signin", status_code=303)
        session, user = current
        rows = []
        for membership in members_mod.memberships_of(instance, user.username):
            project = instance.get_project(membership.project)
            if project is None:
                continue
            rows.append(
                {
                    "project": project,
                    "membership": membership,
                    "sync": server.sync.status(project.id).as_view(),
                }
            )
        return server.render(
            request, "hosted/projects.html", {"rows": rows, "user": user, "csrf": session.csrf}
        )

    def signin_form(
        request: Request, *, error: str | None = None, username: str = "", status_code: int = 200
    ) -> Response:
        token = request.cookies.get(server.signin_cookie) or random_token()
        response = server.render(
            request,
            "hosted/signin.html",
            {
                "error": error,
                "username": username,
                "next": _safe_next(request.query_params.get("next")),
                "providers": instance.settings.oidc,
                "csrf": token,
                "user": None,
            },
            status_code=status_code,
        )
        server.set_cookie(response, server.signin_cookie, token, max_age=3600)
        return response

    def presession_ok(request: Request, form: FormData) -> bool:
        cookie = request.cookies.get(server.signin_cookie)
        submitted = form.get(CSRF_FIELD_NAME)
        return bool(cookie) and isinstance(submitted, str) and submitted == cookie

    async def signin(request: Request) -> Response:
        if request.method == "GET":
            if server.current(request) is not None:
                return RedirectResponse("/", status_code=303)
            return signin_form(request)
        form = await request.form()
        if not presession_ok(request, form):
            return PlainTextResponse("missing or invalid CSRF token", status_code=403)
        username = str(form.get("username") or "")
        password = str(form.get("password") or "")
        try:
            user = await anyio.to_thread.run_sync(
                lambda: accounts.sign_in(
                    store, username, password, client=_client_of(request.scope), now=server.clock()
                )
            )
        except accounts.SignInRefused as refused:
            return signin_form(
                request,
                error=str(refused),
                username=username,
                status_code=429 if refused.reason == "locked" else 401,
            )
        response = RedirectResponse(_safe_next(str(form.get("next") or "")), status_code=303)
        server.start_session(response, user.username)
        return response

    async def signout(request: Request) -> Response:
        current = server.current(request)
        form = await request.form()
        if current is not None:
            session, user = current
            if not accounts.csrf_matches(session, _str(form.get(CSRF_FIELD_NAME))):
                return PlainTextResponse("missing or invalid CSRF token", status_code=403)
            # Signing out ends a screening session
            # (openspec:git-integration#batched-screening-commits).
            mine = members_mod.memberships_of(instance, user.username)

            def flush_all() -> None:
                for membership in mine:
                    with contextlib.suppress(Exception):
                        server.sync.flush(membership.project, actor=membership.actor)

            await anyio.to_thread.run_sync(flush_all)
            accounts.end_session(store, request.cookies.get(server.session_cookie))
        response = RedirectResponse("/signin", status_code=303)
        response.delete_cookie(server.session_cookie, path="/")
        return response

    async def invite(request: Request) -> Response:
        token = request.path_params["token"]
        username = accounts.invitation_user(store, token, now=server.clock())
        invited = accounts.get_user(store, username) if username else None
        if invited is None:
            return server.message(
                request, "Invitation", "This invitation has expired or has already been used.", 404
            )
        presession = request.cookies.get(server.signin_cookie) or random_token()

        def page(error: str | None = None, status_code: int = 200) -> Response:
            response = server.render(
                request,
                "hosted/invite.html",
                {
                    "invited": invited,
                    "token": token,
                    "error": error,
                    "providers": instance.settings.oidc,
                    "min_length": accounts.MIN_PASSWORD_LENGTH,
                    "csrf": presession,
                    "user": None,
                },
                status_code=status_code,
            )
            server.set_cookie(response, server.signin_cookie, presession, max_age=3600)
            return response

        if request.method == "GET":
            return page()
        form = await request.form()
        if not presession_ok(request, form):
            return PlainTextResponse("missing or invalid CSRF token", status_code=403)
        try:
            accepted = await anyio.to_thread.run_sync(
                lambda: accounts.accept_invitation(
                    store, token, str(form.get("password") or ""), now=server.clock()
                )
            )
        except accounts.AccountError as exc:
            return page(str(exc), status_code=422)
        accounts.log_signin(
            store, username=accepted, client=_client_of(request.scope), method="invitation",
            outcome="success", now=server.clock(),
        )  # fmt: skip
        response = RedirectResponse("/", status_code=303)
        server.start_session(response, accepted)
        return response

    async def oidc_start(request: Request) -> Response:
        provider = server.provider(request.path_params["provider"])
        if provider is None:
            return server.message(request, "Sign in", "There is no such sign-in provider.", 404)
        invitation = request.query_params.get("invite")
        if invitation is not None and accounts.invitation_user(store, invitation) is None:
            return server.message(
                request, "Invitation", "This invitation has expired or has already been used.", 404
            )
        try:
            url = await anyio.to_thread.run_sync(
                lambda: server.oidc(provider).start(invitation=invitation)
            )
        except OidcError as exc:
            return server.message(request, "Sign in", str(exc), 502)
        response = RedirectResponse(url, status_code=303)
        # Bind the sign-in to this browser, so a callback started in someone else's browser
        # cannot sign this one in (login CSRF). `Lax`, because the provider's redirect back is a
        # cross-site navigation, which a `Strict` cookie would not accompany.
        state = parse_qs(urlsplit(url).query).get("state", [""])[0]
        response.set_cookie(
            server.oidc_state_cookie, _digest(state), max_age=600, path="/auth/",
            secure=server.secure, httponly=True, samesite="lax",
        )  # fmt: skip
        return response

    async def oidc_callback(request: Request) -> Response:
        provider = server.provider(request.path_params["provider"])
        if provider is None:
            return server.message(request, "Sign in", "There is no such sign-in provider.", 404)
        client = _client_of(request.scope)
        method = f"oidc:{provider.id}"
        bound = request.cookies.get(server.oidc_state_cookie, "")
        if not hmac.compare_digest(bound, _digest(request.query_params.get("state") or "")):
            return server.message(
                request, "Sign in", "This sign-in was not started in this browser; start again.",
                403,
            )  # fmt: skip
        try:
            identity = await anyio.to_thread.run_sync(
                lambda: server.oidc(provider).finish(
                    state=request.query_params.get("state"), code=request.query_params.get("code")
                )
            )
            if identity.invitation is not None:
                username = accounts.use_invitation(store, identity.invitation, now=server.clock())
                link_identity(
                    store, provider=provider.id, subject=identity.subject, username=username
                )
            else:
                linked = user_for_identity(store, provider=provider.id, subject=identity.subject)
                user = accounts.get_user(store, linked) if linked else None
                if user is None or user.disabled:
                    accounts.log_signin(
                        store, username=f"{provider.id}:{identity.subject}", client=client,
                        method=method, outcome="failure", now=server.clock(),
                    )  # fmt: skip
                    return server.message(
                        request,
                        "Sign in",
                        f"This {provider.label} account is not linked to an account here. Ask an "
                        "administrator of this instance for an invitation.",
                        403,
                    )
                username = user.username
        except (OidcError, accounts.AccountError) as exc:
            return server.message(request, "Sign in", str(exc), 403)
        accounts.log_signin(
            store, username=username, client=client, method=method, outcome="success",
            now=server.clock(),
        )  # fmt: skip
        # Not a redirect: a browser arriving from the provider is on a cross-site navigation,
        # and would not send the new `SameSite=Strict` session cookie along a redirect from it.
        # A page that moves on by itself starts a same-site navigation, which does.
        response = server.render(
            request, "hosted/continue.html", {"target": "/", "user": None, "csrf": ""}
        )
        server.start_session(response, username)
        response.delete_cookie(server.oidc_state_cookie, path="/auth/")
        return response

    return [
        Route("/", projects_page, methods=["GET"]),
        Route("/signin", signin, methods=["GET", "POST"]),
        Route("/signout", signout, methods=["POST"]),
        Route("/invite/{token}", invite, methods=["GET", "POST"]),
        Route("/auth/{provider}/start", oidc_start, methods=["GET"]),
        Route("/auth/{provider}/callback", oidc_callback, methods=["GET"]),
        Mount("/static", StaticFiles(directory=_static_dir()), name="static"),
        Mount("/p/{project}/-", routes=_project_admin_routes(server)),
        Route("/p/{project}/mcp", _McpEndpoint(server), methods=["GET", "POST", "DELETE"]),
        Mount("/p/{project}", app=_ProjectDispatcher(server)),
    ]


def _str(value: Any) -> str | None:
    return value if isinstance(value, str) else None


def _member_context(
    server: HostedServer, request: Request
) -> tuple[Project, accounts.Session, accounts.User, members_mod.Membership] | Response:
    """The project, session, account and membership of a request inside a project, or the
    response refusing it."""
    current = server.current(request)
    if current is None:
        if request.method in ("GET", "HEAD"):
            target = quote(request.url.path, safe="/")
            return RedirectResponse(f"/signin?next={target}", status_code=303)
        return PlainTextResponse("sign in first", status_code=401)
    session, user = current
    project_id = request.path_params.get("project", "")
    project = server.instance.get_project(project_id)
    membership = (
        members_mod.membership(server.instance, project_id, user.username) if project else None
    )
    if project is None or membership is None:
        # The same answer whether the project exists or not: a non-member learns nothing.
        return PlainTextResponse("there is no such project", status_code=404)
    return project, session, user, membership


def _project_admin_routes(server: HostedServer) -> list[Route]:
    instance = server.instance

    async def members_page(request: Request) -> Response:
        context = _member_context(server, request)
        if isinstance(context, Response):
            return context
        project, session, user, membership = context
        if membership.role != "lead":
            return PlainTextResponse("only a lead of this project manages its members", 403)
        error = None
        status_code = 200
        if request.method == "POST":
            form = await request.form()
            if not accounts.csrf_matches(session, _str(form.get(CSRF_FIELD_NAME))):
                return PlainTextResponse("missing or invalid CSRF token", status_code=403)
            try:
                members_mod.add_member(
                    instance,
                    project.id,
                    str(form.get("username") or "").strip(),
                    actor=str(form.get("actor") or ""),
                    role=str(form.get("role") or ""),
                )
            except (members_mod.MembershipError, RepoNotFoundError) as exc:
                error, status_code = str(exc), 422
            else:
                return RedirectResponse(f"/p/{quote(project.id)}/-/members", status_code=303)
        repo = instance.open_project(project.id)
        actors = [a for a in repo.config.get("actors", []) if a.get("role") != "inactive"]
        return server.render(
            request,
            "hosted/members.html",
            {
                "project": project,
                "memberships": members_mod.members_of(instance, project.id),
                "actors": actors,
                "roles": members_mod.ROLES,
                "error": error,
                "user": user,
                "csrf": session.csrf,
            },
            status_code=status_code,
        )

    async def remove_member(request: Request) -> Response:
        context = _member_context(server, request)
        if isinstance(context, Response):
            return context
        project, session, _user, membership = context
        if membership.role != "lead":
            return PlainTextResponse("only a lead of this project manages its members", 403)
        form = await request.form()
        if not accounts.csrf_matches(session, _str(form.get(CSRF_FIELD_NAME))):
            return PlainTextResponse("missing or invalid CSRF token", status_code=403)
        username = str(form.get("username") or "")
        target = members_mod.membership(instance, project.id, username)
        leads = members_mod.leads_of(instance, project.id)
        if target is not None and target.role == "lead" and len(leads) <= 1:
            return PlainTextResponse("a project keeps at least one lead", status_code=422)
        members_mod.remove_member(instance, project.id, username)
        return RedirectResponse(f"/p/{quote(project.id)}/-/members", status_code=303)

    async def sync_page(request: Request) -> Response:
        context = _member_context(server, request)
        if isinstance(context, Response):
            return context
        project, session, user, membership = context
        if request.method == "POST":
            form = await request.form()
            if not accounts.csrf_matches(session, _str(form.get(CSRF_FIELD_NAME))):
                return PlainTextResponse("missing or invalid CSRF token", status_code=403)
            action = form.get("action")
            if action == "sync" and membership.role != "observer":
                await anyio.to_thread.run_sync(
                    lambda: server.sync.sync_now(project.id, membership.actor)
                )
            elif action == "resolve" and membership.role == "lead":
                conflicts = server.sync.status(project.id).conflicts
                choices: dict[str, str | Edited] = {}
                for index, conflict in enumerate(conflicts):
                    choice = form.get(f"choice-{index}")
                    if choice in ("mine", "theirs"):
                        choices[conflict["path"]] = str(choice)
                    elif choice == "edit":
                        text = str(form.get(f"text-{index}") or "").replace("\r\n", "\n")
                        choices[conflict["path"]] = Edited(text)
                await anyio.to_thread.run_sync(
                    lambda: server.sync.resolve(project.id, membership.actor, choices)
                )
            else:
                return PlainTextResponse("your role cannot do this here", status_code=403)
            return RedirectResponse(f"/p/{quote(project.id)}/-/sync", status_code=303)
        status = server.sync.status(project.id)
        return server.render(
            request,
            "hosted/sync.html",
            {
                "project": project,
                "status": status,
                "view": status.as_view(),
                "is_lead": membership.role == "lead",
                "can_sync": membership.role != "observer",
                "user": user,
                "csrf": session.csrf,
            },
        )

    return [
        Route("/members", members_page, methods=["GET", "POST"]),
        Route("/members/remove", remove_member, methods=["POST"]),
        Route("/sync", sync_page, methods=["GET", "POST"]),
    ]


# --------------------------------------------------------------------- the project screens


class _ProjectDispatcher:
    """`/p/<project>/...`: authenticate, authorise, then hand the request to the review's
    screens as the member's actor."""

    def __init__(self, server: HostedServer) -> None:
        self.server = server

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        server = self.server
        request = Request(scope, receive)
        context = _member_context(server, request)
        if isinstance(context, Response):
            await context(scope, receive, send)
            return
        project, session, user, membership = context
        root_path = scope.get("root_path", "")
        relative = scope["path"][len(root_path) :] or "/"
        method = scope["method"]

        capability = members_mod.required_capability(method, relative)
        if not members_mod.may(membership.role, capability):
            await PlainTextResponse(
                f"your role in this project ({membership.role}) cannot do this", status_code=403
            )(scope, receive, send)
            return

        form = None
        if method in MUTATING_METHODS:
            content_type = request.headers.get("content-type", "")
            if "form" not in content_type:
                await PlainTextResponse("missing or invalid CSRF token", status_code=403)(
                    scope, receive, send
                )
                return
            try:
                uploads.check_declared_length(
                    request.headers,
                    content_type,
                    max_upload_bytes=server.instance.settings.max_upload_mb * uploads.MIB,
                )
                form = await request.form(
                    max_files=uploads.MAX_FILES_PER_REQUEST,
                    max_fields=uploads.MAX_FIELDS_PER_REQUEST,
                    max_part_size=uploads.MAX_FIELD_BYTES,
                )
            except uploads.UploadRefused as refusal:
                await PlainTextResponse(refusal.message, status_code=refusal.status_code)(
                    scope, receive, send
                )
                return
            except HTTPException as exc:
                await PlainTextResponse(str(exc.detail), status_code=exc.status_code)(
                    scope, receive, send
                )
                return
            if not accounts.csrf_matches(session, _str(form.get(CSRF_FIELD_NAME))):
                await form.close()
                await PlainTextResponse("missing or invalid CSRF token", status_code=403)(
                    scope, receive, send
                )
                return
        elif not relative.startswith("/static/"):
            await anyio.to_thread.run_sync(
                lambda: server.sync.pull_before_read(project.id, membership.actor)
            )

        if form is not None and needs_screening_flush(relative, form):
            # Everyone's pending screening decisions are committed first, each as a batch of their
            # own under their own identity, so none rides along in this member's commit
            # (openspec:hosted-deployment#commit-attribution).
            await anyio.to_thread.run_sync(server.sync.flush, project.id)

        try:
            repo_root = server.instance.project_dir(project.id)
            base = server.project_state(project)
            state = base.for_request(
                actor=membership.actor,
                session_token=session.csrf,
                hosted=server.hosted_view(project, session, user, membership),
            )
            scope.setdefault("state", {})
            scope["state"][REQUEST_STATE_KEY] = state
            if form is not None:
                scope["state"]["form"] = form
            repo = state.open_repo()
            head_before = gitio.current_commit(repo_root) if form is not None else None
            status_holder: dict[str, int] = {}

            async def send_rewritten(message: Message) -> None:
                if message["type"] == "http.response.start":
                    status_holder["status"] = message["status"]
                    headers = MutableHeaders(scope=message)
                    location = headers.get("location")
                    if location and location.startswith("/") and not location.startswith("//"):
                        headers["location"] = root_path + location
                await send(message)

            with (
                gitio.environment(identity_for(server.instance, repo, membership.actor)),
                # A flush made from inside an operation still names each reviewer as their batch's
                # author, not the member whose operation it is.
                batch_identities(lambda handle: identity_for(server.instance, repo, handle)),
            ):
                await server.project_app(scope, receive, send_rewritten)
        finally:
            if form is not None:
                await form.close()

        if form is None:
            return
        if gitio.current_commit(repo_root) != head_before:
            server.sync.note_commit(project.id, membership.actor)
        first = relative.strip("/").split("/", 1)[0]
        if first in _SCREENING_PATHS and status_holder.get("status") == 303:
            await anyio.to_thread.run_sync(
                lambda: server.sync.note_screening(project.id, membership.actor)
            )


# ----------------------------------------------------------------------------- remote MCP


class _McpEndpoint:
    """`/p/<project>/mcp`: the read-only MCP tools over streamable HTTP, for an API token whose
    account is a member of the project."""

    def __init__(self, server: HostedServer) -> None:
        self.server = server

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        from mcp.server.transport_security import TransportSecuritySettings

        from strata.mcpserver.server import create_hosted_mcp_server

        server = self.server
        headers = Headers(scope=scope)
        authorization = headers.get("authorization", "")
        token = authorization[7:].strip() if authorization.lower().startswith("bearer ") else None
        username = accounts.user_for_api_token(server.instance.store, token, now=server.clock())
        if username is None:
            await JSONResponse(
                {"error": "invalid_token", "error_description": "a valid API token is required"},
                status_code=401,
                headers={"WWW-Authenticate": 'Bearer realm="strata"'},
            )(scope, receive, send)
            return
        project_id = scope.get("path_params", {}).get("project", "")
        project = server.instance.get_project(project_id)
        membership = members_mod.membership(server.instance, project_id, username)
        if project is None or membership is None:
            await JSONResponse({"error": "there is no such project"}, status_code=404)(
                scope, receive, send
            )
            return
        await anyio.to_thread.run_sync(
            lambda: server.sync.pull_before_read(project.id, membership.actor)
        )
        mcp = create_hosted_mcp_server(
            repo_root=server.instance.project_dir(project.id), actor=membership.actor
        )
        app = mcp.streamable_http_app(
            streamable_http_path="/",
            stateless_http=True,
            json_response=True,
            transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
        )
        inner = {**scope, "path": "/", "raw_path": b"/", "root_path": ""}
        async with app.router.lifespan_context(app):
            await app(inner, receive, send)


# ------------------------------------------------------------------------------- the app


def create_hosted_app(server: HostedServer) -> Any:
    """The ASGI application for a hosted instance."""

    @contextlib.asynccontextmanager
    async def lifespan(_app: Starlette) -> AsyncIterator[None]:
        if server.worker is not None:
            server.worker.start()
        try:
            yield
        finally:
            if server.worker is not None:
                server.worker.stop()

    app = Starlette(routes=_routes(server), lifespan=lifespan)
    app.state.hosted = server
    return _Gate(server, app)


def run_hosted(
    server: HostedServer, *, bind: str, port: int, trusted_proxies: str
) -> None:  # pragma: no cover - binds a real socket; the app itself is tested in-process
    """Serve the instance until interrupted. `trusted_proxies` are the addresses whose
    `X-Forwarded-Proto`/`X-Forwarded-For` uvicorn believes (the reverse proxy terminating TLS)."""
    import uvicorn

    uvicorn.run(
        create_hosted_app(server),
        host=bind,
        port=port,
        proxy_headers=True,
        forwarded_allow_ips=trusted_proxies,
        server_header=False,
        log_level="info",
        # An access log would record invitation links, which carry their token in the path.
        access_log=False,
    )
