"""Searches and imports in the browser: openspec:web-ui#search-and-import-screens,
#review-before-importing, #imports-from-other-methods
(OpenSpec change `add-web-ui-write-surfaces`, tasks 4.1 to 4.5).

Everything goes through the real ASGI app against a real temporary review, with the operations the
command line uses doing the writing, so what lands in git is what the command line would have put
there.
"""

from __future__ import annotations

import html
import json
import re
from datetime import date
from pathlib import Path
from typing import Any

import pytest
import tomlkit
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from strata import gitio
from strata.cli.main import app as cli_app
from strata.core import operations as ops
from strata.core.actor import add_actor
from strata.core.init import init_repository
from strata.core.repo import open_repo, repo_lock
from strata.web import uploads
from strata.web.app import create_app
from tests.unit._xlsx import build_xlsx

_TOKEN = "test-session-token-0123456789"
_WHY = "Recording this from the browser in a test"
_FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "exports"
_RIS = "TY  - JOUR\nTI  - First paper\nAU  - Smith, J.\nPY  - 2020\nDO  - 10.1000/aaa\nER  - \n"
_RIS_TWO = (
    "TY  - JOUR\nTI  - First paper\nPY  - 2020\nDO  - 10.1000/aaa\nER  - \n"
    "TY  - JOUR\nTI  - Second paper\nPY  - 2021\nDO  - 10.1000/bbb\nER  - \n"
)
_CUSTOM_CSV = "MyTitle,MyAuthor,MyYear\nA Title,Doe,2020\nB Title,Roe,2021\n"


def _review(tmp_path: Path, name: str = "review") -> Path:
    root = tmp_path / name
    init_repository(root, title="Web Search Test", actor_handle="ethan", actor_name="Ethan")
    return root


def _client(root: Path, **kwargs: Any) -> TestClient:
    app = create_app(repo_root=root, actor="ethan", session_token=_TOKEN, **kwargs)
    client = TestClient(app, base_url="http://127.0.0.1:8000")
    assert client.get(f"/?token={_TOKEN}").status_code == 200
    return client


def _post(
    client: TestClient,
    path: str,
    data: dict[str, str] | None = None,
    files: list[tuple[str, bytes]] | None = None,
    **kwargs: Any,
):  # type: ignore[no-untyped-def]
    fields = {"csrf_token": _TOKEN, **(data or {})}
    multipart = [("files", (n, c, "application/octet-stream")) for n, c in (files or [])]
    return client.post(path, data=fields, files=multipart or None, follow_redirects=False, **kwargs)


def _search_fields(**overrides: str) -> dict[str, str]:
    fields = {
        "database": "MEDLINE",
        "platform": "Ovid",
        "executed": "2026-03-04",
        "executed_by": "ethan",
        "query": "1 exp Learning/",
        "hits": "4182",
        "rationale": _WHY,
    }
    fields.update(overrides)
    return fields


def _head(root: Path) -> str:
    return gitio.run(["log", "-1", "--format=%B"], cwd=root).stdout


def _subjects(root: Path, n: int = 5) -> list[str]:
    return gitio.log(root, max_count=n, fmt="%s")


def _clean(root: Path) -> bool:
    return gitio.run(["status", "--porcelain", "--untracked-files=all"], cwd=root).stdout == ""


def _batch_of(response) -> str:  # type: ignore[no-untyped-def]
    assert response.status_code == 303, response.text
    location = response.headers["location"]
    match = re.fullmatch(r"/import/review/([A-Za-z0-9_-]{22})", location)
    assert match, location
    return match.group(1)


def _record_search(client: TestClient, **overrides: str) -> None:
    response = _post(client, "/searches", _search_fields(**overrides))
    assert response.status_code == 303, response.text


def _staged(root: Path) -> list[str]:
    directory = root / ".strata" / "tmp" / "uploads"
    return sorted(p.name for p in directory.iterdir()) if directory.exists() else []


def _squash(text: str) -> str:
    return " ".join(text.split())


# ------------------------------------------------------------------- 4.1 the search screens


def test_the_search_list_starts_empty_and_says_what_to_do(tmp_path: Path) -> None:
    client = _client(_review(tmp_path))

    page = client.get("/searches")

    assert page.status_code == 200
    assert "No searches recorded yet" in page.text
    assert 'href="/searches/new"' in page.text and 'href="/import"' in page.text


