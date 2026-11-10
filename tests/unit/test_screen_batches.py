"""`strata.core.screen_batches`: finding, committing and flushing pending screening decisions."""

from __future__ import annotations

from pathlib import Path

import pytest

from strata import gitio
from strata.core.actor import add_actor
from strata.core.init import init_repository
from strata.core.records import write_records
from strata.core.repo import Repo, open_repo
from strata.core.screen_batches import (
    BROWSER_BODY,
    _actor_of,
    batch_identities,
    commit_screening_batch,
    flush_pending_screening,
    flush_under_lock,
    pending_screening_actors,
    pending_screening_files,
)
from strata.protocol.criteria import add_criterion
from strata.protocol.screening import record_screen_decision
from strata.web.app import needs_screening_flush

_IDS = ("rec_0000000000000001", "rec_0000000000000002", "rec_0000000000000003")


def _record(record_id: str) -> dict:  # type: ignore[type-arg]
    return {
        "id": record_id,
        "type": "article-journal",
        "title": f"Title of {record_id}",
        "strata": {
            "canonical_key": f"sig:{record_id}",
            "canonical": True,
            "sources": [{"import": "imp_01arz3ndektsv4rrffq69g5fav"}],
        },
    }


def _repo(tmp_path: Path) -> Repo:
    """A committed review with ethan and sam, one exclusion criterion and three records."""
    root = tmp_path / "review"
    init_repository(root, title="Batches", actor_handle="ethan", actor_name="Ethan Guthrie")
    add_actor(open_repo(root), handle="sam", name="Sam Okonkwo", role="screener")
    add_criterion(
        open_repo(root),
        kind="exclusion",
        label="Not empirical",
        definition="Not an empirical study.",
        applies_at=["title-abstract"],
        actor="ethan",
        rationale="Establishing the initial protocol criteria.",
        criterion_id="EXC-01",
    )
    write_records(open_repo(root), [_record(r) for r in _IDS])
    gitio.add_all(root)
    gitio.commit(root, "chore: the review\n\nStrata-Op: fixture\n")
    return open_repo(root)


def _screen(repo: Repo, actor: str, record: str, decision: str = "include") -> None:
    record_screen_decision(
        open_repo(repo.root),
        stage="title-abstract",
        record_id=record,
        decision=decision,  # type: ignore[arg-type]
        actor=actor,
        cited=["EXC-01"] if decision == "exclude" else [],
    )


def _log(repo: Repo) -> list[str]:
    return gitio.run(["log", "--format=%an|%s"], cwd=repo.root).stdout.splitlines()


@pytest.mark.parametrize(
    ("name", "actor"),
    [
        ("title-abstract.sam.ndjson", "sam"),
        ("full-text.ethan.ndjson", "ethan"),
        ("title-abstract.ndjson", None),
        ("sam.ndjson", None),
        ("notes.md", None),
    ],
)
def test_the_reviewer_is_read_from_the_file_name(name: str, actor: str | None) -> None:
    assert _actor_of(name) == actor


