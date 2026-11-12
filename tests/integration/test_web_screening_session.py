"""The browser's screening session: when its decisions are committed, and the keys and counters.

`openspec:git-integration#batched-screening-commits`: a decision is written at once and committed
in a batch when the reviewer ends the session, at the 200th decision, or after 15 minutes without
one (#83). `openspec:web-ui#screening-surface-requirements`: a digit ticks a reason and decides
nothing, a skipped record comes back, and the counter counts decisions (#86).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from strata import gitio
from strata.core.init import init_repository
from strata.core.records import write_records
from strata.core.repo import Repo, open_repo
from strata.core.screen_batches import BATCH_IDLE, RECOVERED_BODY, BatchTracker
from strata.core.verify import verify_repository
from strata.protocol.criteria import add_criterion
from strata.protocol.screening import all_screen_events, record_screen_decision
from strata.web.app import commit_due_batches, create_app, leaves_the_screen

_TOKEN = "test-session-token-0123456789"
STAGE = "title-abstract"


def _id(n: int) -> str:
    return f"rec_{n:016d}"


def _record(n: int) -> dict:  # type: ignore[type-arg]
    return {
        "id": _id(n),
        "type": "article-journal",
        "title": f"Paper number {n}",
        "abstract": "An abstract.",
        "strata": {
            "canonical_key": f"sig:{n}",
            "canonical": True,
            "sources": [{"import": "imp_01arz3ndektsv4rrffq69g5fav"}],
        },
    }


def _review(tmp_path: Path, records: int = 4) -> Repo:
    """One reviewer, an inclusion and an exclusion criterion, `records` records, all committed."""
    root = tmp_path / "review"
    init_repository(root, title="Sessions", actor_handle="ethan", actor_name="Ethan Guthrie")
    for kind, label, cid in (
        ("inclusion", "Learners in formal education", "INC-01"),
        ("exclusion", "Not empirical", "EXC-01"),
    ):
        add_criterion(
            open_repo(root),
            kind=kind,  # type: ignore[arg-type]
            label=label,
            definition=f"{label}.",
            applies_at=[STAGE],
            actor="ethan",
            rationale="Establishing the initial protocol criteria.",
            criterion_id=cid,
        )
    write_records(open_repo(root), [_record(n) for n in range(1, records + 1)])
    gitio.add_all(root)
    gitio.commit(root, "chore: the review\n\nStrata-Op: fixture\n")
    return open_repo(root)


def _client(repo: Repo) -> TestClient:
    app = create_app(repo_root=repo.root, actor="ethan", session_token=_TOKEN)
    client = TestClient(app, base_url="http://127.0.0.1:8000")
    client.cookies.set("strata_session_8000", _TOKEN)
    return client


def _decide(client: TestClient, n: int, decision: str = "include", **more: str) -> object:
    data = {"csrf_token": _TOKEN, "record_id": _id(n), "decision": decision, "skip": "", **more}
    return client.post(f"/screen/{STAGE}", data=data, follow_redirects=False)


def _dirty(repo: Repo) -> list[str]:
    out = gitio.run(["status", "--porcelain", "--untracked-files=all"], cwd=repo.root).stdout
    return [line[3:] for line in out.splitlines()]


def _log(repo: Repo) -> list[str]:
    return gitio.run(["log", "--format=%s"], cwd=repo.root).stdout.splitlines()


def _body(repo: Repo, rev: str = "HEAD") -> str:
    return gitio.run(["log", "-1", "--format=%B", rev], cwd=repo.root).stdout


# ------------------------------------------------------------------------- when it commits


def test_a_decision_is_on_disk_at_once_and_committed_on_leaving_the_screen(tmp_path: Path) -> None:
    repo = _review(tmp_path)
    client = _client(repo)
    before = len(_log(repo))
    assert _decide(client, 1).status_code == 303  # type: ignore[attr-defined]
    assert _decide(client, 2, "exclude", criteria="EXC-01").status_code == 303  # type: ignore[attr-defined]
    # Still on the screening screen (the next record, the page's own script): nothing committed.
    client.get(f"/screen/{STAGE}")
    client.get("/static/keyboard.js")
    assert _dirty(repo) == [f"events/screen/{STAGE}.ethan.ndjson"]
    assert len(_log(repo)) == before

    dashboard = client.get("/")  # going anywhere else ends the session
    assert _dirty(repo) == []
    assert _log(repo)[0] == f"screen({STAGE}): screen 2 records (1 exclude, 1 include)"
    assert len(_log(repo)) == before + 1
    assert "has uncommitted changes" not in dashboard.text
    # the derived views were regenerated with the commit (a lone web decision used to leave four
    # E_DERIVED_DRIFT errors behind)
    issues = verify_repository(open_repo(repo.root)).issues
    assert not [i for i in issues if i.code == "E_DERIVED_DRIFT"]
    # and nothing more is committed by the next page
    client.get("/records")
    assert len(_log(repo)) == before + 1


def test_the_finish_button_commits_the_session_and_says_so(tmp_path: Path) -> None:
    repo = _review(tmp_path)
    client = _client(repo)
    page = client.get(f"/screen/{STAGE}")
    assert 'action="/session/finish"' in page.text and "Finish session" in page.text
    _decide(client, 1)
    done = client.post("/session/finish", data={"csrf_token": _TOKEN}, follow_redirects=False)
    assert done.status_code == 303 and done.headers["location"] == "/?finished=1"
    assert _dirty(repo) == []
    assert _log(repo)[0] == f"screen({STAGE}): screen 1 record (1 include)"
    assert "Screening session finished" in client.get("/?finished=1").text
    # Finishing with nothing pending is not an error and commits nothing.
    count = len(_log(repo))
    again = client.post("/session/finish", data={"csrf_token": _TOKEN}, follow_redirects=False)
    assert again.status_code == 303 and len(_log(repo)) == count


def test_finishing_needs_the_csrf_token(tmp_path: Path) -> None:
    client = _client(_review(tmp_path))
    assert client.post("/session/finish", data={}).status_code == 403


def test_the_batch_size_commits_without_being_asked(tmp_path: Path) -> None:
    repo = _review(tmp_path)
    client = _client(repo)
    client.app.state.strata.batches = BatchTracker(size=3)  # type: ignore[attr-defined]
    _decide(client, 1)
    _decide(client, 2)
    assert _dirty(repo) != []
    _decide(client, 3)  # the third uncommitted decision is the batch
    assert _dirty(repo) == []
    assert _log(repo)[0] == f"screen({STAGE}): screen 3 records (3 include)"
    _decide(client, 4)  # and the count starts again
    assert _dirty(repo) == [f"events/screen/{STAGE}.ethan.ndjson"]


def test_fifteen_idle_minutes_commit_the_batch(tmp_path: Path) -> None:
    repo = _review(tmp_path)
    client = _client(repo)
    now = [1000.0]
    state = client.app.state.strata  # type: ignore[attr-defined]
    state.batches = BatchTracker(clock=lambda: now[0])
    _decide(client, 1)
    now[0] += BATCH_IDLE - 1
    assert commit_due_batches(state) == 0 and _dirty(repo) != []
    _decide(client, 2)  # a decision restarts the wait
    now[0] += BATCH_IDLE - 1
    assert commit_due_batches(state) == 0 and _dirty(repo) != []
    now[0] += 1
    assert commit_due_batches(state) == 1 and _dirty(repo) == []
    assert _log(repo)[0] == f"screen({STAGE}): screen 2 records (2 include)"
    assert commit_due_batches(state) == 0


def test_what_counts_as_leaving_the_screen() -> None:
    assert leaves_the_screen("GET", "/")
    assert leaves_the_screen("GET", "/records/rec_1")
    assert not leaves_the_screen("GET", f"/screen/{STAGE}")
    assert not leaves_the_screen("GET", f"/rescreen/{STAGE}")
    assert not leaves_the_screen("GET", "/static/style.css")
    assert not leaves_the_screen("GET", "/healthz")
    assert not leaves_the_screen("POST", "/criteria/new")  # a write flushes by its own rule


def test_serve_commits_what_an_earlier_server_left_and_what_is_pending_when_it_stops(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Startup recovery and shutdown, through `serve_until_idle_or_interrupted` with the network
    part replaced: the server "runs" for as long as it takes to record one decision."""
    import asyncio

    import uvicorn

    from strata.web import server as server_mod

    repo = _review(tmp_path)
    record_screen_decision(repo, stage=STAGE, record_id=_id(1), decision="include", actor="ethan")
    seen: dict[str, object] = {}

    async def fake_serve(self: uvicorn.Server) -> None:
        seen["log_at_start"] = _log(repo)
        seen["dirty_at_start"] = _dirty(repo)
        state = self.config.app.state.strata  # type: ignore[union-attr]
        record_screen_decision(
            open_repo(repo.root), stage=STAGE, record_id=_id(2), decision="maybe", actor="ethan"
        )
        state.batches.note("ethan")
        self.should_exit = True

    monkeypatch.setattr(uvicorn.Server, "serve", fake_serve)
    params = server_mod.ServeParams(
        repo_root=repo.root,
        actor="ethan",
        host="127.0.0.1",
        port=8000,
        session_token=_TOKEN,
        inactivity_timeout=10.0,
    )
    asyncio.run(server_mod.serve_until_idle_or_interrupted(params))

    assert seen["dirty_at_start"] == []
    assert seen["log_at_start"][0] == f"screen({STAGE}): screen 1 record (1 include)"  # type: ignore[index]
    assert RECOVERED_BODY in _body(repo, "HEAD~1")
    assert _dirty(repo) == []
    assert _log(repo)[0] == f"screen({STAGE}): screen 1 record (1 maybe)"