def test_the_list_shows_each_search_with_its_date_hits_and_what_became_of_it(
    tmp_path: Path,
) -> None:
    root = _review(tmp_path)
    client = _client(root)
    _record_search(client)
    _record_search(client, database="Embase", platform="Ovid", hits="", query="")
    batch = _batch_of(
        _post(client, "/searches/S-01-medline/files", files=[("m.ris", _RIS_TWO.encode())])
    )
    _post(client, f"/import/review/{batch}", {"rationale": _WHY})

    page = client.get("/searches").text

    assert "S-01-medline" in page and "S-01-embase" in page
    assert "2026-03-04" in page and "4182" in page
    assert "2 new records" in page  # the import from MEDLINE
    assert "Missing (PRISMA item 7)" in page  # Embase was recorded without its query
    assert "No export yet" in page  # and has nothing imported


def test_a_replaced_search_says_so_and_does_not_ask_for_an_export(tmp_path: Path) -> None:
    client = _client(_review(tmp_path))
    _record_search(client)
    _record_search(client, supersedes="S-01-medline")

    page = client.get("/searches").text

    assert "replaced by" in page and "S-02-medline" in page
    detail = client.get("/searches/S-01-medline").text
    assert "re-run as" in detail and 'action="/searches/S-01-medline/files"' not in detail


def test_the_search_page_shows_its_details_and_its_imports(tmp_path: Path) -> None:
    root = _review(tmp_path)
    client = _client(root)
    _record_search(client, notes="English only, 2010 onwards", peer_reviewed_by="sam")
    batch = _batch_of(
        _post(client, "/searches/S-01-medline/files", files=[("m.ris", _RIS.encode())])
    )
    _post(client, f"/import/review/{batch}", {"rationale": _WHY})

    page = client.get("/searches/S-01-medline")
    text = _squash(page.text)

    assert page.status_code == 200
    assert "MEDLINE" in text and "Ovid" in text and "2026-03-04" in text and "4182" in text
    assert "1 exp Learning/" in text
    assert "English only, 2010 onwards" in text and "peer reviewed by sam" in text
    assert "m.ris" in text and "ris" in text  # the imports table
    assert 'action="/searches/S-01-medline/files"' in page.text


def test_an_unknown_search_is_a_404(tmp_path: Path) -> None:
    client = _client(_review(tmp_path))

    assert client.get("/searches/S-99-nothing").status_code == 404


def test_a_hostile_query_and_notes_are_shown_as_text(tmp_path: Path) -> None:
    client = _client(_review(tmp_path))
    _record_search(
        client,
        database="<b>Evil</b>",
        query="<script>alert(1)</script>",
        notes="<img src=x onerror=alert(2)>",
    )

    listing = client.get("/searches").text
    detail = client.get("/searches/S-01-b-evil-b").text

    for page in (listing, detail):
        assert (
            "<script>alert" not in page and "<img src=x" not in page and "<b>Evil</b>" not in page
        )
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in detail
    assert "&lt;img src=x onerror=alert(2)&gt;" in detail


def test_a_search_with_no_query_is_flagged_on_its_page(tmp_path: Path) -> None:
    client = _client(_review(tmp_path))
    _record_search(client, query="")

    page = client.get("/searches/S-01-medline").text

    assert 'data-testid="query-pending"' in page and "PRISMA item 7" in page


def test_the_dashboard_links_a_search_without_a_query_and_one_without_an_export(
    tmp_path: Path,
) -> None:
    client = _client(_review(tmp_path))
    _record_search(client, query="")
    _record_search(client, database="Embase")

    page = client.get("/").text

    pending = page.split('data-testid="pending-queries"')[1].split("</p>")[0]
    awaiting = page.split('data-testid="awaiting-export"')[1].split("</p>")[0]
    assert 'href="/searches/S-01-medline"' in pending
    assert (
        'href="/searches/S-01-medline"' in awaiting and 'href="/searches/S-01-embase"' in awaiting
    )
    assert 'href="/searches"' in page


def test_the_dashboard_stops_asking_once_an_export_is_imported(tmp_path: Path) -> None:
    client = _client(_review(tmp_path))
    _record_search(client)
    batch = _batch_of(
        _post(client, "/searches/S-01-medline/files", files=[("m.ris", _RIS.encode())])
    )
    _post(client, f"/import/review/{batch}", {"rationale": _WHY})

    assert 'data-testid="awaiting-export"' not in client.get("/").text


def test_the_records_page_links_to_searches_and_import(tmp_path: Path) -> None:
    page = _client(_review(tmp_path)).get("/records").text

    assert 'href="/searches"' in page and 'href="/import"' in page


