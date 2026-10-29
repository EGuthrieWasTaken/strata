"""Uploads at the HTTP layer: openspec:web-uploads
(OpenSpec change `add-web-ui-write-surfaces`, tasks 3.2 and 3.3).

The upload routes themselves arrive in a later task group; these tests put a probe route behind the
same security middleware to show what the middleware does with a file before any route sees it.
"""

from __future__ import annotations

import io
from collections.abc import Iterator
from pathlib import Path

from fastapi import Request
from fastapi.responses import PlainTextResponse
from fastapi.testclient import TestClient

from strata import gitio
from strata.core.init import init_repository
from strata.web import uploads
from strata.web.app import create_app

_TOKEN = "test-session-token-0123456789"
MIB = uploads.MIB
_MULTIPART = {"content-type": "multipart/form-data; boundary=x"}


def _app(tmp_path: Path, *, max_upload_bytes: int = MIB):  # type: ignore[no-untyped-def]
    root = tmp_path / "review"
    if not root.exists():
        init_repository(root, title="Upload Test", actor_handle="ethan", actor_name="Ethan")
    app = create_app(
        repo_root=root, actor="ethan", session_token=_TOKEN, max_upload_bytes=max_upload_bytes
    )

    @app.post("/_probe")
    async def probe(request: Request) -> PlainTextResponse:
        form = request.state.form
        files = [(f.filename, f.file) for f in form.getlist("files") if f.filename]
        if not files:
            return PlainTextResponse("no files", status_code=200)
        batch = request.app.state.strata.staging.stage(files)
        return PlainTextResponse(batch.id)

    return app, root


def _client(app, *, authenticated: bool = True) -> TestClient:  # type: ignore[no-untyped-def]
    client = TestClient(app, base_url="http://127.0.0.1:8000")
    if authenticated:
        assert client.get(f"/?token={_TOKEN}").status_code == 200
    return client


def _post_files(
    client: TestClient,
    files: list[tuple[str, bytes]],
    *,
    csrf: str | None = _TOKEN,
    data: dict[str, str] | None = None,
    headers: dict[str, str] | None = None,
):  # type: ignore[no-untyped-def]
    fields = dict(data or {})
    if csrf is not None:
        fields["csrf_token"] = csrf
    return client.post(
        "/_probe",
        data=fields,
        files=[("files", (name, content, "application/octet-stream")) for name, content in files],
        headers=headers or {},
    )


def _staged(root: Path) -> list[str]:
    staging = root / ".strata" / "tmp" / "uploads"
    return sorted(p.name for p in staging.iterdir()) if staging.exists() else []


def _clean(root: Path) -> bool:
    return gitio.run(["status", "--porcelain", "--untracked-files=all"], cwd=root).stdout == ""


# ------------------------------------------------------------------------------------ limits


def test_a_file_under_the_limit_reaches_the_route_and_is_staged(tmp_path: Path) -> None:
    app, root = _app(tmp_path)

    response = _post_files(_client(app), [("export.ris", b"TY  - JOUR\nER  - \n")])

    assert response.status_code == 200
    assert _staged(root) == [response.text]
    assert _clean(root)


def test_a_file_over_the_limit_is_refused_naming_the_limit_and_leaves_nothing(
    tmp_path: Path,
) -> None:
    app, root = _app(tmp_path, max_upload_bytes=MIB)

    response = _post_files(_client(app), [("big.ris", b"x" * (2 * MIB))])

    assert response.status_code == 413
    assert "limit is 1 MB" in response.text
    assert _staged(root) == []
    assert not (root / ".strata" / "tmp").exists()
    assert _clean(root)


def test_the_limit_can_be_raised(tmp_path: Path) -> None:
    app, root = _app(tmp_path, max_upload_bytes=4 * MIB)

    response = _post_files(_client(app), [("big.ris", b"x" * (2 * MIB))])

    assert response.status_code == 200
    assert len(_staged(root)) == 1


def test_a_request_that_does_not_say_how_large_it_is_is_refused(tmp_path: Path) -> None:
    app, root = _app(tmp_path)
    client = _client(app)

    def chunks() -> Iterator[bytes]:
        yield b"--x\r\n"
        yield b'Content-Disposition: form-data; name="csrf_token"\r\n\r\n' + _TOKEN.encode()
        yield b"\r\n--x--\r\n"

    response = client.post("/_probe", content=chunks(), headers=_MULTIPART)

    assert response.status_code == 411
    assert "cannot be checked" in response.text and "1 MB" in response.text
    assert _staged(root) == []


