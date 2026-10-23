"""`strata sync`: the shared-remote workflow of openspec:collaboration-sync."""

# ruff: noqa: E501
from __future__ import annotations

import json
from pathlib import Path

import pytest

from strata import gitio
from strata.cli.main import EXIT_CONFLICT, EXIT_GENERIC, EXIT_OK, EXIT_VALIDATION, app
from strata.core import sync as sync_mod
from strata.core.events import read_events, verify_chain
from strata.core.repo import Repo, open_repo
from strata.core.verify import verify_repository
from tests.integration._sync import cli, commit, record_ids, runner, screen, shared_review


def _head(repo: Repo) -> str:
    return gitio.current_commit(repo.root)


def _remote_head(bare: Path) -> str:
    return gitio.run(["rev-parse", "refs/heads/main"], cwd=bare).stdout.strip()


def _events(repo: Repo, name: str) -> list[dict]:  # type: ignore[type-arg]
    return read_events(repo.path("events", "screen", name))


@pytest.fixture
def review(tmp_path: Path) -> tuple[Repo, Repo, Path]:
    return shared_review(tmp_path)


# --- refusing and reporting -------------------------------------------------------------------


def test_a_dirty_working_tree_is_refused_with_advice_in_strata_terms(
    review: tuple[Repo, Repo, Path],
) -> None:
    ethan, _sam, bare = review
    ethan.path("notes.txt").write_text("unrecorded work", encoding="utf-8")
    result = cli(ethan, "sync", code=EXIT_GENERIC)
    assert "uncommitted changes" in result.output and "strata" in result.output
    assert "<<<<" not in result.output and "upstream" not in result.output.lower()
    assert _remote_head(bare) == _head(open_repo(review[1].root))


def test_a_repository_with_no_remote_says_how_to_add_one(tmp_path: Path) -> None:
    from strata.core.init import init_repository

    init_repository(tmp_path / "solo", title="Solo", actor_handle="ethan", actor_name="Ethan")
    repo = open_repo(tmp_path / "solo")
    result = cli(repo, "sync", code=EXIT_GENERIC)
    assert "no shared remote" in result.output and "git remote add" in result.output


def test_nothing_incoming_still_pushes_what_is_local(review: tuple[Repo, Repo, Path]) -> None:
    ethan, _sam, bare = review
    screen(ethan, "ethan", record_ids(ethan)[:2])
    result = cli(ethan, "sync")
    assert "Nothing incoming" in result.output and "Pushed" in result.output
    assert gitio.run(["rev-parse", "HEAD"], cwd=ethan.root).stdout.strip() == _remote_head(bare)


def test_a_fast_forward_reports_what_the_collaborator_did(review: tuple[Repo, Repo, Path]) -> None:
    ethan, sam, _bare = review
    ids = record_ids(ethan)
    screen(sam, "sam", ids[:5], "exclude", ["EXC-01"])
    cli(sam, "sync")
    result = cli(ethan, "sync")
    assert "Fast-forwarding" in result.output
    assert "sam screened 5 record(s) at title-abstract (5 exclude)" in result.output
    assert len(_events(ethan, "title-abstract.sam.ndjson")) == 5
    assert verify_repository(open_repo(ethan.root)).ok


