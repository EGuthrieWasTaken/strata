"""`strata.core.operations`: the search and import operations the command line and the web share.

Covers openspec:architecture#mutating-operations-are-shared-services for searches and imports:
the same inputs through `strata` and through the operation leave the same files and the same commit
messages, a rationale that cannot be used is refused before anything is written, and the
subject-length limit no longer turns a long file name or database name into a crash after the
files are written.
"""

import json
import re
from pathlib import Path

import pytest
from typer.testing import CliRunner

from strata import gitio
from strata.cli.main import EXIT_OK, app
from strata.core import operations as ops
from strata.core.commit import RationaleRejectedError
from strata.core.init import init_repository
from strata.core.repo import Repo, open_repo
from strata.ingest.pipeline import ImportPipelineError
from strata.protocol.searches import SearchError

runner = CliRunner()

_IMPORT_ID = re.compile(r"imp_[0-9a-z]{26}")
_EVENT_ID = re.compile(r"ev_[0-9a-z]{26}")
_TIMESTAMP = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z")
_PAPERS = json.dumps(
    [
        {"title": "First paper", "DOI": "10.1000/aaa"},
        {"title": "Second paper", "DOI": "10.1000/bbb"},
    ]
)
_WHY = "recording the search for the equivalence test"


def _init(tmp_path: Path, name: str = "review") -> Repo:
    root = tmp_path / name
    init_repository(root, title="Test Review", actor_handle="ethan", actor_name="Ethan")
    return open_repo(root)


def _search(repo: Repo, **overrides: object) -> ops.SearchRecorded:
    args: dict[str, object] = {
        "database": "MEDLINE",
        "platform": "Ovid",
        "executed": "2026-03-04",
        "executed_by": "ethan",
        "query": "1 exp Learning/",
        "hits": 4182,
        "export_files": ["medline.ris"],
        "rationale": _WHY,
    }
    args.update(overrides)
    return ops.record_search(repo, **args)  # type: ignore[arg-type]


def _export(tmp_path: Path, name: str = "export.json", text: str = _PAPERS) -> Path:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def _head(repo: Repo) -> str:
    return gitio.run(["log", "-1", "--format=%B"], cwd=repo.root).stdout


def _count(repo: Repo) -> int:
    return len(gitio.log(repo.root))


def _status(repo: Repo) -> list[str]:
    out = gitio.run(["status", "--porcelain", "--untracked-files=all"], cwd=repo.root).stdout
    return [line for line in out.splitlines() if line]


def _as_cli(tmp_path: Path, name: str) -> Repo:
    root = tmp_path / name
    result = runner.invoke(
        app,
        ["init", str(root), "--title", "Test Review", "--actor", "ethan", "--actor-name", "Ethan"],
    )
    assert result.exit_code == EXIT_OK, result.output
    return open_repo(root)


# ------------------------------------------------------------------------ rationale rules


def test_rationale_problem_names_what_is_wrong(tmp_path: Path) -> None:
    repo = _init(tmp_path)

    assert ops.rationale_problem(repo, None) == "a rationale is required for this operation"
    assert ops.rationale_problem(repo, "   ") == "a rationale is required for this operation"
    assert ops.rationale_problem(repo, "update") is not None
    assert ops.rationale_problem(repo, "short one") is not None
    assert ops.rationale_problem(repo, "a genuinely explanatory rationale") is None


def test_rationale_problem_is_silent_when_a_review_does_not_require_one(tmp_path: Path) -> None:
    repo = _init(tmp_path)
    repo.config["git"]["require_rationale"] = False

    assert ops.rationale_problem(repo, None) is None
    assert ops.rationale_problem(repo, None, always=True) is not None
    # A rationale that is given is still checked.
    assert ops.rationale_problem(repo, "update") is not None


@pytest.mark.parametrize("bad", [None, "update", "   ", "short one"])
def test_record_search_refuses_an_unusable_rationale_before_writing(
    tmp_path: Path, bad: str | None
) -> None:
    repo = _init(tmp_path)
    before = _count(repo)

    with pytest.raises(RationaleRejectedError):
        _search(repo, rationale=bad)

    assert _count(repo) == before
    assert _status(repo) == []


def test_record_search_asks_for_the_rationale_only_after_the_work_is_written(
    tmp_path: Path,
) -> None:
    repo = _init(tmp_path)
    seen: list[str] = []

    def ask() -> str:
        seen.append("asked")
        assert (repo.root / "protocol" / "searches" / "S-01-medline.yaml").exists()
        return _WHY

    result = _search(repo, rationale=ask, on_written=lambda r: seen.append(r.record["id"]))

    assert seen == ["S-01-medline", "asked"]
    assert result.committed


def test_record_search_without_commit_writes_and_does_not_ask(tmp_path: Path) -> None:
    repo = _init(tmp_path)
    before = _count(repo)

    def never() -> str:
        raise AssertionError("no rationale is needed when nothing is committed")

    result = _search(repo, commit=False, rationale=never)

    assert not result.committed
    assert _count(repo) == before
    assert _status(repo) == ["?? protocol/searches/S-01-medline.yaml"]