# ----------------------------------------------------------------------- 4.2 record a search


def test_the_form_defaults_the_date_to_today_and_the_runner_to_the_signed_in_actor(
    tmp_path: Path,
) -> None:
    page = _client(_review(tmp_path)).get("/searches/new").text

    assert f'name="executed" value="{date.today().isoformat()}"' in page
    assert '<option value="ethan" selected>' in page
    assert 'type="file"' in page and 'enctype="multipart/form-data"' in page
    assert 'name="rationale"' in page


def test_recording_a_search_commits_what_the_command_line_would(tmp_path: Path) -> None:
    root = _review(tmp_path)
    client = _client(root)

    response = _post(client, "/searches", _search_fields())

    assert response.status_code == 303 and response.headers["location"] == "/searches/S-01-medline"
    assert _head(root) == (
        "search-add(S-01-medline): record search S-01-medline\n"
        "\n"
        f"{_WHY}\n"
        "\n"
        "Strata-Op: search-add\n"
        "Strata-Search: S-01-medline\n"
        "Strata-Actor: ethan\n"
        "\n"
    )
    assert _clean(root)
    saved = (root / "protocol" / "searches" / "S-01-medline.yaml").read_text(encoding="utf-8")
    assert "executed: '2026-03-04'" in saved and "hits: 4182" in saved


def test_a_search_run_on_an_earlier_date_records_that_date(tmp_path: Path) -> None:
    root = _review(tmp_path)
    client = _client(root)

    _record_search(client, executed="2025-12-31")

    assert "executed: '2025-12-31'" in (
        root / "protocol" / "searches" / "S-01-medline.yaml"
    ).read_text(encoding="utf-8")


def test_a_search_without_a_query_is_recorded_as_pending(tmp_path: Path) -> None:
    root = _review(tmp_path)
    client = _client(root)

    _record_search(client, query="  ")

    assert "query: |-\n  PENDING\n" in (
        root / "protocol" / "searches" / "S-01-medline.yaml"
    ).read_text(encoding="utf-8")


def test_a_search_can_be_run_by_another_actor_and_the_trailer_follows(tmp_path: Path) -> None:
    root = _review(tmp_path)
    repo = open_repo(root)
    add_actor(repo, handle="sam", name="Sam", role="screener")
    gitio.add(root, ["strata.toml"])
    gitio.commit(root, "test: add sam")
    client = _client(root)

    _record_search(client, executed_by="sam")

    assert "Strata-Actor: sam" in _head(root)


def test_a_search_for_a_database_with_a_long_name_is_recorded(tmp_path: Path) -> None:
    root = _review(tmp_path)
    client = _client(root)

    _record_search(client, database="Cochrane Central Register of Controlled Trials")

    assert _clean(root)
    assert len(_head(root).splitlines()[0]) <= 72


def test_re_running_a_search_prefills_the_form_and_supersedes_it(tmp_path: Path) -> None:
    root = _review(tmp_path)
    client = _client(root)
    _record_search(client, notes="English only")
    original = (root / "protocol" / "searches" / "S-01-medline.yaml").read_text(encoding="utf-8")

    form = client.get("/searches/new?supersedes=S-01-medline").text
    assert 'value="MEDLINE"' in form and "1 exp Learning/" in form and "English only" in form
    assert 'name="supersedes" value="S-01-medline"' in form

    _record_search(client, executed="2026-09-01", supersedes="S-01-medline")

    assert "supersedes: S-01-medline" in (
        root / "protocol" / "searches" / "S-02-medline.yaml"
    ).read_text(encoding="utf-8")
    assert (root / "protocol" / "searches" / "S-01-medline.yaml").read_text(
        encoding="utf-8"
    ) == original


def test_a_search_that_replaces_an_unknown_one_is_refused_with_the_reason(tmp_path: Path) -> None:
    root = _review(tmp_path)
    client = _client(root)
    before = len(gitio.log(root))

    response = _post(client, "/searches", _search_fields(supersedes="S-77-nothing"))

    assert response.status_code == 422
    assert "supersedes references unknown search" in response.text
    assert len(gitio.log(root)) == before and _clean(root)
    assert 'value="MEDLINE"' in response.text  # what was typed is still there


