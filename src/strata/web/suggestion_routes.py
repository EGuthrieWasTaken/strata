"""The suggestions screen: openspec:web-ui#suggestions-screen.

A thin adapter: it lists what `strata suggestions list` lists, and adopting or rejecting records
exactly what `strata suggestions adopt` and `reject` record, by calling the same functions
(`strata.core.agent_ops`). Blinding is applied there, not here: a suggestion about a record the
signed-in person has not decided yet is simply not in the list.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse

from strata.core import agent_ops
from strata.core import agents as agents_mod
from strata.core.commit import RationaleRejectedError
from strata.core.repo import LockTimeoutError
from strata.protocol import suggestions as sugg
from strata.web.common import go
from strata.web.common import state_of as _state
from strata.web.routes import _error, _render

router = APIRouter()


def _page(
    request: Request,
    *,
    error: str | None = None,
    moved: dict[str, str] | None = None,
    status_code: int = 200,
) -> HTMLResponse:
    state = _state(request)
    repo = state.open_repo()
    enabled = agents_mod.is_enabled(repo)
    items = agent_ops.visible_pending(repo, state.actor) if enabled else []
    hidden = enabled and len(items) < len(sugg.pending(repo)) and agent_ops.is_blinded(repo)
    invoker = agents_mod.resolve_invoker(repo, state.actor)
    context: dict[str, Any] = {
        "enabled": enabled,
        "items": items,
        "hidden_note": hidden,
        "error": error,
        "moved": moved or {},
        "can_act": invoker.handle is not None,
        "session_token": state.session_token,
    }
    return _render(request, "suggestions.html", context, status_code=status_code)


@router.get("/suggestions", response_class=HTMLResponse)
def suggestions_view(request: Request) -> HTMLResponse:
    return _page(request)


@router.post("/suggestions/{suggestion_id}/adopt", response_model=None)
def suggestion_adopt(
    request: Request, suggestion_id: str
) -> HTMLResponse | RedirectResponse | PlainTextResponse:
    state = _state(request)
    repo = state.open_repo()
    form = request.state.form
    rationale = str(form.get("rationale") or "")
    problem = None
    try:
        agent_ops.adopt(
            repo,
            suggestion_id,
            by=state.actor,
            rationale=rationale,
            confirm_moved=form.get("confirm") == "1",
        )
    except agent_ops.StateMoved as exc:
        return _page(request, error=str(exc), moved={suggestion_id: str(exc)}, status_code=409)
    except agent_ops.AdoptionError as exc:
        problem = str(exc)
    except RationaleRejectedError as exc:
        problem = str(exc)
    except LockTimeoutError as exc:
        return _error(str(exc), status_code=503)
    if problem is not None:
        return _page(request, error=problem, status_code=422)
    return go("/suggestions")


@router.post("/suggestions/{suggestion_id}/reject", response_model=None)
def suggestion_reject(
    request: Request, suggestion_id: str
) -> HTMLResponse | RedirectResponse | PlainTextResponse:
    state = _state(request)
    repo = state.open_repo()
    reason = str(request.state.form.get("reason") or "")
    try:
        agent_ops.reject(repo, suggestion_id, by=state.actor, reason=reason)
    except (agent_ops.AdoptionError, RationaleRejectedError) as exc:
        return _page(request, error=str(exc), status_code=422)
    except LockTimeoutError as exc:
        return _error(str(exc), status_code=503)
    return go("/suggestions")
