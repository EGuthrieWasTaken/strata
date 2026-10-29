"""The shared operations hold the repository lock
(openspec:architecture#concurrency-and-locking; OpenSpec change `add-web-ui-write-surfaces`,
tasks 2.2 and 2.3).

The multi-process tests run the real command in real processes: contention between a command line
and a web server is exactly this, and two `git commit`s in one repository collide on its index lock
unless something serialises them.
"""

import json
import subprocess
import sys
import time
from pathlib import Path

import pytest
from typer.testing import CliRunner

from strata import gitio
from strata.cli.main import EXIT_GENERIC, EXIT_OK, app
from strata.core import operations as ops
from strata.core.init import init_repository
from strata.core.repo import LockTimeoutError, Repo, open_repo, repo_lock

runner = CliRunner()

_WHY = "recording a search while another writer is busy"

_HOLD = """
import sys, time
from pathlib import Path
from strata.core.repo import Repo, repo_lock

with repo_lock(Repo(root=Path(sys.argv[1]), config={})):
    Path(sys.argv[2]).write_text("holding", encoding="utf-8")
    time.sleep(float(sys.argv[3]))
"""

_RUN_STRATA = "import sys; from strata.cli.main import app; app()"


def _init(tmp_path: Path) -> Repo:
    root = tmp_path / "review"
    init_repository(root, title="Test Review", actor_handle="ethan", actor_name="Ethan")
    return open_repo(root)


def _status(repo: Repo) -> str:
    return gitio.run(["status", "--porcelain", "--untracked-files=all"], cwd=repo.root).stdout


def _search_args(database: str) -> list[str]:
    return [
        "--why",
        _WHY,
        "search",
        "add",
        "--database",
        database,
        "--platform",
        "Ovid",
        "--by",
        "ethan",
        "--query",
        "q",
    ]


def _strata(root: Path, *args: str) -> subprocess.Popen[bytes]:
    return subprocess.Popen(
        [sys.executable, "-c", _RUN_STRATA, "-C", str(root), *args],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )


def _wait_for(path: Path, seconds: float = 60) -> None:
    deadline = time.monotonic() + seconds
    while not path.exists():
        assert time.monotonic() < deadline, f"{path.name} never appeared"
        time.sleep(0.05)


# ------------------------------------------------------------------------- across processes


def test_a_command_waits_for_another_process_holding_the_lock_and_then_succeeds(
    tmp_path: Path,
) -> None:
    repo = _init(tmp_path)
    ready = tmp_path / "ready"
    hold_seconds = 6
    holder = subprocess.Popen(
        [sys.executable, "-c", _HOLD, str(repo.root), str(ready), str(hold_seconds)]
    )
    try:
        _wait_for(ready)
        started = time.monotonic()
        writer = _strata(repo.root, *_search_args("MEDLINE"))
        out, _ = writer.communicate(timeout=120)
        waited = time.monotonic() - started
        holder.wait(timeout=60)
    finally:
        for process in (holder,):
            if process.poll() is None:
                process.kill()

    assert writer.returncode == EXIT_OK, out.decode()
    # It cannot have finished before the holder let go, however long its own start-up took.
    assert waited >= hold_seconds - 1
    assert (repo.root / "protocol" / "searches" / "S-01-medline.yaml").exists()
    assert _status(repo) == ""


def test_four_commands_at_once_all_succeed_with_one_commit_each(tmp_path: Path) -> None:
    repo = _init(tmp_path)
    before = len(gitio.log(repo.root))
    databases = ["MEDLINE", "Embase", "PsycINFO", "Scopus"]

    writers = [_strata(repo.root, *_search_args(db)) for db in databases]
    outputs = [(w.communicate(timeout=300)[0].decode(), w.returncode) for w in writers]

    assert [code for _out, code in outputs] == [EXIT_OK] * 4, outputs
    assert len(gitio.log(repo.root)) == before + 4
    assert sorted(p.name for p in (repo.root / "protocol" / "searches").glob("*.yaml")) == [
        "S-01-embase.yaml",
        "S-01-medline.yaml",
        "S-01-psycinfo.yaml",
        "S-01-scopus.yaml",
    ]
    assert _status(repo) == ""


# ---------------------------------------------------------------------------- the operations