@pytest.mark.parametrize("rationale", ["", "   ", "update", "short one"])
def test_a_missing_or_unusable_rationale_writes_nothing(tmp_path: Path, rationale: str) -> None:
    root = _review(tmp_path)
    client = _client(root)
    before = len(gitio.log(root))

    response = _post(client, "/searches", _search_fields(rationale=rationale))

    assert response.status_code == 422
    assert 'data-testid="form-error"' in response.text
    assert len(gitio.log(root)) == before
    assert _clean(root)
    assert not (root / "protocol" / "searches" / "S-01-medline.yaml").exists()


def test_a_review_that_does_not_require_a_rationale_commits_without_a_body(tmp_path: Path) -> None:
    root = _review(tmp_path)
    doc = tomlkit.parse((root / "strata.toml").read_text(encoding="utf-8"))
    doc["git"]["require_rationale"] = False  # type: ignore[index]
    (root / "strata.toml").write_text(tomlkit.dumps(doc), encoding="utf-8")
    gitio.add(root, ["strata.toml"])
    gitio.commit(root, "test: rationale off")
    client = _client(root)

    _record_search(client, rationale="")

    assert _head(root).splitlines()[:2] == [
        "search-add(S-01-medline): record search S-01-medline",
        "",
    ]


@pytest.mark.parametrize("missing", ["database", "platform"])
def test_the_database_and_platform_are_required(tmp_path: Path, missing: str) -> None:
    client = _client(_review(tmp_path))

    response = _post(client, "/searches", _search_fields(**{missing: " "}))

    assert response.status_code == 422 and "Say which database" in response.text


def test_hits_must_be_a_whole_number(tmp_path: Path) -> None:
    client = _client(_review(tmp_path))

    response = _post(client, "/searches", _search_fields(hits="lots"))

    assert response.status_code == 422 and "whole number" in response.text


def test_an_empty_file_part_from_a_browser_is_not_a_file(tmp_path: Path) -> None:
    root = _review(tmp_path)
    client = _client(root)

    response = _post(client, "/searches", _search_fields(), files=[("", b"")])

    assert response.headers["location"] == "/searches/S-01-medline"
    assert _staged(root) == []


def test_submitting_files_with_the_search_stages_them_for_review(tmp_path: Path) -> None:
    root = _review(tmp_path)
    client = _client(root)

    response = _post(
        client, "/searches", _search_fields(), files=[("../My Export.ris", _RIS.encode())]
    )

    batch = _batch_of(response)
    assert _staged(root) == [batch]
    saved = (root / "protocol" / "searches" / "S-01-medline.yaml").read_text(encoding="utf-8")
    assert "export_files:\n- My Export.ris\n" in saved  # the sanitised name, as stored
    assert _clean(root)


def test_a_pdf_sent_with_a_search_refuses_the_whole_submission(tmp_path: Path) -> None:
    root = _review(tmp_path)
    client = _client(root)
    before = len(gitio.log(root))

    response = _post(
        client, "/searches", _search_fields(), files=[("paper.pdf", b"%PDF-1.7 not an export")]
    )

    assert response.status_code == 422
    assert "does not store full texts" in response.text
    assert "Nothing was recorded" in response.text
    assert len(gitio.log(root)) == before
    assert _staged(root) == []
    assert not (root / "protocol" / "searches").exists() or not list(
        (root / "protocol" / "searches").glob("*.yaml")
    )


def test_a_search_cannot_be_recorded_while_another_process_holds_the_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _review(tmp_path)
    client = _client(root)
    real = ops.repo_lock
    monkeypatch.setattr(ops, "repo_lock", lambda r, timeout: real(r, timeout=0.2))

    with repo_lock(open_repo(root)):
        response = _post(client, "/searches", _search_fields(), files=[("m.ris", _RIS.encode())])

    assert response.status_code == 503 and "repository is locked" in response.text
    assert _staged(root) == [] and _clean(root)


# ---------------------------------------------------------------------------- 4.3 the review


def _stage(client: TestClient, files: list[tuple[str, bytes]], search: str = "S-01-medline") -> str:
    return _batch_of(_post(client, f"/searches/{search}/files", files=files))


def test_the_review_shows_what_the_import_would_do_and_changes_nothing(tmp_path: Path) -> None:
    root = _review(tmp_path)
    client = _client(root)
    _record_search(client)
    batch = _stage(client, [("m.ris", _RIS_TWO.encode())])
    before = gitio.run(["rev-parse", "HEAD"], cwd=root).stdout

    page = client.get(f"/import/review/{batch}")
    text = _squash(page.text)

    assert page.status_code == 200
    assert "Nothing has been imported yet" in text
    assert "m.ris" in text and "read as ris" in text
    # rows read, new, matched existing, rejected
    assert re.search(
        r"<td[^>]*>2</td>\s*<td[^>]*>2</td>\s*<td[^>]*>0</td>\s*<td[^>]*>0</td>", page.text
    )
    assert gitio.run(["rev-parse", "HEAD"], cwd=root).stdout == before
    assert _clean(root)
    assert not (root / "imports").exists() or not list((root / "imports").iterdir())