def test_pending_files_are_listed_by_reviewer_and_gone_once_committed(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    assert pending_screening_files(repo) == {}
    _screen(repo, "sam", _IDS[0])
    _screen(repo, "ethan", _IDS[0], "exclude")
    # A brand-new directory is reported by its files, not as one collapsed entry.
    assert pending_screening_files(open_repo(repo.root)) == {
        "ethan": ["events/screen/title-abstract.ethan.ndjson"],
        "sam": ["events/screen/title-abstract.sam.ndjson"],
    }
    assert pending_screening_actors(open_repo(repo.root)) == ["ethan", "sam"]
    assert commit_screening_batch(open_repo(repo.root), "sam") is True
    assert pending_screening_actors(open_repo(repo.root)) == ["ethan"]
    assert commit_screening_batch(open_repo(repo.root), "sam") is False  # nothing left to commit


def test_a_batch_has_a_generated_summary_and_only_its_own_reviewers_files(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _screen(repo, "sam", _IDS[0])
    _screen(repo, "sam", _IDS[1], "exclude")
    _screen(repo, "ethan", _IDS[0])
    assert commit_screening_batch(open_repo(repo.root), "sam")
    root = repo.root
    assert gitio.run(["log", "-1", "--format=%s"], cwd=root).stdout.strip() == (
        "screen(title-abstract): screen 2 records (1 exclude, 1 include)"
    )
    body = gitio.run(["log", "-1", "--format=%b"], cwd=root).stdout
    assert (
        BROWSER_BODY in body
        and "Strata-Actor: sam" in body
        and "Strata-Stage: title-abstract" in body
    )
    files = gitio.run(["show", "--name-only", "--format=", "HEAD"], cwd=root).stdout.split()
    assert "events/screen/title-abstract.sam.ndjson" in files
    assert "events/screen/title-abstract.ethan.ndjson" not in files
    assert pending_screening_actors(open_repo(root)) == ["ethan"]  # ethan's is still waiting


def test_a_batch_counts_only_the_decisions_not_already_committed(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _screen(repo, "sam", _IDS[0])
    commit_screening_batch(open_repo(repo.root), "sam")
    _screen(repo, "sam", _IDS[1])
    commit_screening_batch(open_repo(repo.root), "sam")
    assert _log(repo)[0].endswith("|screen(title-abstract): screen 1 record (1 include)")


def test_flush_commits_each_reviewer_separately_and_reports_how_many(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    assert flush_pending_screening(repo) == 0  # nothing pending: nothing happens
    _screen(repo, "sam", _IDS[0])
    _screen(repo, "ethan", _IDS[0])
    before = len(_log(repo))
    assert flush_pending_screening(open_repo(repo.root)) == 2
    assert len(_log(repo)) == before + 2
    assert pending_screening_actors(open_repo(repo.root)) == []


def test_flush_leaves_alone_the_reviewers_it_is_told_to(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _screen(repo, "sam", _IDS[0])
    _screen(repo, "ethan", _IDS[0])
    assert flush_pending_screening(open_repo(repo.root), except_actors={"ethan"}) == 1
    assert pending_screening_actors(open_repo(repo.root)) == ["ethan"]


def test_each_batch_is_committed_under_the_identity_the_resolver_gives(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _screen(repo, "sam", _IDS[0])
    _screen(repo, "ethan", _IDS[0])

    def identity(handle: str) -> dict[str, str]:
        return gitio.identity_env(
            author=(f"{handle.title()} Reviewer", f"{handle}@example.test"),
            committer=("The Instance", "instance@example.test"),
        )

    with (
        batch_identities(identity),
        gitio.environment(
            gitio.identity_env(
                author=("Someone Else", "x@example.test"),
                committer=("Someone Else", "x@example.test"),
            )
        ),
    ):
        assert (
            flush_pending_screening(open_repo(repo.root)) == 2
        )  # the ambient identity is not used
    log = gitio.run(["log", "-2", "--format=%an|%cn|%s"], cwd=repo.root).stdout.splitlines()
    assert sorted(line.split("|")[0] for line in log) == ["Ethan Reviewer", "Sam Reviewer"]
    assert {line.split("|")[1] for line in log} == {"The Instance"}


@pytest.mark.parametrize(
    ("path", "form", "flushes"),
    [
        ("/screen/title-abstract", None, False),
        ("/rescreen/title-abstract", None, False),
        ("/screen/title-abstract", {"decision": "include"}, False),
        ("/adjudicate/title-abstract", None, True),
        ("/criteria/EXC-01/edit", {"intent": "save"}, True),
        ("/criteria/EXC-01/edit", {}, True),
        ("/criteria/EXC-01/edit", {"intent": "preview"}, False),  # a preview writes nothing
        ("/dedup/run", None, True),
        ("/import/review/abc", None, True),
    ],
)
def test_only_requests_that_commit_something_else_flush_first(
    path: str, form: dict[str, str] | None, flushes: bool
) -> None:
    assert needs_screening_flush(path, form) is flushes


def test_flushing_under_the_lock_never_touches_the_lock_of_an_idle_repository(
    tmp_path: Path,
) -> None:
    """Taking a dead process's lock "reclaims" it; the operation that follows is the one that
    should say so, so an idle repository's lock is left alone."""
    repo = _repo(tmp_path)
    lock_path = repo.root / ".strata" / "lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path.write_text("999999\n", encoding="ascii")  # a process that is not there
    assert flush_under_lock(repo) == 0
    assert lock_path.exists() and lock_path.read_text(encoding="ascii").strip() == "999999"


def test_flushing_under_the_lock_commits_what_is_pending_and_releases_the_lock(
    tmp_path: Path,
) -> None:
    repo = _repo(tmp_path)
    _screen(repo, "sam", _IDS[0])
    assert flush_under_lock(open_repo(repo.root)) == 1
    assert pending_screening_actors(open_repo(repo.root)) == []
    # Released: another acquisition succeeds at once.
    from strata.core.repo import repo_lock

    with repo_lock(open_repo(repo.root), timeout=1.0):
        pass