# ------------------------------------------------------------------- a change of mind


def test_changing_a_decision_needs_a_reason_and_the_batch_carries_it(tmp_path: Path) -> None:
    repo = _review(tmp_path)
    client = _client(repo)
    _decide(client, 1, "exclude", criteria="EXC-01")
    undo = client.get(f"/screen/{STAGE}?redo={_id(1)}")
    assert "You decided EXCLUDE for this record" in undo.text and "citing EXC-01" in undo.text
    assert "Why the change?" in undo.text

    refused = _decide(client, 1, "include")
    assert refused.status_code == 422  # type: ignore[attr-defined]
    assert "Say why it is now INCLUDE" in refused.text  # type: ignore[attr-defined]
    assert len(all_screen_events(open_repo(repo.root), STAGE)) == 1

    # The same decision again is not a change and asks for nothing.
    assert _decide(client, 2).status_code == 303  # type: ignore[attr-defined]
    assert _decide(client, 2).status_code == 303  # type: ignore[attr-defined]

    assert _decide(client, 1, "include", note="Pressed the wrong key.").status_code == 303  # type: ignore[attr-defined]
    client.get("/")
    body = " ".join(_body(repo).split())  # the message is wrapped
    assert "Changed decisions:" in body
    assert f"- {_id(1)} at {STAGE}: exclude -> include. Why: Pressed the wrong key." in body
    assert _id(2) not in body