def test_the_review_agrees_with_the_commands_dry_run(tmp_path: Path) -> None:
    root = _review(tmp_path)
    client = _client(root)
    _record_search(client)
    export = tmp_path / "m.ris"
    export.write_text(_RIS_TWO, encoding="utf-8")
    cli = CliRunner().invoke(
        cli_app,
        ["--json", "-C", str(root), "import", str(export), "--by", "ethan", "--search"]
        + ["S-01-medline", "--dry-run"],
    )
    dry = json.loads(cli.output)[0]

    page = client.get(f"/import/review/{_stage(client, [('m.ris', _RIS_TWO.encode())])}").text

    row = re.search(
        r"<td[^>]*>(\d+)</td>\s*<td[^>]*>(\d+)</td>\s*<td[^>]*>(\d+)</td>\s*<td[^>]*>(\d+)</td>",
        page,
    )
    assert row is not None
    assert tuple(int(g) for g in row.groups()) == (
        dry["rows_read"],
        dry["records_created"],
        dry["existing_ids_appended"],
        dry["rows_rejected"],
    )


def test_a_file_already_imported_is_recognised_at_review(tmp_path: Path) -> None:
    root = _review(tmp_path)
    client = _client(root)
    _record_search(client)
    first = _stage(client, [("m.ris", _RIS.encode())])
    _post(client, f"/import/review/{first}", {"rationale": _WHY})
    before = len(gitio.log(root))

    again = _stage(client, [("same-again.ris", _RIS.encode())])
    page = client.get(f"/import/review/{again}").text

    assert 'data-testid="already-imported"' in page and "imp_" in page
    assert "Nothing here can be imported" in page
    assert len(gitio.log(root)) == before


def test_rejected_rows_are_listed_with_their_reasons(tmp_path: Path) -> None:
    root = _review(tmp_path)
    client = _client(root)
    _record_search(client)
    scopus = (_FIXTURES / "csv" / "scopus-malformed.csv").read_bytes()
    expected = json.loads((_FIXTURES / "csv" / "scopus-malformed.expected.json").read_text())

    batch = _stage(client, [("scopus.csv", scopus)])
    page = client.get(f"/import/review/{batch}").text

    assert 'data-testid="rejected-rows"' in page
    rejected = expected.get("rejected") or expected.get("rows_rejected")
    assert rejected  # the fixture is only useful if it really has rejected rows
    assert "recognised as a scopus export" in page
    assert "Rows that cannot be used" in page


def test_an_unrecognised_csv_asks_which_column_is_which(tmp_path: Path) -> None:
    root = _review(tmp_path)
    client = _client(root)
    _record_search(client)
    batch = _stage(client, [("custom.csv", _CUSTOM_CSV.encode())])

    page = client.get(f"/import/review/{batch}").text

    assert "match no known database export" in page
    assert 'name="map_0_title"' in page and '<option value="MyTitle"' in page
    assert "could not detect a known export platform" in page
    assert "Nothing here can be imported" in page


def test_choosing_the_columns_gives_a_preview_and_carries_the_choice_to_the_import(
    tmp_path: Path,
) -> None:
    root = _review(tmp_path)
    client = _client(root)
    _record_search(client)
    batch = _stage(client, [("custom.csv", _CUSTOM_CSV.encode())])

    page = client.get(
        f"/import/review/{batch}?map_0_title=MyTitle&map_0_author=MyAuthor&map_0_year=MyYear"
    ).text

    assert re.search(r"<td[^>]*>2</td>\s*<td[^>]*>2</td>\s*<td[^>]*>0</td>\s*<td[^>]*>0</td>", page)
    confirm = page.split('id="confirm-form"')[1].split("</form>")[0]
    assert '<input type="hidden" name="map_0_title" value="MyTitle">' in confirm
    assert '<input type="hidden" name="map_0_author" value="MyAuthor">' in confirm
    assert "Import 1 file" in confirm


