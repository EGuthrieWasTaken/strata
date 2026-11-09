"""The hosted sync loop, end to end (openspec:hosted-deployment#automatic-git-sync-loop,
#hosted-and-local-collaborators-interoperate, #commit-attribution, #git-is-always-the-backend).

Two members screen concurrently through the instance while a third screens on a laptop and runs
`strata sync`; every decision survives everywhere. A criterion edited differently on the instance
and on the laptop stops pushes and is shown to the lead in domain terms until resolved. An
unreachable remote is retried with backoff and loses nothing.
"""

# ruff: noqa: E501

from __future__ import annotations

import shutil
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from strata import gitio
from strata.core import records as records_mod
from strata.core import sync as sync_mod
from strata.core.repo import Repo, open_repo
from strata.core.verify import verify_repository
from strata.hosted import syncloop
from strata.protocol import criteria as criteria_mod
from strata.protocol import screening as screening_mod
from tests.integration._hosted import csrf_from, event_lines, hosted, local_clone, post


def _ids(repo: Repo) -> list[str]:
    return sorted(r["id"] for r in records_mod.read_records(repo))


def _commit(repo: Repo, message: str, actor: str) -> None:
    gitio.add_all(repo.root)
    gitio.commit(repo.root, f"{message}\n\nStrata-Op: test\nStrata-Actor: {actor}\n")


def _remote_head(bare: Path) -> str:
    return gitio.run(["rev-parse", "refs/heads/main"], cwd=bare).stdout.strip()


def _screen_locally(repo: Repo, actor: str, ids: list[str], decision: str = "include") -> None:
    for record_id in ids:
        screening_mod.record_screen_decision(
            repo, stage="title-abstract", record_id=record_id, decision=decision,  # type: ignore[arg-type]
            actor=actor,
        )  # fmt: skip
    _commit(repo, f"screen: {actor} screened {len(ids)}", actor)


def _decisions(repo: Repo) -> set[tuple[str, str, str]]:
    return {
        (e["actor"], e["body"]["record"], e["body"]["decision"])
        for e in screening_mod.all_screen_events(repo, "title-abstract")
    }


def test_two_hosted_members_and_a_local_clone_converge_with_every_decision(tmp_path: Path) -> None:
    h = hosted(tmp_path)
    priya = local_clone(h.bare, tmp_path / "priya-laptop")
    ids = _ids(h.repo)
    ethan, sam = h.signed_in("ethan.g"), h.signed_in("sam.okonkwo")
    ethan_csrf, sam_csrf = (
        csrf_from(ethan.get("/p/spacing/").text),
        csrf_from(sam.get("/p/spacing/").text),
    )

    def decide(client, csrf: str, decision: str) -> list[int]:  # type: ignore[no-untyped-def]
        return [
            client.post(
                "/p/spacing/screen/title-abstract",
                data={"csrf_token": csrf, "record_id": record_id, "decision": decision},
            ).status_code
            for record_id in ids
        ]

    # Both members screen at the same time, each in their own browser.
    with ThreadPoolExecutor(max_workers=2) as pool:
        ethan_codes = pool.submit(decide, ethan, ethan_csrf, "include")
        sam_codes = pool.submit(decide, sam, sam_csrf, "maybe")
        assert ethan_codes.result() == [303] * len(ids)
        assert sam_codes.result() == [303] * len(ids)

    # Meanwhile the local collaborator screens half of them and syncs first.
    _screen_locally(priya, "priya", ids[:3])
    sync_mod.sync(priya, actor="priya", sleep=lambda _s: None)

    # The instance commits the members' batches (after 15 idle minutes) and pushes.
    h.clock.advance(syncloop.BATCH_IDLE + 1)
    assert h.server.sync.run_due() == ["spacing"]
    status = h.server.sync.status("spacing")
    assert (
        status.push_pending is False and status.last_error is None and status.pending_decisions == 0
    )

    # The laptop syncs again: the instance, the laptop and the remote now agree exactly.
    sync_mod.sync(open_repo(priya.root), actor="priya", sleep=lambda _s: None)
    instance_repo, laptop = h.repo, open_repo(priya.root)
    assert event_lines(instance_repo) == event_lines(laptop)
    assert (
        gitio.current_commit(instance_repo.root)
        == gitio.current_commit(laptop.root)
        == _remote_head(h.bare)
    )
    expected = (
        {("ethan", r, "include") for r in ids}
        | {("sam", r, "maybe") for r in ids}
        | {("priya", r, "include") for r in ids[:3]}
    )
    assert _decisions(laptop) == expected
    assert verify_repository(laptop).ok

    # Leaving the instance: a fresh clone of the remote verifies and holds every decision.
    leaving = local_clone(h.bare, tmp_path / "leaving")
    assert verify_repository(leaving).ok and _decisions(leaving) == expected

    # Each commit made for a member names them as author and the instance as committer.
    log = gitio.log(instance_repo.root, fmt="%an | %cn | %s")
    batches = [line for line in log if "| screen(title-abstract): screen 6 records" in line]
    assert sorted(batches) == [
        "Ethan Guthrie | strata instance | screen(title-abstract): screen 6 records (6 include)",
        "Sam Okonkwo | strata instance | screen(title-abstract): screen 6 records (6 maybe)",
    ]
    by_instance = [line for line in log if " | strata instance | " in line]
    assert any(line.endswith("sync: sync with origin") for line in by_instance)
    assert {line.split(" | ")[0] for line in by_instance} <= {"Ethan Guthrie", "Sam Okonkwo"}


