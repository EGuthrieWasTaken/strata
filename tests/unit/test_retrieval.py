"""Full-text retrieval (openspec:full-text-retrieval)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from strata.core import fulltext
from strata.core.events import read_events
from strata.core.status import compute_status
from strata.core.verify import verify_repository
from strata.protocol import pool as pool_mod
from strata.protocol import retrieval
from tests.unit._m3 import add_records, decide, init_review, rec, rpt


def _setup(tmp_path: Path, n: int = 3):  # type: ignore[no-untyped-def]
    repo = init_review(tmp_path)
    ids = add_records(repo, n)
    decide(repo, "title-abstract", ids)
    return repo


def _codes(repo) -> set[str]:  # type: ignore[no-untyped-def]
    return {i.code for i in verify_repository(repo).issues}


def test_reports_sought_are_records_included_at_title_abstract(tmp_path: Path) -> None:
    repo = init_review(tmp_path)
    ids = add_records(repo, 4)
    decide(repo, "title-abstract", [ids[0], ids[1]])
    decide(repo, "title-abstract", [ids[2]], decision="maybe")  # both unsure: a conflict
    decide(repo, "title-abstract", [ids[3]], actors=("ethan",))  # only one of two reviewers
    assert retrieval.sought_reports(repo) == [rpt(1), rpt(2)]


def test_retrieved_writes_an_event_and_a_manifest_entry_but_no_file(tmp_path: Path) -> None:
    repo = _setup(tmp_path)
    event = retrieval.record_retrieval(
        repo,
        report=rpt(1),
        status="retrieved",
        actor="ethan",
        source="institutional-access",
        version="version-of-record",
        path="cepeda-2008.pdf",
        retrieved_on="2026-03-28",
    )
    assert event["body"] == {
        "report": rpt(1),
        "status": "retrieved",
        "source": "institutional-access",
        "locator": {"doi": "10.1000/test.1"},
        "version": "version-of-record",
    }
    [entry] = fulltext.read_manifest(repo)
    assert entry == {
        "report": rpt(1),
        "locator": {"doi": "10.1000/test.1"},
        "version": "version-of-record",
        "path": "cepeda-2008.pdf",
        "retrieved": "2026-03-28",
        "source": "institutional-access",
        "actor": "ethan",
    }
    assert not list(repo.root.rglob("*.pdf"))  # the document itself is never written
    assert read_events(repo.path("events", "retrieval", "ethan.ndjson"))[0]["ev"] == "retrieval"


def test_retrieved_defaults_the_date_and_version(tmp_path: Path) -> None:
    repo = _setup(tmp_path)
    retrieval.record_retrieval(
        repo, report=rpt(1), status="retrieved", actor="ethan", source="open-access"
    )
    [entry] = fulltext.read_manifest(repo)
    assert entry["version"] == "unknown"
    assert len(entry["retrieved"]) == 10


def test_an_explicit_locator_overrides_the_records_identifiers(tmp_path: Path) -> None:
    repo = _setup(tmp_path)
    retrieval.record_retrieval(
        repo,
        report=rpt(1),
        status="retrieved",
        actor="ethan",
        source="author-copy",
        locator={"pmid": "19076480"},
        related=[{"doi": "10.1000/preprint.1"}],
        sha256="a" * 64,
    )
    [entry] = fulltext.read_manifest(repo)
    assert entry["locator"] == {"pmid": "19076480"}
    assert entry["related"] == [{"doi": "10.1000/preprint.1"}]
    assert entry["sha256"] == "a" * 64


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"status": "lost"}, "status must be one of"),
        ({"status": "retrieved"}, "needs a source"),
        ({"status": "not-retrieved"}, "needs a reason"),
        ({"status": "not-retrieved", "reason": "bored"}, "needs a reason"),
        ({"status": "not-retrieved", "reason": "other"}, "needs free text"),
        ({"status": "retrieved", "source": "x", "version": "final-final"}, "version"),
    ],
)
def test_invalid_outcomes_are_refused_and_write_nothing(
    tmp_path: Path, kwargs: dict[str, str], message: str
) -> None:
    repo = _setup(tmp_path)
    with pytest.raises((retrieval.RetrievalError, ValueError), match=message):
        retrieval.record_retrieval(repo, report=rpt(1), actor="ethan", **kwargs)  # type: ignore[arg-type]
    assert retrieval.all_retrieval_events(repo) == []
    assert fulltext.read_manifest(repo) == []


def test_a_report_that_is_not_sought_is_refused(tmp_path: Path) -> None:
    repo = init_review(tmp_path)
    add_records(repo, 2)
    with pytest.raises(retrieval.RetrievalError, match="not a report sought"):
        retrieval.record_retrieval(
            repo, report=rpt(1), status="not-retrieved", actor="ethan", reason="no-access"
        )


def test_a_record_without_any_identifier_needs_an_explicit_locator(tmp_path: Path) -> None:
    repo = init_review(tmp_path)
    from tests.unit._m3 import record

    r = record(1)
    del r["DOI"]
    ids = add_records(repo, [r])
    decide(repo, "title-abstract", ids)
    with pytest.raises(retrieval.RetrievalError, match="no DOI or other identifier"):
        retrieval.record_retrieval(
            repo, report=rpt(1), status="retrieved", actor="ethan", source="s"
        )


def test_not_retrieved_reasons_are_counted(tmp_path: Path) -> None:
    repo = _setup(tmp_path, 4)
    retrieval.record_retrieval(
        repo, report=rpt(1), status="not-retrieved", actor="ethan", reason="no-response-from-author"
    )
    retrieval.record_retrieval(
        repo, report=rpt(2), status="not-retrieved", actor="ethan", reason="no-access"
    )
    retrieval.record_retrieval(
        repo,
        report=rpt(3),
        status="not-retrieved",
        actor="ethan",
        reason="other",
        reason_text="  withdrawn by publisher ",
    )
    retrieval.record_retrieval(repo, report=rpt(4), status="ill-requested", actor="sam")
    counts = retrieval.retrieval_counts(repo)
    assert (counts.sought, counts.not_retrieved, counts.outstanding, counts.ill_requested) == (
        4,
        3,
        1,
        1,
    )
    assert counts.reasons == {"no-access": 1, "no-response-from-author": 1, "other": 1}
    event = retrieval.all_retrieval_events(repo)[2]
    assert event["body"]["reason_text"] == "withdrawn by publisher"


def test_outstanding_reports_shrink_as_outcomes_are_recorded(tmp_path: Path) -> None:
    repo = _setup(tmp_path, 3)
    assert retrieval.outstanding_reports(repo) == [rpt(1), rpt(2), rpt(3)]
    retrieval.record_retrieval(repo, report=rpt(1), status="retrieved", actor="ethan", source="s")
    retrieval.record_retrieval(repo, report=rpt(2), status="ill-requested", actor="ethan")
    assert retrieval.outstanding_reports(repo) == [rpt(2), rpt(3)]  # ILL is still outstanding
    retrieval.record_retrieval(repo, report=rpt(1), status="sought", actor="ethan")  # reopened
    assert retrieval.outstanding_reports(repo) == [rpt(1), rpt(2), rpt(3)]
    states = retrieval.retrieval_states(repo)
    assert retrieval.status_of(states, rpt(3)) == "sought"
    assert retrieval.status_of(states, rpt(2)) == "ill-requested"


def test_204_sought_8_outstanding_scenario_in_miniature(tmp_path: Path) -> None:
    repo = _setup(tmp_path, 10)
    for n in range(1, 9):
        retrieval.record_retrieval(
            repo, report=rpt(n), status="retrieved", actor="ethan", source="s"
        )
    counts = retrieval.retrieval_counts(repo)
    assert (counts.sought, counts.outstanding, counts.retrieved) == (10, 2, 8)


def test_not_retrieved_report_shows_in_the_pool_view(tmp_path: Path) -> None:
    repo = _setup(tmp_path, 2)
    retrieval.record_retrieval(
        repo, report=rpt(1), status="not-retrieved", actor="ethan", reason="not-found"
    )
    rows = pool_mod.regenerate_pool_tsv(repo).splitlines()
    header = rows[0].split("\t")
    by_id = {r.split("\t")[0]: dict(zip(header, r.split("\t"), strict=True)) for r in rows[1:]}
    assert by_id[rec(1)]["fulltext"] == "not-retrieved"
    assert by_id[rec(2)]["fulltext"] == "unscreened"


def test_status_reports_retrieval_and_recommends_it(tmp_path: Path) -> None:
    repo = _setup(tmp_path, 3)
    status = compute_status(repo)
    assert status.retrieval is not None
    assert (status.retrieval.sought, status.retrieval.outstanding) == (3, 3)
    assert status.next_action == "strata retrieve"


def test_status_has_no_retrieval_line_before_anything_is_sought(tmp_path: Path) -> None:
    repo = init_review(tmp_path)
    add_records(repo, 2)
    status = compute_status(repo)
    assert status.retrieval is not None and status.retrieval.sought == 0
    assert status.next_action != "strata retrieve"


# --- the manifest and verify ----------------------------------------------------------------


def test_locator_helpers() -> None:
    assert fulltext.locator_key({"pmid": "1", "doi": "10.1/x"}) == "doi:10.1/x"
    assert fulltext.locator_key({"url": "https://x"}) == "url:https://x"
    with pytest.raises(ValueError):
        fulltext.locator_key({})
    assert fulltext.locator_from_record({"DOI": "https://doi.org/10.1000/ABC", "PMID": 7}) == {
        "doi": "10.1000/abc",
        "pmid": "7",
    }
    assert fulltext.locator_from_record({}) == {}


def test_manifest_keeps_the_latest_entry_per_report(tmp_path: Path) -> None:
    repo = _setup(tmp_path, 1)
    for version in ("preprint", "version-of-record"):
        retrieval.record_retrieval(
            repo, report=rpt(1), status="retrieved", actor="ethan", source="s", version=version
        )
    entries = fulltext.read_manifest(repo)
    assert len(entries) == 2
    assert fulltext.latest_by_report(entries)[rpt(1)]["version"] == "version-of-record"


def test_different_hashes_for_the_same_document_are_not_an_error(tmp_path: Path) -> None:
    """openspec:full-text-retrieval#documents-are-never-identified-by-content-hash."""
    repo = _setup(tmp_path, 1)
    for actor, digest in (("ethan", "a" * 64), ("sam", "b" * 64)):
        retrieval.record_retrieval(
            repo, report=rpt(1), status="retrieved", actor=actor, source="s", sha256=digest
        )
    report = verify_repository(repo)
    assert [i for i in report.issues if "sha256" in i.message or "hash" in i.message] == []
    assert _codes(repo) == set()