def test_too_many_files_are_refused_and_nothing_is_staged(tmp_path: Path) -> None:
    app, root = _app(tmp_path)
    files = [
        (f"f{i}.ris", b"TY  - JOUR\nER  - \n") for i in range(uploads.MAX_FILES_PER_REQUEST + 1)
    ]

    response = _post_files(_client(app), files)

    assert response.status_code == 400
    assert str(uploads.MAX_FILES_PER_REQUEST) in response.text
    assert _staged(root) == []


def test_exactly_the_most_files_allowed_are_accepted(tmp_path: Path) -> None:
    app, root = _app(tmp_path)
    files = [(f"f{i}.ris", b"TY  - JOUR\nER  - \n") for i in range(uploads.MAX_FILES_PER_REQUEST)]

    response = _post_files(_client(app), files)

    assert response.status_code == 200


def test_a_text_field_over_its_limit_is_refused_even_within_the_request_limit(
    tmp_path: Path,
) -> None:
    app, root = _app(tmp_path, max_upload_bytes=8 * MIB)

    response = _post_files(_client(app), [("a.ris", b"x")], data={"query": "q" * (2 * MIB)})

    assert response.status_code == 400
    assert "exceeded maximum size" in response.text
    assert _staged(root) == []


def test_an_ordinary_form_is_held_to_the_small_limit(tmp_path: Path) -> None:
    app, _root = _app(tmp_path, max_upload_bytes=500 * MIB)

    response = _client(app).post("/_probe", data={"csrf_token": _TOKEN, "notes": "n" * (2 * MIB)})

    assert response.status_code == 413
    assert "limit is 1 MB" in response.text


# --------------------------------------------------------------------------------- the order


def test_a_foreign_origin_is_refused_before_the_size_is_looked_at(tmp_path: Path) -> None:
    app, root = _app(tmp_path)

    response = _post_files(
        _client(app),
        [("big.ris", b"x" * (2 * MIB))],
        headers={"origin": "http://evil.example"},
    )

    assert response.status_code == 400
    assert response.text == "invalid Origin header"
    assert _staged(root) == []


def test_a_wrong_host_is_refused_before_the_size_is_looked_at(tmp_path: Path) -> None:
    app, root = _app(tmp_path)

    response = _post_files(
        _client(app), [("big.ris", b"x" * (2 * MIB))], headers={"host": "evil.example:8000"}
    )

    assert response.status_code == 400
    assert response.text == "invalid Host header"
    assert _staged(root) == []


def test_no_session_is_refused_before_the_size_is_looked_at(tmp_path: Path) -> None:
    app, root = _app(tmp_path)

    response = _post_files(_client(app, authenticated=False), [("big.ris", b"x" * (2 * MIB))])

    assert response.status_code == 403
    assert response.text == "missing or invalid session"
    assert _staged(root) == []


def test_a_missing_csrf_token_stages_nothing(tmp_path: Path) -> None:
    app, root = _app(tmp_path)

    response = _post_files(_client(app), [("export.ris", b"TY  - JOUR\nER  - \n")], csrf=None)

    assert response.status_code == 403
    assert response.text == "missing or invalid CSRF token"
    assert _staged(root) == []
    assert not (root / ".strata" / "tmp").exists()


def test_a_wrong_csrf_token_stages_nothing(tmp_path: Path) -> None:
    app, root = _app(tmp_path)

    response = _post_files(_client(app), [("export.ris", b"TY  - JOUR\nER  - \n")], csrf="nope")

    assert response.status_code == 403
    assert _staged(root) == []


# -------------------------------------------------------------------------------- housekeeping


def test_starting_the_server_discards_whatever_an_earlier_one_left_staged(tmp_path: Path) -> None:
    app, root = _app(tmp_path)
    left_behind = uploads.UploadStaging(root, max_total_bytes=MIB).stage(
        [("old.ris", io.BytesIO(b"x"))]
    )
    assert _staged(root) == [left_behind.id]

    _app(tmp_path)  # a new server for the same review

    assert _staged(root) == []
