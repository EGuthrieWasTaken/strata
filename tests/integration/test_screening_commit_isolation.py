"""A commit for one operation never carries another reviewer's pending screening decisions.

Screening decisions are written at once and committed in batches
(`openspec:git-integration#batched-screening-commits`). Until the batch is committed a decision
sits in its reviewer's event file, uncommitted, and every other operation stages `events/` and
`derived/`. They used to take it along: an adjudication by one reviewer committed another's
screening file, under the adjudicator's name and with the adjudication's subject. These tests make
an operation commit while other reviewers have pending decisions and check what each commit
contains and who it names.
"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
from typer.testing import CliRunner

from strata import gitio
from strata.cli.main import app as cli_app
from strata.core.actor import add_actor
from strata.core.init import init_repository
from strata.core.records import write_records
from strata.core.repo import Repo, open_repo
from strata.core.verify import verify_repository
from strata.protocol.criteria import add_criterion
from strata.protocol.screening import record_screen_decision
from strata.web.app import create_app

_TOKEN = "test-session-token-0123456789"
_RECORDS = ("rec_0000000000000001", "rec_0000000000000002")


def _record(record_id: str) -> dict:  # type: ignore[type-arg]
    return {
        "id": record_id,
        "type": "article-journal",
        "title": f"Title of {record_id}",
        "abstract": "An abstract.",
        "strata": {
            "canonical_key": f"sig:{record_id}",
            "canonical": True,
            "sources": [{"import": "imp_01arz3ndektsv4rrffq69g5fav"}],
        },
    }


def _review(tmp_path: Path) -> tuple[Repo, str]:
    """ethan (the lead) and sam, one exclusion criterion and two records, all committed. Then sam
    includes and ethan excludes the first record (a conflict) and both decisions stay uncommitted,
    as they are when made in the browser. Returns the repository and the commit that is HEAD."""
    root = tmp_path / "review"
    init_repository(root, title="Isolation", actor_handle="ethan", actor_name="Ethan Guthrie")
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
    write_records(open_repo(root), [_record(r) for r in _RECORDS])
    gitio.add_all(root)
    gitio.commit(root, "chore: the shared review\n\nStrata-Op: fixture\n")
    head = gitio.current_commit(root)
    for actor, decision, cited in (("sam", "include", []), ("ethan", "exclude", ["EXC-01"])):
        record_screen_decision(
            open_repo(root),
            stage="title-abstract",
            record_id=_RECORDS[0],
            decision=decision,  # type: ignore[arg-type]
            actor=actor,
            cited=cited,
        )
    assert sorted(_pending(root)) == [
        "events/screen/title-abstract.ethan.ndjson",
        "events/screen/title-abstract.sam.ndjson",
    ]
    return open_repo(root), head


def _git(root: Path, *args: str) -> str:
    return gitio.run(list(args), cwd=root).stdout


def _pending(root: Path) -> list[str]:
    return [line[3:] for line in _git(root, "status", "--porcelain", "-uall").splitlines() if line]


def _commits_since(root: Path, head: str) -> list[tuple[str, str, str, set[str], str]]:
    """(sha, author, subject, files, trailers) of every commit after `head`, oldest first."""
    shas = _git(root, "log", "--reverse", "--format=%H", f"{head}..HEAD").split()
    return [
        (
            sha,
            _git(root, "show", "-s", "--format=%an", sha).strip(),
            _git(root, "show", "-s", "--format=%s", sha).strip(),
            set(_git(root, "show", "--name-only", "--format=", sha).split()),
            _git(root, "show", "-s", "--format=%b", sha),
        )
        for sha in shas
    ]


def _client(repo: Repo, actor: str) -> TestClient:
    app = create_app(repo_root=repo.root, actor=actor, session_token=_TOKEN)
    client = TestClient(app, base_url="http://127.0.0.1:8000")
    assert client.get(f"/?token={_TOKEN}").status_code == 200
    return client


def _assert_derived_files_current(root: Path) -> None:
    """The derived views say what regenerating them would write. (Not `verify_repository(...).ok`:
    these records carry a made-up import id, so the PRISMA counts never close, in any commit.)"""
    codes = {issue.code for issue in verify_repository(open_repo(root)).issues}
    assert "E_DERIVED_DRIFT" not in codes, codes


def _screen_commits(commits):  # type: ignore[no-untyped-def]
    return [c for c in commits if c[2].startswith("screen(")]


def _assert_isolated(root: Path, head: str, *, operation: str) -> None:
    """Two batches (one per reviewer, each with only their own file) and then the operation's own
    commit, which holds no screening file; and a repository that is clean and valid."""
    commits = _commits_since(root, head)
    batches = _screen_commits(commits)
    assert len(batches) == 2, [c[2] for c in commits]
    by_actor = {c[4].split("Strata-Actor:")[1].split()[0]: c for c in batches}
    assert set(by_actor) == {"ethan", "sam"}
    assert by_actor["sam"][3] & {"events/screen/title-abstract.sam.ndjson"}
    assert not by_actor["sam"][3] & {"events/screen/title-abstract.ethan.ndjson"}
    assert by_actor["ethan"][3] & {"events/screen/title-abstract.ethan.ndjson"}
    assert not by_actor["ethan"][3] & {"events/screen/title-abstract.sam.ndjson"}

    own = [c for c in commits if c[2].startswith(operation)]
    assert len(own) == 1, [c[2] for c in commits]
    assert not [f for f in own[0][3] if f.startswith("events/screen/")], own[0][3]
    # The batches come first, so the operation's commit is the last thing in the history.
    assert commits[-1][0] == own[0][0]
    assert _pending(root) == []
    _assert_derived_files_current(root)


def test_a_web_adjudication_does_not_commit_another_reviewers_pending_decisions(
    tmp_path: Path,
) -> None:
    repo, head = _review(tmp_path)
    response = _client(repo, "ethan").post(
        "/adjudicate/title-abstract",
        data={
            "csrf_token": _TOKEN,
            "record_id": _RECORDS[0],
            "decision": "include",
            "rationale": "Both opinions read; the study is empirical.",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    _assert_isolated(repo.root, head, operation="adjudicate(")


def test_a_web_criteria_change_does_not_commit_pending_decisions_with_it(tmp_path: Path) -> None:
    repo, head = _review(tmp_path)
    response = _client(repo, "ethan").post(
        "/criteria/EXC-01/edit",
        data={
            "csrf_token": _TOKEN,
            "direction": "loosened",
            "definition": "Not an empirical study, reviews excepted.",
            "rationale": "Systematic reviews should reach full text.",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    _assert_isolated(repo.root, head, operation="criteria-edit(")


def test_a_web_duplicate_run_does_not_commit_pending_decisions_with_it(tmp_path: Path) -> None:
    repo, head = _review(tmp_path)
    # Two records that dedup will merge: same DOI, so there is something to commit.
    twin = _record("rec_0000000000000003")
    twin["DOI"] = "10.1234/same"
    first = _record("rec_0000000000000004")
    first["DOI"] = "10.1234/same"
    write_records(open_repo(repo.root), [twin, first])
    gitio.add(repo.root, ["records"])  # only the records: the screening files stay pending
    gitio.commit(repo.root, "chore: two records with the same DOI\n\nStrata-Op: fixture\n")
    head = gitio.current_commit(repo.root)
    response = _client(open_repo(repo.root), "ethan").post(
        "/dedup/run",
        data={"csrf_token": _TOKEN, "rationale": "Merging the obvious duplicate pair."},
        follow_redirects=False,
    )
    assert response.status_code in (200, 303)
    commits = _commits_since(repo.root, head)
    assert len(_screen_commits(commits)) == 2, [c[2] for c in commits]
    assert all(not f.startswith("events/screen/") for c in commits[2:] for f in c[3])
    assert _pending(repo.root) == []


def test_a_command_line_search_does_not_commit_pending_decisions_with_it(tmp_path: Path) -> None:
    repo, head = _review(tmp_path)
    result = CliRunner().invoke(
        cli_app,
        ["--why", "Recording the PsycINFO search.", "-C", str(repo.root)]
        + ["search", "add", "--database", "PsycINFO", "--platform", "Ovid", "--by", "ethan"]
        + ["--query", "spaced practice", "--hits", "3"],
    )
    assert result.exit_code == 0, result.output
    _assert_isolated(repo.root, head, operation="search-add(")


def test_a_command_line_criterion_does_not_commit_pending_decisions_with_it(
    tmp_path: Path,
) -> None:
    repo, head = _review(tmp_path)
    result = CliRunner().invoke(
        cli_app,
        ["--why", "Adding a second exclusion criterion.", "-C", str(repo.root)]
        + ["criteria", "add", "--kind", "exclusion", "--label", "Not human"]
        + ["--definition", "Animal studies.", "--applies-at", "title-abstract", "--by", "ethan"],
    )
    assert result.exit_code == 0, result.output
    _assert_isolated(repo.root, head, operation="criteria-add(")


def test_a_command_line_screening_session_commits_only_its_own_decisions(tmp_path: Path) -> None:
    """`strata screen` by one reviewer while another's decisions are pending: the other's go in a
    batch of their own, and the session's commit holds only what the session recorded."""
    repo, head = _review(tmp_path)
    # Ethan has his own pending decision too; sam's must not travel with the session's commit.
    result = CliRunner().invoke(
        cli_app,
        ["--why", "Screening the second record.", "-C", str(repo.root)]
        + ["screen", "title-abstract", "--by", "ethan", "--filter", f"id in ['{_RECORDS[1]}']"],
        input="i\n\n",
    )
    assert result.exit_code == 0, result.output
    commits = _commits_since(repo.root, head)
    sam = [c for c in _screen_commits(commits) if "Strata-Actor: sam" in c[4]]
    assert len(sam) == 1
    assert sam[0][3] & {"events/screen/title-abstract.sam.ndjson"}
    assert not sam[0][3] & {"events/screen/title-abstract.ethan.ndjson"}
    session = [c for c in commits if c[2].startswith("screen(") and c not in sam][-1]
    assert not session[3] & {"events/screen/title-abstract.sam.ndjson"}
    assert _pending(repo.root) == []
    _assert_derived_files_current(repo.root)