def test_a_batch_of_200_decisions_is_committed_at_once(tmp_path: Path) -> None:
    h = hosted(tmp_path, records=2)
    sam = h.signed_in("sam.okonkwo")
    for record_id in _ids(h.repo):
        assert (
            post(
                sam, "/screen/title-abstract", {"record_id": record_id, "decision": "include"}
            ).status_code
            == 303
        )
    assert h.server.sync.status("spacing").pending_decisions == 2
    head = gitio.current_commit(h.repo.root)
    h.instance.store.execute(
        "UPDATE screening_batches SET pending = ? WHERE actor = 'sam'", (syncloop.BATCH_SIZE - 1,)
    )
    assert h.server.sync.note_screening("spacing", "sam") is True
    assert gitio.current_commit(h.repo.root) != head
    assert h.server.sync.status("spacing").push_pending is True
    assert not gitio.is_dirty(h.repo.root)


def test_commits_made_in_the_browser_are_pushed_after_commit(tmp_path: Path) -> None:
    h = hosted(tmp_path)
    ethan = h.signed_in("ethan.g")
    before = _remote_head(h.bare)
    response = post(
        ethan, "/criteria/EXC-01/edit",
        {"direction": "tightened", "definition": "Wrong population: not human learners.", "rationale": "Clarifying the wording."},
    )  # fmt: skip
    assert response.status_code == 303 and response.headers["location"] == "/p/spacing/criteria"
    assert h.server.sync.status("spacing").push_pending is True
    assert h.server.sync.run_due() == ["spacing"]
    assert _remote_head(h.bare) != before
    pushed = gitio.run(
        ["log", "-1", "--format=%an | %cn", "refs/heads/main"], cwd=h.bare
    ).stdout.strip()
    assert pushed == "Ethan Guthrie | strata instance"


def test_conflicting_criterion_edits_stop_pushes_until_a_lead_resolves(tmp_path: Path) -> None:
    h = hosted(tmp_path)
    priya = local_clone(h.bare, tmp_path / "priya-laptop")
    ethan = h.signed_in("ethan.g")
    # The lead rewords EXC-03 (here EXC-01) on the instance ...
    assert post(
        ethan, "/criteria/EXC-01/edit",
        {"direction": "tightened", "definition": "Wrong population: the sample is not adult learners.", "rationale": "Rewording the criterion."},
    ).status_code == 303  # fmt: skip
    # ... while a local collaborator pushes a different wording.
    criteria_mod.edit_criterion(
        priya, "EXC-01", direction="tightened", actor="priya", rationale="Rewording.",
        definition="Wrong population: the sample is children only.",
    )  # fmt: skip
    _commit(priya, "criteria: reword EXC-01", "priya")
    sync_mod.sync(priya, actor="priya", sleep=lambda _s: None)
    remote_before = _remote_head(h.bare)
    instance_head = gitio.current_commit(h.repo.root)

    assert h.server.sync.run_due() == []
    status = h.server.sync.status("spacing")
    assert status.blocked and status.push_pending
    assert [c["path"] for c in status.conflicts] == ["protocol/criteria.yaml"]
    assert any("EXC-01 definition" in line for line in status.conflicts[0]["summary"])
    # Nothing was resolved silently: the instance's copy is as it was, and nothing was pushed.
    assert _remote_head(h.bare) == remote_before
    assert gitio.current_commit(h.repo.root) == instance_head and not gitio.is_dirty(h.repo.root)
    assert "adult learners" in h.repo.path("protocol", "criteria.yaml").read_text()
    # Pushes stay stopped, and so do pulls, until it is resolved.
    h.clock.advance(3600)
    assert h.server.sync.run_due() == []
    assert _remote_head(h.bare) == remote_before

    # Every page says so; only a lead is offered the choice.
    sam = h.signed_in("sam.okonkwo")
    assert "Pushes to the shared remote are stopped" in sam.get("/p/spacing/").text
    sam_view = sam.get("/p/spacing/-/sync")
    assert sam_view.status_code == 200 and 'data-testid="conflict-form"' not in sam_view.text
    assert post(sam, "/-/sync", {"action": "resolve", "choice-0": "mine"}).status_code == 403
    lead_view = ethan.get("/p/spacing/-/sync")
    assert 'data-testid="conflict-form"' in lead_view.text
    assert "adult learners" in lead_view.text and "children only" in lead_view.text
    assert (
        "Keep mine" in lead_view.text
        and "Keep theirs" in lead_view.text
        and "Edit:" in lead_view.text
    )

    # The lead keeps theirs: the sync completes and pushes.
    resolved = post(ethan, "/-/sync", {"action": "resolve", "choice-0": "theirs"})
    assert resolved.status_code == 303
    status = h.server.sync.status("spacing")
    assert not status.blocked and not status.push_pending and status.last_error is None
    assert "children only" in h.repo.path("protocol", "criteria.yaml").read_text()
    assert _remote_head(h.bare) == gitio.current_commit(h.repo.root)
    sync_mod.sync(open_repo(priya.root), actor="priya", sleep=lambda _s: None)
    assert verify_repository(open_repo(priya.root)).ok
    assert gitio.current_commit(priya.root) == _remote_head(h.bare)