def test_the_choices_form_never_carries_the_session_token(tmp_path: Path) -> None:
    root = _review(tmp_path)
    client = _client(root)
    _record_search(client)
    batch = _stage(client, [("custom.csv", _CUSTOM_CSV.encode())])

    page = client.get(f"/import/review/{batch}").text

    preview = page.split('id="preview-form"')[1].split("</form>")[0]
    assert "csrf_token" not in preview and _TOKEN not in preview
    assert f'<form method="get" action="/import/review/{batch}" id="preview-form">' in page


def test_a_workbook_with_several_sheets_lets_the_person_choose_one(tmp_path: Path) -> None:
    root = _review(tmp_path)
    client = _client(root)
    _record_search(client)
    book = build_xlsx(
        {
            "Export": [["MyTitle", "MyAuthor"], ["A Title", "Doe"]],
            "Other": [["Other title", "Other author"], ["B Title", "Roe"]],
        }
    )
    batch = _stage(client, [("export.xlsx", book)])

    first = client.get(f"/import/review/{batch}").text
    second = client.get(f"/import/review/{batch}?sheet_0=Other").text

    assert 'name="sheet_0"' in first and '<option value="Export" selected>' in first
    assert '<option value="Other" selected>' in second
    assert '<option value="Other title"' in second and '<option value="MyTitle"' not in second


def test_a_corrupt_workbook_is_reported_and_the_search_stays_recorded(tmp_path: Path) -> None:
    root = _review(tmp_path)
    client = _client(root)
    _record_search(client)
    batch = _stage(client, [("broken.xlsx", b"this is not a workbook")])

    page = client.get(f"/import/review/{batch}").text

    assert "not an .xlsx workbook" in page and "This file will not be imported" in page
    assert (root / "protocol" / "searches" / "S-01-medline.yaml").exists()


def test_an_unknown_or_expired_batch_is_not_found(tmp_path: Path) -> None:
    root = _review(tmp_path)
    client = _client(root)

    assert client.get("/import/review/" + "A" * 22).status_code == 404
    assert client.get("/import/review/not-an-id").status_code == 404
    assert client.get("/import/review/..%2F..%2Fetc").status_code in (404, 422)


def test_a_batch_that_has_expired_asks_for_the_file_again(tmp_path: Path) -> None:
    root = _review(tmp_path)
    client = _client(root)
    _record_search(client)
    batch = _stage(client, [("m.ris", _RIS.encode())])
    meta_path = root / ".strata" / "tmp" / "uploads" / batch / "batch.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta["created"] -= uploads.BATCH_TTL_SECONDS + 10
    meta_path.write_text(json.dumps(meta), encoding="utf-8")

    response = client.get(f"/import/review/{batch}")

    assert response.status_code == 410 and "please upload the file again" in response.text


# ---------------------------------------------------------------------------- 4.4 confirming


def test_confirming_imports_each_file_separately_with_the_commands_commits(
    tmp_path: Path,
) -> None:
    root = _review(tmp_path)
    client = _client(root)
    _record_search(client)
    batch = _stage(
        client,
        [
            ("a.ris", b"TY  - JOUR\nTI  - Alpha\nDO  - 10.1000/a\nER  - \n"),
            ("b.ris", b"TY  - JOUR\nTI  - Beta\nDO  - 10.1000/b\nER  - \n"),
        ],
    )
    before = len(gitio.log(root))

    response = _post(client, f"/import/review/{batch}", {"rationale": _WHY})

    assert response.status_code == 200, response.text
    assert len(gitio.log(root)) == before + 2
    assert [re.sub(r"imp_\w+", "<ID>", s) for s in _subjects(root, 2)] == [
        "import(<ID>): import b.ris",
        "import(<ID>): import a.ris",
    ]
    message = _head(root)
    assert "Strata-Op: import" in message and "Strata-Actor: ethan" in message
    assert _WHY in message
    assert _clean(root)
    text = _squash(response.text)
    assert "a.ris" in text and "b.ris" in text and "1 new, 0 matched existing, 0 rejected" in text
    assert _staged(root) == []
    detail = client.get("/searches/S-01-medline").text
    assert "a.ris" in detail and "b.ris" in detail


def test_confirming_twice_does_not_import_twice(tmp_path: Path) -> None:
    root = _review(tmp_path)
    client = _client(root)
    _record_search(client)
    batch = _stage(client, [("m.ris", _RIS.encode())])
    _post(client, f"/import/review/{batch}", {"rationale": _WHY})
    after_first = len(gitio.log(root))

    second = _post(client, f"/import/review/{batch}", {"rationale": _WHY})

    assert second.status_code == 404
    assert len(gitio.log(root)) == after_first


