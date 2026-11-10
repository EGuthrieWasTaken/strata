"""On a hosted instance one member's operation never commits another member's screening decisions.

An adjudication (or any other commit) stages `events/` and `derived/`. Another member's decisions,
still waiting for their batch, sit in `events/screen/<stage>.<actor>.ndjson` and used to ride along
in it: committed with the adjudicator as author and the adjudication as subject, which breaks
`openspec:hosted-deployment#commit-attribution` (each commit names the reviewer who made it).
Each member's batch is now committed first, as that member.
"""

from __future__ import annotations

from pathlib import Path

from strata import gitio
from strata.hosted.syncloop import actor_identity
from strata.protocol import screening as screening_mod
from tests.integration._hosted import hosted, post
from tests.integration.test_hosted_sync import _ids


def test_an_adjudication_commits_each_members_pending_batch_first_and_as_them(
    tmp_path: Path,
) -> None:
    h = hosted(tmp_path)
    record = _ids(h.repo)[0]
    ethan, sam = h.signed_in("ethan.g"), h.signed_in("sam.okonkwo")

    # ethan includes and sam excludes; the review's third screener, priya, has no account here, so
    # her decision is written straight into the instance's working copy. None is committed yet.
    assert post(ethan, "/screen/title-abstract", {"record_id": record, "decision": "include"})
    assert post(
        sam,
        "/screen/title-abstract",
        {"record_id": record, "decision": "exclude", "criteria": ["EXC-01"]},
    )
    screening_mod.record_screen_decision(
        h.repo,
        stage="title-abstract",
        record_id=record,
        decision="include",
        actor="priya",
        cited=[],
    )
    root = h.repo.root
    head = gitio.current_commit(root)
    assert h.server.sync.status("spacing").pending_decisions == 2

    response = post(
        ethan,
        "/adjudicate/title-abstract",
        {
            "record_id": record,
            "decision": "include",
            "rationale": "All three opinions read; the study is empirical.",
        },
    )
    assert response.status_code == 303, response.text

    shas = gitio.run(["log", "--reverse", "--format=%H", f"{head}..HEAD"], cwd=root).stdout.split()
    commits = []
    for sha in shas:
        fmt = lambda f, sha=sha: gitio.run(["show", "-s", f"--format={f}", sha], cwd=root).stdout  # noqa: E731
        files = set(gitio.run(["show", "--name-only", "--format=", sha], cwd=root).stdout.split())
        commits.append(
            (fmt("%an").strip(), fmt("%cn").strip(), fmt("%s").strip(), fmt("%b"), files)
        )

    batches = [c for c in commits if c[2].startswith("screen(")]
    adjudication = [c for c in commits if c[2].startswith("adjudicate(")]
    assert len(batches) == 3 and len(adjudication) == 1, [c[2] for c in commits]
    assert commits[-1] == adjudication[0]  # the batches first, then the operation

    instance = h.instance.settings.committer[0]
    for handle in ("ethan", "sam", "priya"):
        mine = [c for c in batches if f"Strata-Actor: {handle}" in c[3]]
        assert len(mine) == 1, handle
        author, committer, _, _, files = mine[0]
        assert author == actor_identity(h.repo, handle)[0]  # the reviewer, not the adjudicator
        assert committer == instance
        assert files & {f"events/screen/title-abstract.{handle}.ndjson"}
        assert not [f for f in files if f.startswith("events/screen/") and f"{handle}." not in f]

    author, committer, _, _, files = adjudication[0]
    assert author == actor_identity(h.repo, "ethan")[0] and committer == instance
    assert not [f for f in files if f.startswith("events/screen/")], files

    # Nothing is left waiting, and the instance's own bookkeeping agrees.
    assert gitio.run(["status", "--porcelain"], cwd=root).stdout.strip() == ""
    assert h.server.sync.status("spacing").pending_decisions == 0


def test_a_decision_whose_bookkeeping_row_was_lost_is_still_committed_by_its_author(
    tmp_path: Path,
) -> None:
    """What is on disk is the truth: if the instance restarted or a note failed, the pending file is
    still found and committed as its reviewer's, not left for the next operation to take along."""
    h = hosted(tmp_path)
    record = _ids(h.repo)[0]
    screening_mod.record_screen_decision(
        h.repo, stage="title-abstract", record_id=record, decision="include", actor="sam", cited=[]
    )
    assert h.server.sync.status("spacing").pending_decisions == 0  # no row: nothing noted it
    assert h.server.sync.flush("spacing") == 1
    root = h.repo.root
    author = gitio.run(["show", "-s", "--format=%an|%s", "HEAD"], cwd=root).stdout.strip()
    assert author.startswith(actor_identity(h.repo, "sam")[0] + "|screen(title-abstract)")
    assert gitio.run(["status", "--porcelain"], cwd=root).stdout.strip() == ""
