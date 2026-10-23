"""E2E-02: two collaborators screening concurrently on separate clones, syncing repeatedly through
a shared remote with `strata sync`, end identical with zero manual conflict resolution.

The first test is the structural invariant the second depends on
(openspec:collaboration-sync#dual-screening-never-conflicts): two actors writing to disjoint
per-actor event files never produce a git conflict, even under a genuine three-way merge. The second
is the scenario itself, through the CLI: rounds of screening and syncing from both clones.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from strata import gitio
from strata.cli.main import app
from strata.core.events import append_new_event, read_events
from strata.core.repo import open_repo
from strata.core.verify import verify_repository
from tests.integration._sync import cli as sync_cli
from tests.integration._sync import record_ids, shared_review

runner = CliRunner()


@pytest.mark.req("E2E-02")
def test_two_clones_disjoint_events_merge_without_conflict(tmp_path: Path) -> None:
    origin = tmp_path / "origin"
    init_result = runner.invoke(
        app,
        [
            "init",
            str(origin),
            "--title",
            "Concurrent Review",
            "--actor",
            "ethan",
            "--actor-name",
            "Ethan",
        ],
    )
    assert init_result.exit_code == 0, init_result.output

    add_sam = runner.invoke(
        app,
        [
            "--why",
            "Sam is joining the review team as a second screener.",
            "-C",
            str(origin),
            "actor",
            "add",
            "sam",
            "Sam",
        ],
    )
    assert add_sam.exit_code == 0, add_sam.output

    bare = tmp_path / "origin.git"
    gitio.run(["init", "--bare", "--initial-branch=main", str(bare)], cwd=tmp_path)
    gitio.run(["remote", "add", "shared", str(bare)], cwd=origin)
    gitio.run(["push", "shared", "HEAD:main"], cwd=origin)

    ethan_clone = tmp_path / "ethan-clone"
    sam_clone = tmp_path / "sam-clone"
    gitio.clone(str(bare), ethan_clone)
    gitio.clone(str(bare), sam_clone)
    for clone in (ethan_clone, sam_clone):
        doctor_result = runner.invoke(app, ["-C", str(clone), "doctor", "--fix"])
        assert doctor_result.exit_code == 0, doctor_result.output

    ethan_events_path = ethan_clone / "events" / "screen" / "title-abstract.ethan.ndjson"
    for i in range(3):
        append_new_event(
            ethan_events_path,
            ev="screen",
            actor="ethan",
            body={
                "stage": "title-abstract",
                "record": f"rec_ethan{i:012x}",
                "decision": "include",
                "criteria": [],
                "criteria_version": 1,
            },
        )
    gitio.add(ethan_clone, ["events"])
    gitio.commit(
        ethan_clone,
        "screen(title-abstract): screen 3 records\n\nStrata-Op: screen\nStrata-Actor: ethan\n",
    )
    gitio.run(["push", "origin", "HEAD:main"], cwd=ethan_clone)

    sam_events_path = sam_clone / "events" / "screen" / "title-abstract.sam.ndjson"
    for i in range(3):
        append_new_event(
            sam_events_path,
            ev="screen",
            actor="sam",
            body={
                "stage": "title-abstract",
                "record": f"rec_sam{i:013x}",
                "decision": "exclude",
                "criteria": ["EXC-01"],
                "criteria_version": 1,
            },
        )
    gitio.add(sam_clone, ["events"])
    gitio.commit(
        sam_clone,
        "screen(title-abstract): screen 3 records\n\nStrata-Op: screen\nStrata-Actor: sam\n",
    )

    # sam is now behind origin/main (ethan pushed first). Fetch + merge must be
    # conflict-free because the two actors touched disjoint files.
    gitio.fetch(sam_clone, "origin")
    merge_result = gitio.run(
        ["merge", "origin/main", "-m", "merge: sync"], cwd=sam_clone, check=False
    )
    assert merge_result.returncode == 0, merge_result.stderr
    status = gitio.run(["status", "--porcelain"], cwd=sam_clone)
    assert "UU" not in status.stdout

    gitio.run(["push", "origin", "HEAD:main"], cwd=sam_clone)

    gitio.fetch(ethan_clone, "origin")
    gitio.run(["merge", "origin/main", "--ff-only"], cwd=ethan_clone)

    for clone_path in (ethan_clone, sam_clone):
        ethan_events = read_events(clone_path / "events" / "screen" / "title-abstract.ethan.ndjson")
        sam_events = read_events(clone_path / "events" / "screen" / "title-abstract.sam.ndjson")
        assert len(ethan_events) == 3
        assert len(sam_events) == 3

    report = verify_repository(open_repo(sam_clone))
    # Dangling-record warnings are expected at this stage (dedup/import land in
    # M1); what matters here is that schemas and hash chains survived the merge.
    assert not any(issue.code in ("E_SCHEMA", "E_CHAIN") for issue in report.issues)


@pytest.mark.req("E2E-02")
def test_two_collaborators_screen_and_sync_repeatedly_and_converge(tmp_path: Path) -> None:
    ethan, sam, bare = shared_review(tmp_path, records=9)
    for _round in range(3):
        for handle, clone in (("ethan", ethan), ("sam", sam)):
            result = runner.invoke(
                app,
                [
                    "--why",
                    "Screening this batch for the shared review.",
                    "-C",
                    str(clone.root),
                    "screen",
                    "title-abstract",
                    "--by",
                    handle,
                    "--limit",
                    "3",
                ],
                input="i\n\n" * 3,
            )
            assert result.exit_code == 0, result.output
        for clone in (ethan, sam):
            out = sync_cli(clone, "sync")  # exit code 0 every time: never a conflict to resolve
            assert "conflict:" not in out.output and "<<<<" not in out.output
    for clone in (ethan, sam, ethan):
        sync_cli(clone, "sync")

    heads = {gitio.current_commit(c.root) for c in (ethan, sam)}
    assert len(heads) == 1 and heads == {
        gitio.run(["rev-parse", "refs/heads/main"], cwd=bare).stdout.strip()
    }
    for clone in (ethan, sam):
        for handle in ("ethan", "sam"):
            events = read_events(
                clone.root / "events" / "screen" / f"title-abstract.{handle}.ndjson"
            )
            assert len(events) == 9 and len({e["body"]["record"] for e in events}) == 9
        assert verify_repository(open_repo(clone.root)).ok
        assert not gitio.is_dirty(clone.root)
    assert (ethan.root / "derived" / "pool.tsv").read_bytes() == (
        sam.root / "derived" / "pool.tsv"
    ).read_bytes()
    status = runner.invoke(app, ["--json", "-C", str(ethan.root), "status"])
    assert status.exit_code == 0 and len(record_ids(ethan)) == 9
