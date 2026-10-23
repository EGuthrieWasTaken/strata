"""The extraction, reconciliation and risk-of-bias screens (openspec:web-ui, M3)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from strata import gitio
from strata.core.events import read_events
from strata.core.repo import Repo
from strata.extract import records as rec_mod
from strata.extract import rob
from strata.web.app import create_app
from tests.unit._m3 import init_review
from tests.unit.test_extract_records import MEANS, _review, study

_TOKEN = "test-session-token-0123456789"
S1, S2 = study(1), study(2)
WHY = "Recording this for the review record."


def _commit(repo: Repo) -> Repo:
    gitio.add_all(repo.root)
    if gitio.is_dirty(repo.root):
        gitio.commit(repo.root, "chore: fixture\n\nStrata-Op: fixture\nStrata-Actor: ethan")
    return repo


def _client(repo: Repo, actor: str = "ethan") -> TestClient:
    app = create_app(repo_root=repo.root, actor=actor, session_token=_TOKEN)
    client = TestClient(app, base_url="http://127.0.0.1:8000")
    assert client.get(f"/?token={_TOKEN}").status_code == 200
    return client


def _post(client: TestClient, path: str, **data: str) -> Any:
    return client.post(path, data={"csrf_token": _TOKEN, **data}, follow_redirects=False)


def _subjects(repo: Repo) -> list[str]:
    return gitio.log(repo.root, fmt="%s")


# --- /extract --------------------------------------------------------------------------------


def test_the_coding_form_lists_every_field_with_a_source_input(tmp_path: Path) -> None:
    repo = _commit(_review(tmp_path))
    page = _client(repo).get(f"/extract/{S1}")
    assert page.status_code == 200
    for name in ("n_total", "design", "retention_interval", "mean_age"):
        assert f'name="field:{name}"' in page.text and f'name="source:{name}"' in page.text
    assert 'data-source-input="source-n_total"' in page.text
    assert "Author1" in page.text


def test_unknown_studies_and_a_missing_form_are_404(tmp_path: Path) -> None:
    repo = _commit(_review(tmp_path))
    client = _client(repo)
    assert client.get("/extract/std_nope").status_code == 404
    assert client.get("/rob/std_nope").status_code == 404
    assert client.get(f"/extract/{S1}/reconcile").status_code == 404  # single-reviewer extraction
    bare = _commit(init_review(tmp_path / "bare"))
    assert _client(bare).get("/extract").status_code == 404


def test_saving_fields_records_values_with_sources_and_commits(tmp_path: Path) -> None:
    repo = _commit(_review(tmp_path))
    response = _post(
        _client(repo),
        f"/extract/{S1}",
        **{
            "field:n_total": "148", "source:n_total": "Table 1",
            "field:design": "rct", "field:retention_interval": "1 week",
            "rationale": WHY,
        },
    )  # fmt: skip
    assert response.status_code == 303 and response.headers["location"] == f"/extract/{S1}"
    record = rec_mod.read_record(rec_mod.consensus_path(repo, S1))
    assert record is not None
    assert record["fields"]["n_total"] == {"value": 148, "source": "Table 1"}
    assert record["fields"]["retention_interval"]["value"] == 168
    assert _subjects(repo)[0].startswith("extract")
    assert not gitio.is_dirty(repo.root)


def test_invalid_values_and_a_missing_rationale_are_refused_without_writing(tmp_path: Path) -> None:
    repo = _commit(_review(tmp_path))
    client = _client(repo)
    bad = _post(client, f"/extract/{S1}", **{"field:n_total": "lots", "rationale": WHY})
    assert bad.status_code == 422 and "not a number" in bad.text
    terse = _post(client, f"/extract/{S1}", **{"field:n_total": "5", "rationale": ""})
    assert terse.status_code == 422
    assert not rec_mod.consensus_path(repo, S1).exists()


def test_the_effect_size_is_previewed_then_saved(tmp_path: Path) -> None:
    repo = _commit(_review(tmp_path))
    client = _client(repo)
    query = {
        "design": "two-group-means",
        "outcome": "recall",
        **{f"in:{k}": str(v) for k, v in MEANS.items()},
    }
    page = client.get(f"/extract/{S1}", params=query)
    assert "SMD = " in page.text and 'id="effect-save"' in page.text
    partial = client.get(f"/extract/{S1}", params={"design": "two-group-means", "in:n1": "74"})
    assert "Waiting for more inputs" in partial.text and 'id="effect-save"' not in partial.text
    assert not rec_mod.consensus_path(repo, S1).exists()  # previewing never writes

    saved = _post(
        client, f"/extract/{S1}",
        effect_design="two-group-means", effect_outcome="recall", effect_source="Table 2",
        rationale=WHY, **{f"in:{k}": str(v) for k, v in MEANS.items()},
    )  # fmt: skip
    assert saved.status_code == 303
    record = rec_mod.read_record(rec_mod.consensus_path(repo, S1))
    assert record is not None and record["effects"][0]["source"] == "Table 2"
    assert "SMD" in client.get(f"/extract/{S1}").text


def test_a_warning_is_shown_and_can_be_acknowledged_with_a_note(tmp_path: Path) -> None:
    repo = _commit(_review(tmp_path))
    client = _client(repo)
    huge = {
        "in:n1": "20",
        "in:m1": "9",
        "in:sd1": "1",
        "in:n2": "20",
        "in:m2": "4.5",
        "in:sd2": "1",
    }
    _post(
        client,
        f"/extract/{S1}",
        effect_design="two-group-means",
        effect_outcome="recall",
        rationale=WHY,
        **huge,
    )
    page = client.get(f"/extract/{S1}")
    assert "large-effect" in page.text and 'name="action" value="ack"' in page.text
    record = rec_mod.read_record(rec_mod.consensus_path(repo, S1))
    assert record is not None
    [(key, code, _m)] = rec_mod.open_warnings(repo, S1, record)
    done = _post(
        client,
        f"/extract/{S1}",
        action="ack",
        effect=key,
        code=code,
        note="Matches the paper",
        rationale=WHY,
    )
    assert done.status_code == 303
    assert "large-effect" not in client.get(f"/extract/{S1}").text
    [event] = [
        e for e in read_events(repo.path("events", "note", "ethan.ndjson")) if e["body"].get("code")
    ]
    assert event["body"]["text"] == "Matches the paper"


def test_the_index_lists_studies_and_what_they_lack(tmp_path: Path) -> None:
    repo = _review(tmp_path, studies=2)
    for name, raw in (("n_total", "1"), ("design", "rct"), ("retention_interval", "NR")):
        rec_mod.set_field(repo, study=S1, handle="ethan", name=name, raw=raw)
    page = _client(_commit(repo)).get("/extract")
    assert page.status_code == 200 and "complete" in page.text and "missing: n_total" in page.text


def test_forms_without_the_csrf_token_are_refused(tmp_path: Path) -> None:
    repo = _commit(_review(tmp_path))
    client = _client(repo)
    for path in (f"/extract/{S1}", f"/extract/{S1}/reconcile", f"/rob/{S1}"):
        assert client.post(path, data={"field:n_total": "1"}).status_code == 403


# --- /extract/<study>/reconcile --------------------------------------------------------------


def _dual(tmp_path: Path) -> Repo:
    repo = _review(tmp_path, mode="dual", studies=2)
    for handle, interval in (("ethan", "1 week"), ("sam", "24 hours")):
        for name, raw in (("n_total", "100"), ("design", "rct"), ("retention_interval", interval)):
            rec_mod.set_field(repo, study=S1, handle=handle, name=name, raw=raw)
    return _commit(repo)


def test_the_reconcile_screen_shows_each_reviewers_value(tmp_path: Path) -> None:
    page = _client(_dual(tmp_path)).get(f"/extract/{S1}/reconcile")
    assert page.status_code == 200
    assert "168 hours" in page.text and "24 hours" in page.text and "differ" in page.text
    assert "Accept all agreements" in page.text


def test_resolving_a_disagreement_in_the_browser_writes_the_same_event_as_the_cli(
    tmp_path: Path,
) -> None:
    """openspec scenario: a reconcile event is recorded exactly as the CLI would record it."""
    repo = _dual(tmp_path)
    client = _client(repo)
    _post(client, f"/extract/{S1}/reconcile", action="accept-agreements", commit_rationale=WHY)
    response = _post(
        client, f"/extract/{S1}/reconcile",
        item="field:retention_interval", choice="ethan", rationale="The Methods say one week.",
        commit_rationale=WHY,
    )  # fmt: skip
    assert response.status_code == 303
    events = read_events(repo.path("events", "reconcile", "ethan.ndjson"))
    chosen = next(e for e in events if e["body"]["field"] == "retention_interval")
    assert chosen["body"]["rationale"] == "The Methods say one week."
    assert chosen["body"]["chosen"] == 168 or chosen["body"]["chosen"] == "168 hours"
    consensus = rec_mod.read_record(rec_mod.consensus_path(repo, S1))
    assert consensus is not None and consensus["fields"]["retention_interval"]["value"] == 168
    assert _subjects(repo)[0].startswith("reconcile")
    assert "differ" not in client.get(f"/extract/{S1}/reconcile").text

    # the very same call the CLI makes produces the same shape of event
    from strata.extract import reconcile as reconcile_mod

    other = _dual(tmp_path / "again")
    reconcile_mod.resolve(
        other, study=S1, reconciler="ethan", item_id="field:retention_interval",
        choice="ethan", rationale="The Methods say one week.",
    )  # fmt: skip
    [cli_event] = [
        e
        for e in read_events(other.path("events", "reconcile", "ethan.ndjson"))
        if e["body"]["field"] == "retention_interval"
    ]
    assert set(cli_event["body"]) == set(chosen["body"])


def test_a_reconciliation_needs_a_rationale(tmp_path: Path) -> None:
    repo = _dual(tmp_path)
    response = _post(
        _client(repo), f"/extract/{S1}/reconcile",
        item="field:retention_interval", choice="ethan", rationale=" ", commit_rationale=WHY,
    )  # fmt: skip
    assert response.status_code == 422 and "rationale" in response.text
    assert not rec_mod.consensus_path(repo, S1).exists()


# --- /rob/<study> ----------------------------------------------------------------------------


def _rob_repo(tmp_path: Path, **kwargs: Any) -> Repo:
    repo = _review(tmp_path, **kwargs)
    rob.init_instrument(repo, "rob2")
    return _commit(repo)


def test_the_rob_screen_shows_the_domains_and_their_questions(tmp_path: Path) -> None:
    page = _client(_rob_repo(tmp_path)).get(f"/rob/{S1}")
    assert page.status_code == 200
    for fragment in ("D1: ", "D5: ", 'name="answer:1.1"', "Allocation sequence random", "Overall"):
        assert fragment in page.text


def test_there_is_no_rob_screen_before_an_instrument_is_chosen(tmp_path: Path) -> None:
    client = _client(_commit(_review(tmp_path)))
    assert client.get(f"/rob/{S1}").status_code == 404 and client.get("/rob").status_code == 404


def test_answers_then_a_judgement_are_recorded_with_the_suggestion(tmp_path: Path) -> None:
    repo = _rob_repo(tmp_path)
    client = _client(repo)
    for question, answer in (("1.1", "Y"), ("1.2", "Y"), ("1.3", "N")):
        _post(
            client,
            f"/rob/{S1}",
            action="answers",
            domain="D1",
            commit_rationale=WHY,
            **{f"answer:{question}": answer},
        )
    assert "The algorithm suggests <strong>low</strong>" in client.get(f"/rob/{S1}").text
    response = _post(
        client, f"/rob/{S1}", action="judgement", domain="D1", judgement="low",
        support="Central randomisation", source="p. 3", commit_rationale=WHY,
    )  # fmt: skip
    assert response.status_code == 303
    saved = rob.read_assessment(rob.consensus_path(repo, S1))
    assert saved is not None and saved["domains"]["D1"]["judgement"] == "low"
    [event] = read_events(repo.path("events", "rob", "ethan.ndjson"))
    assert event["body"]["suggested"] == "low" and event["body"]["source"] == "p. 3"
    assert _subjects(repo)[0].startswith("rob")


def test_overriding_the_suggestion_in_the_browser_needs_a_justification(tmp_path: Path) -> None:
    repo = _rob_repo(tmp_path)
    client = _client(repo)
    answers = {"answer:1.1": "Y", "answer:1.2": "Y", "answer:1.3": "N"}
    _post(client, f"/rob/{S1}", action="answers", domain="D1", commit_rationale=WHY, **answers)
    refused = _post(
        client,
        f"/rob/{S1}",
        action="judgement",
        domain="D1",
        judgement="high",
        commit_rationale=WHY,
    )
    assert refused.status_code == 422 and "justification" in refused.text
    accepted = _post(
        client, f"/rob/{S1}", action="judgement", domain="D1", judgement="high",
        override_justification="Registry shows the sequence was changed.", commit_rationale=WHY,
    )  # fmt: skip
    assert accepted.status_code == 303
    [event] = read_events(repo.path("events", "rob", "ethan.ndjson"))
    assert event["body"]["suggested"] == "low" and event["body"]["judgement"] == "high"


def test_the_rob_index_lists_studies(tmp_path: Path) -> None:
    page = _client(_rob_repo(tmp_path, studies=2)).get("/rob")
    assert page.status_code == 200 and "missing: domains" in page.text


def test_the_dashboard_links_to_the_new_screens_once_extraction_starts(tmp_path: Path) -> None:
    repo = _commit(_review(tmp_path))
    text = _client(repo).get("/").text
    assert 'href="/extract"' in text and 'href="/rob"' in text