def test_an_operation_that_cannot_get_the_lock_writes_nothing(tmp_path: Path) -> None:
    repo = _init(tmp_path)
    before = len(gitio.log(repo.root))

    with repo_lock(repo), pytest.raises(LockTimeoutError, match="held by process"):
        ops.record_search(
            repo,
            database="MEDLINE",
            platform="Ovid",
            executed="2026-03-04",
            executed_by="ethan",
            query="q",
            rationale=_WHY,
            lock_timeout=0.2,
        )

    assert len(gitio.log(repo.root)) == before
    assert not (repo.root / "protocol" / "searches" / "S-01-medline.yaml").exists()
    assert _status(repo) == ""


def test_an_import_waits_for_the_lock_before_it_writes_anything(tmp_path: Path) -> None:
    repo = _init(tmp_path)
    export = tmp_path / "export.json"
    export.write_text(json.dumps([{"title": "A paper", "DOI": "10.1000/aaa"}]), encoding="utf-8")
    ops.record_search(
        repo,
        database="MEDLINE",
        platform="Ovid",
        executed="2026-03-04",
        executed_by="ethan",
        query="q",
        rationale=_WHY,
    )

    with repo_lock(repo), pytest.raises(LockTimeoutError):
        ops.import_file(
            repo,
            export,
            imported_by="ethan",
            search_id="S-01-medline",
            rationale=_WHY,
            lock_timeout=0.2,
        )

    assert not (repo.root / "imports").exists() or not list((repo.root / "imports").iterdir())
    assert _status(repo) == ""


def test_a_dry_run_and_the_pre_check_do_not_need_the_lock(tmp_path: Path) -> None:
    repo = _init(tmp_path)
    export = tmp_path / "export.json"
    export.write_text(json.dumps([{"title": "A paper", "DOI": "10.1000/aaa"}]), encoding="utf-8")
    ops.record_search(
        repo,
        database="MEDLINE",
        platform="Ovid",
        executed="2026-03-04",
        executed_by="ethan",
        query="q",
        rationale=_WHY,
    )

    with repo_lock(repo):
        dry = ops.import_file(
            repo,
            export,
            imported_by="ethan",
            search_id="S-01-medline",
            dry_run=True,
            lock_timeout=0.2,
        )
        would = ops.would_import_anything(
            repo, [export], imported_by="ethan", search_id="S-01-medline"
        )

    assert dry.outcome.records_created == 1 and would is True


def test_a_result_says_when_the_lock_was_left_by_a_process_that_died(tmp_path: Path) -> None:
    repo = _init(tmp_path)
    lock_path = repo.root / ".strata" / "lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path.write_text("999999\n", encoding="ascii")

    recorded = ops.record_search(
        repo,
        database="MEDLINE",
        platform="Ovid",
        executed="2026-03-04",
        executed_by="ethan",
        query="q",
        rationale=_WHY,
    )

    assert recorded.lock_reclaimed_from == 999999
    assert not lock_path.exists()
    assert _status(repo) == ""


# --------------------------------------------------------------------------------- the command


def test_the_command_says_so_when_it_takes_over_a_dead_processs_lock(tmp_path: Path) -> None:
    repo = _init(tmp_path)
    lock_path = repo.root / ".strata" / "lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path.write_text("999999\n", encoding="ascii")

    result = runner.invoke(app, ["-C", str(repo.root), *_search_args("MEDLINE")])

    assert result.exit_code == EXIT_OK, result.output
    text = " ".join(result.output.split())
    assert "the repository lock was left by process 999999" in text
    assert "recorded search S-01-medline" in text


def test_the_command_reports_a_lock_that_stays_held(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _init(tmp_path)
    real_lock = ops.repo_lock
    monkeypatch.setattr(ops, "repo_lock", lambda r, timeout: real_lock(r, timeout=0.2))

    with repo_lock(repo):
        result = runner.invoke(app, ["-C", str(repo.root), *_search_args("MEDLINE")])

    assert result.exit_code == EXIT_GENERIC
    assert "repository is locked (held by process" in " ".join(result.output.split())
    assert _status(repo) == ""


def test_a_dry_run_import_works_while_the_lock_is_held(tmp_path: Path) -> None:
    repo = _init(tmp_path)
    export = tmp_path / "export.json"
    export.write_text(json.dumps([{"title": "A paper", "DOI": "10.1000/aaa"}]), encoding="utf-8")
    runner.invoke(app, ["-C", str(repo.root), *_search_args("MEDLINE")])

    with repo_lock(repo):
        result = runner.invoke(
            app,
            ["-C", str(repo.root), "import", str(export), "--by", "ethan", "--search"]
            + ["S-01-medline", "--dry-run"],
        )

    assert result.exit_code == EXIT_OK, result.output
    assert "would import" in result.output