def test_a_change_to_a_committed_decision_is_listed_too(tmp_path: Path) -> None:
    repo = _review(tmp_path)
    client = _client(repo)
    _decide(client, 1)
    client.get("/")  # committed
    _decide(client, 1, "exclude", criteria="EXC-01", note="On reflection it is a commentary.")
    client.get("/")
    assert _log(repo)[0] == f"screen({STAGE}): screen 1 record (1 exclude)"
    assert "include -> exclude. Why: On reflection it is a commentary." in " ".join(
        _body(repo).split()
    )


# ------------------------------------------------------------------------ keys and counters


def test_a_refused_exclusion_keeps_the_place_and_speaks_plainly(tmp_path: Path) -> None:
    repo = _review(tmp_path)
    client = _client(repo)
    _decide(client, 1)
    refused = _decide(client, 2, "exclude", note="half a thought")
    assert refused.status_code == 422  # type: ignore[attr-defined]
    text = refused.text  # type: ignore[attr-defined]
    assert f"{STAGE} screening &mdash; 2 of 4" in text and "<progress" in text
    assert "Paper number 2" in text and "half a thought" in text
    # In the reviewer's words; the setting follows, muted, for whoever looks it up.
    assert "Tick at least one reason before excluding." in text
    assert "an exclude decision requires" not in text
    assert (
        '<p class="field-meta error-detail">Setting: screening.require_exclusion_reason</p>' in text
    )