def test_a_failing_file_does_not_stop_the_others_and_the_search_stays(tmp_path: Path) -> None:
    root = _review(tmp_path)
    client = _client(root)
    _record_search(client)
    batch = _stage(
        client,
        [
            ("broken.xlsx", b"nope"),
            ("good.ris", _RIS.encode()),
            ("custom.csv", _CUSTOM_CSV.encode()),
        ],
    )

    response = _post(client, f"/import/review/{batch}", {"rationale": _WHY})
    text = _squash(response.text)

    assert response.status_code == 200
    assert "Not imported" in text and "not an .xlsx workbook" in text
    assert "could not detect a known export platform" in text  # the CSV had no mapping
    assert "good.ris" in text and "Imported as" in text
    assert len(_subjects(root, 3)) == 3 and "import good.ris" in _subjects(root, 1)[0]
    assert (root / "protocol" / "searches" / "S-01-medline.yaml").exists()
    assert _clean(root)


def test_a_chosen_mapping_is_applied_as_the_commands_map_option_is(tmp_path: Path) -> None:
    root = _review(tmp_path)
    client = _client(root)
    _record_search(client)
    batch = _stage(client, [("custom.csv", _CUSTOM_CSV.encode())])

    response = _post(
        client,
        f"/import/review/{batch}",
        {"rationale": _WHY, "map_0_title": "MyTitle", "map_0_author": "MyAuthor"},
    )

    assert response.status_code == 200 and "2 new" in _squash(response.text)
    manifest = next((root / "imports").glob("*/manifest.yaml")).read_text(encoding="utf-8")
    assert "title: MyTitle" in manifest and "author: MyAuthor" in manifest


def test_a_chosen_sheet_is_the_one_imported(tmp_path: Path) -> None:
    root = _review(tmp_path)
    client = _client(root)
    _record_search(client)
    book = build_xlsx(
        {
            "Export": [["MyTitle"], ["From the first sheet"]],
            "Other": [["MyTitle"], ["From the second sheet"]],
        }
    )
    batch = _stage(client, [("export.xlsx", book)])

    _post(
        client,
        f"/import/review/{batch}",
        {"rationale": _WHY, "sheet_0": "Other", "map_0_title": "MyTitle"},
    )

    records = (root / "records" / "records.ndjson").read_text(encoding="utf-8")
    assert "From the second sheet" in records and "From the first sheet" not in records
    assert "sheet: Other" in next((root / "imports").glob("*/manifest.yaml")).read_text(
        encoding="utf-8"
    )


@pytest.mark.parametrize("rationale", ["", "update"])
def test_confirming_without_a_usable_rationale_imports_nothing_and_keeps_the_batch(
    tmp_path: Path, rationale: str
) -> None:
    root = _review(tmp_path)
    client = _client(root)
    _record_search(client)
    batch = _stage(client, [("m.ris", _RIS.encode())])
    before = len(gitio.log(root))

    response = _post(client, f"/import/review/{batch}", {"rationale": rationale})

    assert response.status_code == 422 and 'data-testid="form-error"' in response.text
    assert len(gitio.log(root)) == before and _clean(root)
    assert _staged(root) == [batch]


def test_an_already_imported_file_in_a_confirmation_changes_nothing(tmp_path: Path) -> None:
    root = _review(tmp_path)
    client = _client(root)
    _record_search(client)
    first = _stage(client, [("m.ris", _RIS.encode())])
    _post(client, f"/import/review/{first}", {"rationale": _WHY})
    before = len(gitio.log(root))
    again = _stage(client, [("m-again.ris", _RIS.encode())])

    response = _post(client, f"/import/review/{again}", {"rationale": _WHY})

    assert "Already imported as" in _squash(response.text) and "nothing changed" in response.text
    assert len(gitio.log(root)) == before


def test_confirming_while_the_lock_is_held_keeps_the_batch_and_writes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _review(tmp_path)
    client = _client(root)
    _record_search(client)
    batch = _stage(client, [("m.ris", _RIS.encode())])
    real = ops.repo_lock
    monkeypatch.setattr(ops, "repo_lock", lambda r, timeout: real(r, timeout=0.2))

    with repo_lock(open_repo(root)):
        response = _post(client, f"/import/review/{batch}", {"rationale": _WHY})

    assert response.status_code == 503 and "repository is locked" in response.text
    assert _staged(root) == [batch] and _clean(root)


