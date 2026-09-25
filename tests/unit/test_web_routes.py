"""Unit tests for the small internal helpers in `web.routes` that every
route handler shares: `_error` (a plain, non-templated error body -- see
that function's docstring for why it's `text/plain`, not `text/html`) and
`_redirect` (a percent-encoded, same-origin-only redirect builder). Both
were added specifically to close CodeQL findings on `web/routes.py`
(reflected XSS and open redirect / header injection) -- these tests pin
the behaviour those fixes depend on, including the defensive branch in
`_redirect` no legitimate caller can reach through the HTTP surface."""

from __future__ import annotations

import pytest

from strata.web.routes import _error, _redirect


def test_error_returns_plain_text_with_the_given_status() -> None:
    response = _error("unknown stage 'bogus'", status_code=404)
    assert response.status_code == 404
    assert response.media_type == "text/plain"
    assert response.body == b"unknown stage 'bogus'"


def test_error_does_not_interpret_markup_in_the_message() -> None:
    """The whole point of `_error`: a value like `<script>` must survive
    as literal text, never be interpreted as HTML by a browser."""
    response = _error("<script>alert(1)</script>", status_code=422)
    assert response.body == b"<script>alert(1)</script>"
    assert response.media_type == "text/plain"


def test_redirect_with_no_query_values() -> None:
    response = _redirect("/dedup")
    assert response.status_code == 303
    assert response.headers["location"] == "/dedup"


def test_redirect_percent_encodes_query_values() -> None:
    response = _redirect("/screen/title-abstract", prev="rec_1", skip="a:b,c")
    location = response.headers["location"]
    assert location.startswith("/screen/title-abstract?")
    assert "prev=rec_1" in location
    assert "skip=a%3Ab%2Cc" in location


def test_redirect_omits_empty_query_values() -> None:
    response = _redirect("/adjudicate/title-abstract", skip="")
    assert response.headers["location"] == "/adjudicate/title-abstract"


def test_redirect_refuses_a_scheme_or_host_in_the_path() -> None:
    """No legitimate caller builds a path this way (every call site passes
    a literal `/`-prefixed string plus percent-encoded segments), but this
    pins the defensive check itself: CodeQL's py/url-redirection concern is
    exactly a value that could send the browser off this app entirely."""
    with pytest.raises(ValueError, match="non-relative target"):
        _redirect("http://evil.example/phish")


def test_redirect_refuses_a_protocol_relative_target() -> None:
    with pytest.raises(ValueError, match="non-relative target"):
        _redirect("//evil.example/phish")
