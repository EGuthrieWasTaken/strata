"""The web interface and the command line leave the same thing in git
(openspec:web-ui#write-screens-match-the-command-line; OpenSpec change `add-web-ui-write-surfaces`,
task 4.7).

Two identical reviews, one search and one import made once with `strata` and once at the web
interface: the search files, commit messages and trailers, records, import manifests, events and
PRISMA counts must be the same apart from generated ids and timestamps.
"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
from typer.testing import CliRunner

from strata import gitio
from strata.cli.main import EXIT_OK, app
from strata.core.init import init_repository
from strata.web.app import create_app
from tests.integration._equivalence import committed_snapshot

runner = CliRunner()
_TOKEN = "test-session-token-0123456789"
_WHY = "recorded for the equivalence test"
_RIS = (
    "TY  - JOUR\nTI  - Spacing effects in learning\nAU  - Cepeda, Nicholas J.\nPY  - 2008\n"
    "JO  - Psychological Science\nDO  - 10.1111/j.1467-9280.2008.02209.x\nER  - \n"
    "TY  - JOUR\nTI  - Retrieval practice\nAU  - Roediger, Henry L.\nPY  - 2006\n"
    "DO  - 10.1111/j.1467-8721.2006.00415.x\nER  - \n"
)
_SEARCH = {
    "database": "MEDLINE",
    "platform": "Ovid",
    "executed": "2026-03-04",
    "executed_by": "ethan",
    "query": "1 exp Learning/",
    "hits": "4182",
}


def _review(tmp_path: Path, name: str) -> Path:
    root = tmp_path / name
    init_repository(root, title="Equivalence", actor_handle="ethan", actor_name="Ethan")
    return root


def _web(root: Path) -> TestClient:
    client = TestClient(
        create_app(repo_root=root, actor="ethan", session_token=_TOKEN),
        base_url="http://127.0.0.1:8000",
    )
    assert client.get(f"/?token={_TOKEN}").status_code == 200
    return client


def _post(client: TestClient, path: str, data: dict[str, str], files=None):  # type: ignore[no-untyped-def]
    return client.post(
        path, data={"csrf_token": _TOKEN, **data}, files=files, follow_redirects=False
    )


def _cli_search(root: Path, export_name: str | None) -> None:
    args = ["--why", _WHY, "-C", str(root), "search", "add", "--database", "MEDLINE"]
    args += ["--platform", "Ovid", "--by", "ethan", "--executed", "2026-03-04"]
    args += ["--query", "1 exp Learning/", "--hits", "4182"]
    if export_name:
        args += ["--export-file", export_name]
    result = runner.invoke(app, args)
    assert result.exit_code == EXIT_OK, result.output


def test_one_search_is_the_same_from_either_surface(tmp_path: Path) -> None:
    via_cli = _review(tmp_path, "cli")
    via_web = _review(tmp_path, "web")
    _cli_search(via_cli, None)

    response = _post(_web(via_web), "/searches", {**_SEARCH, "rationale": _WHY})

    assert response.status_code == 303
    assert committed_snapshot(via_cli) == committed_snapshot(via_web)
    snapshot = committed_snapshot(via_web)
    assert "protocol/searches/S-01-medline.yaml" in snapshot
    assert "Strata-Search: S-01-medline" in snapshot["<message>"]


def test_one_import_is_the_same_from_either_surface(tmp_path: Path) -> None:
    via_cli = _review(tmp_path, "cli")
    via_web = _review(tmp_path, "web")
    export = tmp_path / "medline.ris"
    export.write_bytes(_RIS.encode())  # bytes: text mode would turn "\n" into "\r\n" on Windows
    _cli_search(via_cli, None)
    result = runner.invoke(
        app,
        ["--why", _WHY, "-C", str(via_cli), "import", str(export), "--by", "ethan", "--search"]
        + ["S-01-medline"],
    )
    assert result.exit_code == EXIT_OK, result.output

    client = _web(via_web)
    _post(client, "/searches", {**_SEARCH, "rationale": _WHY})
    start = _post(
        client,
        "/searches/S-01-medline/files",
        {},
        files=[("files", ("medline.ris", _RIS.encode(), "application/octet-stream"))],
    )
    done = _post(client, start.headers["location"], {"rationale": _WHY})

    assert done.status_code == 200
    web_side = committed_snapshot(via_web)
    assert committed_snapshot(via_cli) == web_side
    # Not vacuous: the comparison covers the records, the manifest, the raw file and the counts.
    names = set(web_side)
    assert {"records/records.ndjson", "derived/counts.json"} <= names
    assert any(n.endswith("/manifest.yaml") for n in names)
    assert any(n.endswith("/raw/medline.ris") for n in names)
    assert any(n.startswith("events/import/") for n in names)


def test_a_search_with_its_export_is_the_same_two_commits_from_either_surface(
    tmp_path: Path,
) -> None:
    via_cli = _review(tmp_path, "cli")
    via_web = _review(tmp_path, "web")
    export = tmp_path / "medline.ris"
    export.write_bytes(_RIS.encode())  # bytes: text mode would turn "\n" into "\r\n" on Windows
    _cli_search(via_cli, "medline.ris")
    runner.invoke(
        app,
        ["--why", _WHY, "-C", str(via_cli), "import", str(export), "--by", "ethan", "--search"]
        + ["S-01-medline"],
    )

    client = _web(via_web)
    start = _post(
        client,
        "/searches",
        {**_SEARCH, "rationale": _WHY},
        files=[("files", ("medline.ris", _RIS.encode(), "application/octet-stream"))],
    )
    _post(client, start.headers["location"], {"rationale": _WHY})

    for revision in ("HEAD", "HEAD~1"):
        assert committed_snapshot(via_cli, revision) == committed_snapshot(via_web, revision)
    assert len(gitio.log(via_cli)) == len(gitio.log(via_web))