def test_discarding_removes_the_batch_and_leaves_the_search(tmp_path: Path) -> None:
    root = _review(tmp_path)
    client = _client(root)
    _record_search(client)
    batch = _stage(client, [("m.ris", _RIS.encode())])
    before = len(gitio.log(root))

    response = _post(client, f"/import/review/{batch}/discard")

    assert response.status_code == 303 and response.headers["location"] == "/searches/S-01-medline"
    assert _staged(root) == [] and len(gitio.log(root)) == before


def test_uploading_to_a_search_that_does_not_exist_is_a_404(tmp_path: Path) -> None:
    client = _client(_review(tmp_path))

    assert (
        _post(client, "/searches/S-99-nothing/files", files=[("m.ris", _RIS.encode())]).status_code
        == 404
    )


def test_uploading_no_file_to_a_search_says_so(tmp_path: Path) -> None:
    client = _client(_review(tmp_path))
    _record_search(client)

    response = _post(client, "/searches/S-01-medline/files", files=[("", b"")])

    assert response.status_code == 422 and "Choose at least one file" in response.text


def test_a_pdf_uploaded_to_a_search_is_refused_and_nothing_is_staged(tmp_path: Path) -> None:
    root = _review(tmp_path)
    client = _client(root)
    _record_search(client)

    response = _post(client, "/searches/S-01-medline/files", files=[("paper.pdf", b"%PDF-1.7 x")])

    assert response.status_code == 422 and "does not store full texts" in response.text
    assert _staged(root) == []


# ------------------------------------------------------------------ 4.5 other methods of finding


def test_the_other_methods_page_lists_the_methods(tmp_path: Path) -> None:
    page = _client(_review(tmp_path)).get("/import").text

    for method in ("citation-searching", "website", "organisation", "registry", "contact"):
        assert f'value="{method}"' in page


def test_importing_from_a_registry_counts_as_the_commands_via_registry_does(tmp_path: Path) -> None:
    web_root = _review(tmp_path, "web")
    cli_root = _review(tmp_path, "cli")
    client = _client(web_root)
    export = tmp_path / "registry.ris"
    export.write_text(_RIS_TWO, encoding="utf-8")

    start = _post(
        client, "/import", {"via": "registry"}, files=[("registry.ris", _RIS_TWO.encode())]
    )
    review = client.get(f"/import/review/{_batch_of(start)}").text
    assert "A trial or study registry" in review
    done = _post(client, start.headers["location"], {"rationale": _WHY})
    assert done.status_code == 200 and "2 new" in _squash(done.text)

    cli = CliRunner().invoke(
        cli_app,
        [
            "--why",
            _WHY,
            "-C",
            str(cli_root),
            "import",
            str(export),
            "--by",
            "ethan",
            "--via",
            "registry",
        ],
    )
    assert cli.exit_code == 0, cli.output

    web_counts = json.loads((web_root / "derived" / "counts.json").read_text(encoding="utf-8"))
    cli_counts = json.loads((cli_root / "derived" / "counts.json").read_text(encoding="utf-8"))
    assert web_counts == cli_counts
    assert "registry" in json.dumps(web_counts)


def test_an_import_with_no_method_is_refused_in_the_commands_words(tmp_path: Path) -> None:
    root = _review(tmp_path)
    client = _client(root)

    response = _post(client, "/import", {"via": ""}, files=[("m.ris", _RIS.encode())])

    assert response.status_code == 422
    assert "exactly one of --search or --via is required" in response.text
    assert _staged(root) == []


def test_an_import_with_an_invented_method_is_refused(tmp_path: Path) -> None:
    client = _client(_review(tmp_path))

    response = _post(client, "/import", {"via": "carrier-pigeon"}, files=[("m.ris", _RIS.encode())])

    assert response.status_code == 422
    assert "invalid --via 'carrier-pigeon'" in html.unescape(response.text)


def test_an_import_with_a_method_but_no_file_says_so(tmp_path: Path) -> None:
    client = _client(_review(tmp_path))

    response = _post(client, "/import", {"via": "website"}, files=[("", b"")])

    assert response.status_code == 422 and "Choose at least one file" in response.text


def test_discarding_an_other_methods_upload_goes_back_to_the_import_page(tmp_path: Path) -> None:
    root = _review(tmp_path)
    client = _client(root)
    start = _post(client, "/import", {"via": "website"}, files=[("m.ris", _RIS.encode())])
    batch = _batch_of(start)

    response = _post(client, f"/import/review/{batch}/discard")

    assert response.headers["location"] == "/import" and _staged(root) == []