def test_a_review_that_does_not_require_a_rationale_commits_without_a_body(
    tmp_path: Path,
) -> None:
    repo = _init(tmp_path)
    repo.config["git"]["require_rationale"] = False

    _search(repo, rationale=None)

    assert _head(repo).splitlines()[:2] == [
        "search-add(S-01-medline): record search S-01-medline",
        "",
    ]
    assert "Strata-Op: search-add" in _head(repo)


def test_domain_errors_propagate_and_write_nothing(tmp_path: Path) -> None:
    repo = _init(tmp_path)
    _search(repo)
    before = _count(repo)

    with pytest.raises(SearchError, match="already exists"):
        _search(repo, search_id="S-01-medline")

    assert _count(repo) == before
    assert _status(repo) == []


# -------------------------------------------------------------------------- long names


def test_a_long_export_file_name_no_longer_breaks_the_import_commit(tmp_path: Path) -> None:
    repo = _init(tmp_path)
    _search(repo)
    name = "medline-export-2026-10-01-final-v2.ris"
    export = _export(tmp_path, name, "TY  - JOUR\nTI  - A title\nER  - \n")

    result = ops.import_file(
        repo, export, imported_by="ethan", search_id="S-01-medline", rationale=_WHY
    )

    assert result.committed
    assert _status(repo) == []
    subject = _head(repo).splitlines()[0]
    assert len(subject) <= 72 and subject.startswith("import(imp_")
    # Nothing is lost: the data keep the whole name.
    assert (repo.root / "imports" / result.outcome.import_id / "raw" / name).exists()


def test_a_long_database_name_no_longer_breaks_the_search_commit(tmp_path: Path) -> None:
    repo = _init(tmp_path)

    result = _search(repo, database="Cochrane Central Register of Controlled Trials")

    assert result.committed
    assert _status(repo) == []
    search_id = result.record["id"]
    assert search_id == "S-01-cochrane-central-register-of-controlled-trials"
    message = _head(repo)
    assert len(message.splitlines()[0]) <= 72
    # The trailer carries the whole id.
    assert f"Strata-Search: {search_id}" in message


def test_the_command_line_survives_the_same_long_names(tmp_path: Path) -> None:
    root = _as_cli(tmp_path, "cli").root
    export = _export(tmp_path, "medline-export-2026-10-01-final-v2.ris", "TY  - JOUR\nER  - \n")

    searched = runner.invoke(
        app,
        ["--why", _WHY, "-C", str(root), "search", "add", "--database"]
        + ["Cochrane Central Register of Controlled Trials", "--platform", "Wiley", "--by"]
        + ["ethan", "--query", "q"],
    )
    imported = runner.invoke(
        app,
        ["--why", _WHY, "-C", str(root), "import", str(export), "--by", "ethan", "--search"]
        + ["S-01-cochrane-central-register-of-controlled-trials"],
    )

    assert searched.exit_code == EXIT_OK, searched.output
    assert imported.exit_code == EXIT_OK, imported.output
    assert gitio.run(["status", "--porcelain"], cwd=root).stdout == ""


# ------------------------------------------------------------------------------ imports


def test_importing_a_file_already_imported_needs_no_rationale_and_commits_nothing(
    tmp_path: Path,
) -> None:
    repo = _init(tmp_path)
    _search(repo)
    export = _export(tmp_path)
    ops.import_file(repo, export, imported_by="ethan", search_id="S-01-medline", rationale=_WHY)
    before = _count(repo)

    again = ops.import_file(
        repo, export, imported_by="ethan", search_id="S-01-medline", rationale=None
    )

    assert again.outcome.already_imported and not again.committed
    assert _count(repo) == before
    assert _status(repo) == []


def test_importing_something_new_with_no_rationale_is_refused_before_writing(
    tmp_path: Path,
) -> None:
    repo = _init(tmp_path)
    _search(repo)
    export = _export(tmp_path)
    before = _count(repo)

    with pytest.raises(RationaleRejectedError):
        ops.import_file(repo, export, imported_by="ethan", search_id="S-01-medline")

    assert _count(repo) == before
    assert _status(repo) == []


def test_a_dry_run_writes_nothing_and_asks_for_nothing(tmp_path: Path) -> None:
    repo = _init(tmp_path)
    _search(repo)
    export = _export(tmp_path)
    before = _count(repo)

    result = ops.import_file(
        repo, export, imported_by="ethan", search_id="S-01-medline", dry_run=True
    )

    assert result.outcome.dry_run and result.outcome.records_created == 2
    assert not result.committed
    assert _count(repo) == before
    assert _status(repo) == []


def test_import_without_commit_regenerates_the_counts_and_leaves_the_work_uncommitted(
    tmp_path: Path,
) -> None:
    repo = _init(tmp_path)
    _search(repo)
    before = _count(repo)

    result = ops.import_file(
        repo, _export(tmp_path), imported_by="ethan", search_id="S-01-medline", commit=False
    )

    assert not result.committed
    assert _count(repo) == before
    assert " M derived/counts.json" in _status(repo)


