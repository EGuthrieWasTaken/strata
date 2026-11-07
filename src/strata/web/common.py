"""Small helpers every web route module needs, so none has to import another's privates."""

from __future__ import annotations

from fastapi.responses import RedirectResponse

from strata.web.app import state_of

__all__ = ["go", "state_of"]


def go(path: str) -> RedirectResponse:
    """Redirect after a POST, so a reload does not repeat it."""
    return RedirectResponse(url=path, status_code=303)