def test_the_reasons_are_numbered_as_the_command_line_numbers_them(tmp_path: Path) -> None:
    page = _client(_review(tmp_path)).get(f"/screen/{STAGE}").text
    first = page.index('value="INC-01" data-shortcut-digit="1"')
    second = page.index('value="EXC-01" data-shortcut-digit="2"')
    assert first < second
    # An inclusion criterion is cited because the record fails it, and the page says so.
    assert "Not met:</span> Learners in formal education" in page
    assert "Reasons for excluding (at least one is needed to exclude)" in page


def test_a_skipped_record_comes_back_when_the_rest_are_done(tmp_path: Path) -> None:
    repo = _review(tmp_path, records=3)
    client = _client(repo)
    skip = _id(1)
    second = client.get(f"/screen/{STAGE}?skip={skip}")
    # The counter counts decisions: nothing is decided, so this is still the first.
    assert f"{STAGE} screening &mdash; 1 of 3" in second.text and "Paper number 2" in second.text
    assert "0 of 3 decided" in second.text and "1 skipped for now" in second.text
    _decide(client, 2, skip=skip)
    third = client.get(f"/screen/{STAGE}?skip={skip}&prev={_id(2)}")
    assert f"{STAGE} screening &mdash; 2 of 3" in third.text
    # the undo link keeps the skip list
    assert f"redo={_id(2)}&amp;skip={skip}" in third.text
    _decide(client, 3, skip=skip)

    done = client.get(f"/screen/{STAGE}?skip={skip}&prev={_id(3)}", follow_redirects=False)
    assert done.status_code == 303
    assert done.headers["location"] == f"/screen/{STAGE}?prev={_id(3)}&again=1"
    back = client.get(done.headers["location"])
    assert "Nothing left to screen" not in back.text
    assert "These are the records you skipped" in back.text and "Paper number 1" in back.text
    assert f"{STAGE} screening &mdash; 3 of 3" in back.text
    _decide(client, 1)
    assert "Nothing left to screen" in client.get(f"/screen/{STAGE}").text


def test_undo_shows_the_record_as_one_already_counted(tmp_path: Path) -> None:
    repo = _review(tmp_path)
    client = _client(repo)
    _decide(client, 1)
    _decide(client, 2)
    undo = client.get(f"/screen/{STAGE}?redo={_id(2)}")
    assert f"{STAGE} screening &mdash; 2 of 4" in undo.text  # not "3 of 4"


def test_the_keyboard_script_ticks_on_a_digit_and_never_excludes(tmp_path: Path) -> None:
    """The script is exercised in a browser by `tests/browser`; this guards the rule in its text:
    the digit branch must not reach for the Exclude button."""
    script = _client(_review(tmp_path)).get("/static/keyboard.js").text
    start = script.index('if (key >= "1" && key <= "9")')
    digit_branch = script[start : script.index('if (key === "s")', start)]
    assert "checkbox.checked = !checkbox.checked" in digit_branch
    assert ".click()" not in digit_branch and "exclude" not in digit_branch.split("//")[0]