def test_a_lead_can_resolve_a_conflict_by_editing_the_text(tmp_path: Path) -> None:
    h = hosted(tmp_path)
    priya = local_clone(h.bare, tmp_path / "priya-laptop")
    ethan = h.signed_in("ethan.g")
    post(
        ethan, "/criteria/EXC-01/edit",
        {"direction": "tightened", "definition": "Wrong population: the sample is not adult learners.", "rationale": "Rewording the criterion."},
    )  # fmt: skip
    criteria_mod.edit_criterion(
        priya, "EXC-01", direction="tightened", actor="priya", rationale="Rewording.",
        definition="Wrong population: the sample is children only.",
    )  # fmt: skip
    _commit(priya, "criteria: reword EXC-01", "priya")
    sync_mod.sync(priya, actor="priya", sleep=lambda _s: None)
    h.server.sync.run_due()
    conflict = h.server.sync.status("spacing").conflicts[0]
    merged = conflict["theirs"].replace("children only", "children or adolescents only")
    with_markers = post(
        ethan,
        "/-/sync",
        {
            "action": "resolve",
            "choice-0": "edit",
            "text-0": "<<<<<<< mine\nx\n=======\ny\n>>>>>>> theirs\n",
        },
    )
    assert with_markers.status_code == 303 and h.server.sync.status("spacing").blocked
    post(ethan, "/-/sync", {"action": "resolve", "choice-0": "edit", "text-0": merged})
    assert not h.server.sync.status("spacing").blocked
    assert "children or adolescents only" in h.repo.path("protocol", "criteria.yaml").read_text()
    assert _remote_head(h.bare) == gitio.current_commit(h.repo.root)


def test_an_unreachable_remote_is_retried_with_backoff_and_loses_nothing(tmp_path: Path) -> None:
    h = hosted(tmp_path)
    sam = h.signed_in("sam.okonkwo")
    record = _ids(h.repo)[0]
    away = tmp_path / "remote-away.git"
    shutil.move(str(h.bare), away)

    assert (
        post(
            sam, "/screen/title-abstract", {"record_id": record, "decision": "include"}
        ).status_code
        == 303
    )
    h.server.sync.flush("spacing", actor="sam")
    assert h.server.sync.run_due() == []
    first = h.server.sync.status("spacing")
    assert first.failures == 1 and first.push_pending and first.last_error
    assert first.next_retry == h.clock() + syncloop.RETRY_BASE
    # The dashboard reports the failure; the decision is committed on the instance.
    page = sam.get("/p/spacing/")
    assert "The last sync failed" in page.text
    assert ("sam", record, "include") in _decisions(h.repo)

    # Not retried before the backoff has passed; then retried, and the wait doubles.
    assert h.server.sync.run_due() == [] and h.server.sync.status("spacing").failures == 1
    h.clock.advance(syncloop.RETRY_BASE)
    assert h.server.sync.run_due() == []
    second = h.server.sync.status("spacing")
    assert second.failures == 2 and second.next_retry == h.clock() + 2 * syncloop.RETRY_BASE

    # The remote comes back: the next retry pushes everything.
    shutil.move(str(away), h.bare)
    h.clock.advance(2 * syncloop.RETRY_BASE)
    assert h.server.sync.run_due() == ["spacing"]
    assert h.server.sync.status("spacing").failures == 0
    assert _remote_head(h.bare) == gitio.current_commit(h.repo.root)
    leaving = local_clone(h.bare, tmp_path / "leaving")
    assert ("sam", record, "include") in _decisions(leaving)


def test_pull_before_read_fetches_a_local_collaborators_work_when_stale(tmp_path: Path) -> None:
    h = hosted(tmp_path)
    priya = local_clone(h.bare, tmp_path / "priya-laptop")
    sam = h.signed_in("sam.okonkwo")
    sam.get("/p/spacing/")  # the first page pulls
    fetched = h.server.sync.status("spacing").last_fetch
    _screen_locally(priya, "priya", _ids(priya)[:1])
    sync_mod.sync(priya, actor="priya", sleep=lambda _s: None)
    sam.get("/p/spacing/")  # within the interval: served from the instance's copy
    assert h.server.sync.status("spacing").last_fetch == fetched
    assert ("priya", _ids(priya)[0], "include") not in _decisions(h.repo)
    h.clock.advance(h.instance.settings.sync_interval + 1)
    sam.get("/p/spacing/records")
    assert ("priya", _ids(priya)[0], "include") in _decisions(h.repo)