def test_a_tree_that_looks_dirty_but_stages_nothing_still_syncs(
    review: tuple[Repo, Repo, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    """On Windows a fast-forward leaves files that git lists as modified (line endings rewritten
    by the regeneration) although `git add` stages nothing; `git commit` then failed with "nothing
    to commit" and the sync with it."""
    ethan, sam, _bare = review
    screen(sam, "sam", record_ids(sam)[:3], "exclude", ["EXC-01"])
    cli(sam, "sync")
    real = gitio.is_dirty
    calls: list[int] = []

    def dirty_after_the_first_look(path: Path) -> bool:
        calls.append(1)
        return True if len(calls) > 1 else real(path)

    monkeypatch.setattr(sync_mod.gitio, "is_dirty", dirty_after_the_first_look)
    before = _head(ethan)
    result = cli(ethan, "sync")
    assert "Fast-forwarding" in result.output and len(calls) > 1
    assert _head(ethan) != before and verify_repository(open_repo(ethan.root)).ok
    assert not gitio.has_staged_changes(ethan.root)


# --- the structural promise: dual screening never conflicts -----------------------------------


def test_two_collaborators_screening_concurrently_converge_without_a_conflict(
    review: tuple[Repo, Repo, Path],
) -> None:
    ethan, sam, bare = review
    ids = record_ids(ethan)
    screen(ethan, "ethan", ids[:6], "include")
    screen(sam, "sam", ids[2:8], "exclude", ["EXC-01"])
    first = cli(ethan, "sync")
    assert "Pushed" in first.output
    second = cli(sam, "sync")
    assert (
        "Merging" in second.output
        and "ethan screened 6 record(s) at title-abstract (6 include)" in second.output
    )
    assert "new screening conflict(s)" in second.output and "strata adjudicate" in second.output
    cli(ethan, "sync")
    cli(sam, "sync")
    for repo in (ethan, sam):
        assert (
            len(_events(repo, "title-abstract.ethan.ndjson")) == 6
            and len(_events(repo, "title-abstract.sam.ndjson")) == 6
        )
        assert verify_repository(open_repo(repo.root)).ok
    assert _head(ethan) == _head(sam) == _remote_head(bare)
    assert (
        ethan.path("derived", "conflicts.tsv").read_bytes()
        == sam.path("derived", "conflicts.tsv").read_bytes()
    )
    assert (
        ethan.path("derived", "conflicts.tsv").read_text().count("\n") == 1 + 4
    )  # the four records both screened


def test_repeated_syncing_stays_quiet_once_converged(review: tuple[Repo, Repo, Path]) -> None:
    ethan, sam, _bare = review
    screen(ethan, "ethan", record_ids(ethan)[:3])
    cli(ethan, "sync")
    cli(sam, "sync")
    again = cli(sam, "sync")
    assert "Nothing incoming" in again.output and "nothing in the review itself" in again.output


def test_the_same_reviewer_on_two_machines_gets_a_sorted_relinked_file(
    review: tuple[Repo, Repo, Path],
) -> None:
    ethan, sam, _bare = review
    ids = record_ids(ethan)
    # "sam's clone" plays ethan's second machine: both append to ethan's file concurrently.
    screen(ethan, "ethan", ids[:3], "include")
    screen(sam, "ethan", ids[3:6], "exclude", ["EXC-01"])
    cli(ethan, "sync")
    result = cli(sam, "sync")
    assert "re-linked it" in result.output and "title-abstract.ethan.ndjson" in result.output
    path = sam.path("events", "screen", "title-abstract.ethan.ndjson")
    events = read_events(path)
    assert len(events) == 6 and [(e["ts"], e["id"]) for e in events] == sorted(
        (e["ts"], e["id"]) for e in events
    )
    assert verify_chain(path) == [] and [e["seq"] for e in events] == [1, 2, 3, 4, 5, 6]
    relinks = read_events(sam.path("events", "relink", "ethan.ndjson"))
    assert relinks and relinks[0]["body"]["file"] == "events/screen/title-abstract.ethan.ndjson"
    assert verify_repository(open_repo(sam.root)).ok
    cli(ethan, "sync")
    assert read_events(ethan.path("events", "screen", "title-abstract.ethan.ndjson")) == events


# --- verification guards the remote ----------------------------------------------------------


def test_a_merge_that_does_not_verify_is_undone_and_never_pushed(
    review: tuple[Repo, Repo, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    ethan, sam, bare = review
    screen(sam, "sam", record_ids(sam)[:2], "exclude", ["EXC-01"])
    # ethan pushes a broken event file (a schema-invalid line) that the merge will bring in.
    bad = ethan.path("events", "screen", "title-abstract.ethan.ndjson")
    bad.parent.mkdir(parents=True, exist_ok=True)
    bad.write_text(json.dumps({"ev": "nonsense", "id": "ev_" + "0" * 26}) + "\n", encoding="utf-8")
    monkeypatch.setenv("STRATA_SKIP_HOOKS", "1")  # the pre-commit hook would refuse this file
    commit(ethan, "break: a hand-edited event file")
    monkeypatch.delenv("STRATA_SKIP_HOOKS")
    gitio.run(["push", "origin", "HEAD:main"], cwd=ethan.root)
    before, remote_before = _head(sam), _remote_head(bare)
    result = cli(sam, "sync", code=EXIT_VALIDATION)
    assert "does not verify" in result.output and "nothing was pushed" in result.output
    assert _head(sam) == before and _remote_head(bare) == remote_before
    assert not gitio.is_dirty(sam.root)


# --- human-authored conflicts -----------------------------------------------------------------


def _edit_criterion(repo: Repo, text: str) -> None:
    from strata.protocol import criteria as criteria_mod

    criteria_mod.edit_criterion(
        repo,
        "EXC-01",
        direction="tightened",
        actor="ethan",
        rationale="Rewording.",
        definition=text,
    )
    commit(repo, "criteria: reword EXC-01")


def test_two_people_rewording_one_criterion_is_a_conflict_shown_as_mine_and_theirs(
    review: tuple[Repo, Repo, Path],
) -> None:
    ethan, sam, bare = review
    _edit_criterion(ethan, "Wrong population: the sample is not adult learners.")
    _edit_criterion(sam, "Wrong population: the sample is children only.")
    cli(ethan, "sync")
    before = _head(sam)
    refused = cli(sam, "sync", code=EXIT_CONFLICT)
    text = refused.output
    assert "protocol/criteria.yaml" in text and "EXC-01 definition" in text
    assert (
        "mine" in text and "theirs" in text and "children only" in text and "adult learners" in text
    )
    assert "<<<<<<<" not in text and "=======" not in text
    assert _head(sam) == before and not gitio.is_dirty(sam.root)
    assert "adult learners" not in sam.path("protocol", "criteria.yaml").read_text()


def test_resolve_mine_and_theirs(review: tuple[Repo, Repo, Path]) -> None:
    ethan, sam, bare = review
    _edit_criterion(ethan, "Wrong population: the sample is not adult learners.")
    _edit_criterion(sam, "Wrong population: the sample is children only.")
    cli(ethan, "sync")
    out = cli(sam, "sync", "--resolve", "theirs")
    assert "kept theirs for protocol/criteria.yaml" in out.output and "Pushed" in out.output
    assert "adult learners" in sam.path("protocol", "criteria.yaml").read_text()
    assert "<<<<" not in sam.path("protocol", "criteria.yaml").read_text()
    assert verify_repository(open_repo(sam.root)).ok
    cli(ethan, "sync")
    # The repository content is the same; a file the tool wrote may carry the platform's newline.
    assert ethan.path("protocol", "criteria.yaml").read_bytes().replace(b"\r\n", b"\n") == sam.path(
        "protocol", "criteria.yaml"
    ).read_bytes().replace(b"\r\n", b"\n")


def test_the_prompt_offers_mine_theirs_or_an_editor(review: tuple[Repo, Repo, Path]) -> None:
    ethan, sam, _bare = review
    _edit_criterion(ethan, "Wrong population: the sample is not adult learners.")
    _edit_criterion(sam, "Wrong population: the sample is children only.")
    cli(ethan, "sync")
    result = runner.invoke(app, ["-C", str(sam.root), "sync"], input="m\n")
    assert result.exit_code == EXIT_OK, result.output
    assert (
        "Keep [m]ine, keep [t]heirs" in result.output
        and "kept mine for protocol/criteria.yaml" in result.output
    )
    assert "children only" in sam.path("protocol", "criteria.yaml").read_text()


# --- records ------------------------------------------------------------------------------------


def test_concurrent_corrections_to_one_record_are_merged_and_reported(
    review: tuple[Repo, Repo, Path],
) -> None:
    ethan, sam, _bare = review
    target = record_ids(ethan)[0]
    cli(ethan, "fix", target, "--field", "title", "--value", "Beta title", "--by", "ethan")
    cli(sam, "fix", target, "--field", "title", "--value", "Alpha title", "--by", "sam")
    cli(ethan, "sync")
    result = cli(sam, "sync")
    assert (
        "decided automatically" in result.output
        and target in result.output
        and "title" in result.output
    )
    merged = {
        r["id"]: r for r in json.loads(cli(sam, "records", "list", "--format", "json").output)
    }
    assert merged[target]["title"] == "Alpha title"
    amends = [
        e
        for e in read_events(sam.path("events", "fix", "ethan.ndjson"))
        if e["body"].get("source") == "merge"
    ]
    assert amends and amends[0]["body"]["record"] == target
    assert verify_repository(open_repo(sam.root)).ok


# --- the network ----------------------------------------------------------------------------------


def test_network_failures_are_retried_with_exponential_backoff(
    review: tuple[Repo, Repo, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    ethan, _sam, _bare = review
    calls: list[int] = []
    real = gitio.fetch

    def flaky(path: Path, remote: str = "origin"):  # type: ignore[no-untyped-def]
        calls.append(1)
        if len(calls) <= 4:
            raise gitio.GitError(
                ["fetch"],
                128,
                "fatal: unable to access 'https://example.org/': Could not resolve host",
            )
        return real(path, remote)

    monkeypatch.setattr(gitio, "fetch", flaky)
    slept: list[float] = []
    report = sync_mod.sync(ethan, actor="ethan", sleep=slept.append)
    assert slept == [2, 4, 8, 16] and len(calls) == 5 and report.pushed


def test_a_network_that_never_comes_back_is_an_error_after_four_retries(
    review: tuple[Repo, Repo, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    ethan, _sam, _bare = review
    monkeypatch.setattr(
        gitio,
        "fetch",
        lambda path, remote="origin": (_ for _ in ()).throw(
            gitio.GitError(["fetch"], 128, "fatal: Connection timed out")
        ),
    )
    slept: list[float] = []
    with pytest.raises(sync_mod.SyncError, match="after 5 attempts"):
        sync_mod.sync(ethan, actor="ethan", sleep=slept.append)
    assert slept == [2, 4, 8, 16]


def test_a_failure_that_is_not_the_network_is_not_retried(
    review: tuple[Repo, Repo, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    ethan, _sam, _bare = review
    monkeypatch.setattr(
        gitio,
        "fetch",
        lambda path, remote="origin": (_ for _ in ()).throw(
            gitio.GitError(["fetch"], 128, "fatal: 'origin' does not appear to be a git repository")
        ),
    )
    slept: list[float] = []
    with pytest.raises(sync_mod.SyncError, match="fetching failed"):
        sync_mod.sync(ethan, actor="ethan", sleep=slept.append)
    assert slept == []


def test_no_push_fetches_merges_and_verifies_only(review: tuple[Repo, Repo, Path]) -> None:
    ethan, sam, bare = review
    screen(sam, "sam", record_ids(sam)[:2], "exclude", ["EXC-01"])
    cli(sam, "sync")
    screen(ethan, "ethan", record_ids(ethan)[:2])
    before = _remote_head(bare)
    result = cli(ethan, "sync", "--no-push")
    assert "Not pushed" in result.output and _remote_head(bare) == before


def test_json_output_names_the_changes(review: tuple[Repo, Repo, Path]) -> None:
    ethan, sam, _bare = review
    screen(sam, "sam", record_ids(sam)[:3], "exclude", ["EXC-01"])
    cli(sam, "sync")
    out = json.loads(cli(ethan, "--json", "sync").output)
    assert (
        out["status"] == "fast-forward"
        and out["pushed"] is True
        and out["incoming_authors"]["sam"] == 1
    )
    assert out["screened"] == {"sam/title-abstract": {"exclude": 3}}


# --- clones and remotes that are not set up ideally ----------------------------------------------


def test_a_clone_without_the_merge_drivers_still_syncs(review: tuple[Repo, Repo, Path]) -> None:
    ethan, sam, _bare = review
    for driver in ("strata-regenerate", "strata-records"):
        for key in ("name", "driver"):
            gitio.run(["config", "--unset", f"merge.{driver}.{key}"], cwd=sam.root, check=False)
    target = record_ids(ethan)[0]
    cli(ethan, "fix", target, "--field", "title", "--value", "Beta title", "--by", "ethan")
    cli(sam, "fix", target, "--field", "title", "--value", "Alpha title", "--by", "sam")
    screen(sam, "sam", record_ids(sam)[1:3], "exclude", ["EXC-01"])
    cli(ethan, "sync")
    result = cli(sam, "sync")  # exit code 0: no conflict markers left for anyone to resolve
    assert "<<<<" not in result.output and "decided automatically" in result.output
    assert verify_repository(open_repo(sam.root)).ok and not gitio.is_dirty(sam.root)
    assert "<<<<<<<" not in sam.path("records", "records.ndjson").read_text()
    cli(ethan, "sync")
    assert _head(ethan) == _head(sam)
    assert (
        ethan.path("records", "records.ndjson").read_bytes()
        == sam.path("records", "records.ndjson").read_bytes()
    )


def test_the_rebase_strategy_replays_local_commits_and_converges(
    review: tuple[Repo, Repo, Path],
) -> None:
    ethan, sam, bare = review
    ids = record_ids(ethan)
    screen(ethan, "ethan", ids[:3], "include")
    cli(ethan, "sync")
    screen(sam, "sam", ids[3:6], "exclude", ["EXC-01"])
    report = sync_mod.sync(sam, actor="sam", strategy="rebase")
    assert report.status == "merged" and report.pushed
    for repo in (open_repo(sam.root), open_repo(ethan.root)):
        if repo.root == ethan.root:
            cli(ethan, "sync")
        assert verify_repository(open_repo(repo.root)).ok
    assert _head(sam) == _remote_head(bare) == _head(ethan)
    assert len(_events(sam, "title-abstract.ethan.ndjson")) == 3
    assert len(_events(sam, "title-abstract.sam.ndjson")) == 3


def test_a_push_the_remote_rejects_is_integrated_and_tried_again(
    review: tuple[Repo, Repo, Path],
) -> None:
    ethan, sam, bare = review
    ids = record_ids(ethan)
    screen(sam, "sam", ids[:2], "exclude", ["EXC-01"])
    flag = bare / "rejected-once"
    hook = bare / "hooks" / "pre-receive"
    hook.write_text(
        f'#!/bin/sh\nif [ ! -e "{flag}" ]; then touch "{flag}"; echo "remote: busy" >&2; exit 1; fi\n',
        encoding="utf-8",
    )
    hook.chmod(0o755)
    report = sync_mod.sync(sam, actor="sam")
    assert report.pushed and flag.exists()
    assert _remote_head(bare) == _head(sam)
    screen(ethan, "ethan", ids[2:4], "include")
    cli(ethan, "sync")
    assert verify_repository(open_repo(ethan.root)).ok


# --- the merge drivers as commands -----------------------------------------------------------------


def test_the_driver_commands_follow_git_s_contract(tmp_path: Path) -> None:
    base, ours, theirs = tmp_path / "b", tmp_path / "o", tmp_path / "t"
    for path in (base, ours, theirs):
        path.write_text("anything\n", encoding="utf-8")
    result = runner.invoke(
        app, ["merge-regenerate", str(base), str(ours), str(theirs), "derived/pool.tsv"]
    )
    assert result.exit_code == 0 and ours.read_text() == "anything\n"
    record = {
        "id": "rec_0000000000000001",
        "type": "article-journal",
        "title": "T",
        "strata": {"canonical_key": "sig:1", "canonical": True, "sources": []},
    }
    base.write_text("", encoding="utf-8")
    ours.write_text(json.dumps(record) + "\n", encoding="utf-8")
    theirs.write_text(json.dumps({**record, "id": "rec_0000000000000002"}) + "\n", encoding="utf-8")
    result = runner.invoke(
        app, ["merge-records", str(base), str(ours), str(theirs), "records/records.ndjson"]
    )
    assert result.exit_code == 0, result.output
    assert [json.loads(line)["id"] for line in ours.read_text().splitlines()] == [
        "rec_0000000000000001",
        "rec_0000000000000002",
    ]
