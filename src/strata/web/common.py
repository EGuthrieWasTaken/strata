"""Small helpers every web route module needs, so none has to import another's privates."""

from __future__ import annotations

from fastapi import Request
from fastapi.responses import RedirectResponse

from strata.web.app import AppState


def state_of(request: Request) -> AppState:
    state: AppState = request.app.state.strata
    return state


def go(path: str) -> RedirectResponse:
    """Redirect after a POST, so a reload does not repeat it."""
    return RedirectResponse(url=path, status_code=303)