def test_verify_flags_a_malformed_manifest_and_an_unknown_report(tmp_path: Path) -> None:
    repo = _setup(tmp_path, 1)
    path = fulltext.manifest_path(repo)
    path.parent.mkdir(parents=True, exist_ok=True)
    good = {
        "report": rpt(99),
        "locator": {"doi": "10.1/x"},
        "version": "unknown",
        "retrieved": "2026-01-01",
        "source": "s",
        "actor": "ethan",
    }
    path.write_text(
        "\n".join(
            [
                json.dumps(good),
                json.dumps({**good, "version": "final-final"}),
                "{not json",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    codes = _codes(repo)
    assert {"E_SCHEMA", "E_DANGLING_REF"} <= codes


def test_verify_checks_the_body_of_retrieval_events(tmp_path: Path) -> None:
    repo = _setup(tmp_path, 1)
    retrieval.record_retrieval(
        repo, report=rpt(1), status="not-retrieved", actor="ethan", reason="no-access"
    )
    assert _codes(repo) == set()
    path = repo.path("events", "retrieval", "ethan.ndjson")
    from strata.core.events import append_new_event

    append_new_event(
        path, ev="retrieval", actor="ethan", body={"report": rpt(1), "status": "not-retrieved"}
    )
    assert "E_SCHEMA" in _codes(repo)


def test_verify_flags_a_retrieval_for_a_missing_record(tmp_path: Path) -> None:
    repo = _setup(tmp_path, 1)
    from strata.core.events import append_new_event

    append_new_event(
        repo.path("events", "retrieval", "ethan.ndjson"),
        ev="retrieval",
        actor="ethan",
        body={"report": rpt(404), "status": "sought"},
    )
    assert "E_DANGLING_REF" in _codes(repo)
