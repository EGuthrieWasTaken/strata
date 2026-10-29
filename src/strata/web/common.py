"""Small helpers every web route module needs, so none has to import another's privates."""

from __future__ import annotations

from typing import Any

from fastapi import Request
from fastapi.responses import RedirectResponse

from strata.core.repo import Repo
from strata.web.app import AppState


def state_of(request: Request) -> AppState:
    state: AppState = request.app.state.strata
    return state


def active_actors(repo: Repo) -> list[dict[str, Any]]:
    """The review's actors who can still be given work (not marked inactive)."""
    return [a for a in repo.config.get("actors", []) if a.get("role") != "inactive"]


def go(path: str) -> RedirectResponse:
    """Redirect after a POST, so a reload does not repeat it."""
    return RedirectResponse(url=path, status_code=303)
