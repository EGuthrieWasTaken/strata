"""E2E-02 (skeleton): two collaborators screening concurrently on separate
clones sync with zero manual conflict resolution.

Full fidelity with docs/spec/14-testing.md's E2E-02 (repeated syncing via
`strata sync`) lands once that command exists; this exercises the structural
invariant it depends on (docs/spec/04-git-integration.md §5.1): two actors
writing to disjoint per-actor event files never produces a git conflict,
even under a genuine three-way merge.
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

    add_sam = runner.invoke(app, ["-C", str(origin), "actor", "add", "sam", "Sam"])
    assert add_sam.exit_code == 0, add_sam.output
    gitio.add_all(origin)
    gitio.commit(origin, "chore: add sam as an actor\n\nStrata-Op: actor-add\n")

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