def test_import_files_carries_on_past_a_failure_with_one_commit_per_file(tmp_path: Path) -> None:
    repo = _init(tmp_path)
    _search(repo)
    first = _export(tmp_path, "a.json", '[{"title": "First", "DOI": "10.1000/aaa"}]')
    bad = _export(tmp_path, "b.xyz", "not a bibliography")
    third = _export(tmp_path, "c.json", '[{"title": "Third", "DOI": "10.1000/ccc"}]')
    before = _count(repo)

    items = ops.import_files(
        repo, [first, bad, third], imported_by="ethan", search_id="S-01-medline", rationale=_WHY
    )

    assert [(i.result is not None, i.error is not None) for i in items] == [
        (True, False),
        (False, True),
        (True, False),
    ]
    assert items[1].error == "unsupported file extension '.xyz'; pass --format explicitly"
    assert _count(repo) == before + 2
    assert _status(repo) == []


def test_import_errors_are_the_pipelines(tmp_path: Path) -> None:
    repo = _init(tmp_path)

    with pytest.raises(ImportPipelineError, match="exactly one of"):
        ops.import_file(repo, _export(tmp_path), imported_by="ethan", rationale=_WHY)


# ------------------------------------------------------------------- one action, two surfaces


def _committed_snapshot(repo: Repo) -> dict[str, str]:
    """What HEAD changed, with the parts that legitimately differ between runs masked.

    Masked: generated import and event ids and timestamps, and the hash chain, which covers them.
    Everything else (record ids, manifests, bodies, raw files, commit message) is compared as is.
    """

    def mask(text: str) -> str:
        text = _IMPORT_ID.sub("<IMPORT>", text)
        text = _EVENT_ID.sub("<EVENT>", text)
        text = _TIMESTAMP.sub("<TS>", text)
        return re.sub(r"sha256:[0-9a-f]{64}", "<DIGEST>", text) if '"prev"' in text else text

    names = gitio.run(["show", "--name-only", "--format=", "HEAD"], cwd=repo.root).stdout
    snapshot = {"<message>": mask(_head(repo))}
    for name in sorted(n for n in names.splitlines() if n):
        content = gitio.run(["show", f"HEAD:{name}"], cwd=repo.root).stdout
        if name.startswith("events/"):
            lines = []
            for line in content.splitlines():
                event = json.loads(line)
                lines.append(
                    json.dumps({k: event[k] for k in ("ev", "actor", "body")}, sort_keys=True)
                )
            content = "\n".join(lines)
        snapshot[mask(name)] = mask(content)
    return snapshot


def test_one_search_through_the_command_and_the_operation_is_the_same(tmp_path: Path) -> None:
    via_cli = _as_cli(tmp_path, "cli")
    via_ops = _init(tmp_path, "ops")

    result = runner.invoke(
        app,
        ["--why", _WHY, "-C", str(via_cli.root), "search", "add", "--database", "MEDLINE"]
        + ["--platform", "Ovid", "--by", "ethan", "--executed", "2026-03-04"]
        + ["--query", "1 exp Learning/", "--hits", "4182", "--export-file", "medline.ris"],
    )
    assert result.exit_code == EXIT_OK, result.output
    _search(via_ops)

    assert _committed_snapshot(via_cli) == _committed_snapshot(via_ops)


def test_one_import_through_the_command_and_the_operation_is_the_same(tmp_path: Path) -> None:
    via_cli = _as_cli(tmp_path, "cli")
    via_ops = _init(tmp_path, "ops")
    for repo in (via_cli, via_ops):
        _search(repo)
    export = _export(tmp_path)

    result = runner.invoke(
        app,
        ["--why", _WHY, "-C", str(via_cli.root), "import", str(export), "--by", "ethan"]
        + ["--search", "S-01-medline"],
    )
    assert result.exit_code == EXIT_OK, result.output
    ops.import_file(via_ops, export, imported_by="ethan", search_id="S-01-medline", rationale=_WHY)

    cli_side = _committed_snapshot(via_cli)
    assert cli_side == _committed_snapshot(via_ops)
    # The comparison is not vacuous: it covers the records, the manifest and the raw file.
    assert any(name.endswith("raw/export.json") for name in cli_side)
    assert "records/records.ndjson" in cli_side


def test_the_comparison_notices_a_different_commit_message(tmp_path: Path) -> None:
    via_cli = _as_cli(tmp_path, "cli")
    via_ops = _init(tmp_path, "ops")
    runner.invoke(
        app,
        ["--why", _WHY, "-C", str(via_cli.root), "search", "add", "--database", "MEDLINE"]
        + ["--platform", "Ovid", "--by", "ethan", "--executed", "2026-03-04"]
        + ["--query", "1 exp Learning/", "--hits", "4182", "--export-file", "medline.ris"],
    )
    _search(via_ops, rationale="a different reason for recording the same search")

    assert _committed_snapshot(via_cli) != _committed_snapshot(via_ops)
