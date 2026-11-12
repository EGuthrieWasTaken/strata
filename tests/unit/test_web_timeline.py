"""A record's provenance and the history are shown as who did what, when and why (#87)."""

from __future__ import annotations

from pathlib import Path

from strata import gitio
from strata.core.init import init_repository
from strata.core.logcmd import DomainCommit, _reason, domain_log
from strata.core.provenance import ProvenanceEntry
from strata.core.repo import open_repo
from strata.web import timeline


def _entry(kind: str, body: dict, *, actor: str | None = "ada") -> ProvenanceEntry:  # type: ignore[type-arg]
    return ProvenanceEntry(kind=kind, ts="2026-11-06T13:04:05Z", actor=actor, detail=body)


def test_times_are_shown_in_utc_and_say_so() -> None:
    assert timeline.when("2026-11-06T13:04:05Z") == "6 Nov 2026, 13:04 UTC"
    assert timeline.when("2026-11-06T08:04:05-05:00") == "6 Nov 2026, 13:04 UTC"
    assert timeline.when("2026-11-06T13:04:05") == "6 Nov 2026, 13:04"
    assert timeline.when("last Tuesday") == "last Tuesday"
    assert timeline.when(None) == ""


def test_stored_values_are_written_as_a_person_would() -> None:
    assert timeline.shown(None) == "none" and timeline.shown([]) == "none"
    assert timeline.shown(["a.ris", "b.ris"]) == "a.ris, b.ris"
    assert timeline.shown(True) == "yes"
    assert timeline.shown({"peer_reviewed_by": None}) == "Peer reviewed by: none"
    assert timeline.label_of("export_files") == "Export files"


def test_a_correction_is_a_sentence_with_its_reason() -> None:
    record = "rec_1qjn6pvab3h794qe"
    commits = [  # newest first, as the log gives them
        DomainCommit("c3", f"fix({record}): corrected page", {"Op": "fix"}, reason="Wrong pages."),
        DomainCommit("c2", f"fix({record}): corrected year", {"Op": "fix"}, reason="Per the DOI."),
        DomainCommit("c1", f"fix({record}): corrected title", {"Op": "fix"}, reason="Truncated."),
        DomainCommit("c0", "fix(rec_other): corrected title", {"Op": "fix"}, reason="Not ours."),
    ]
    steps = timeline.timeline(
        [
            _entry(
                "record-amend", {"record": record, "field": "title", "old": "Old", "new": "New"}
            ),
            _entry(
                "record-amend", {"record": record, "field": "issued", "old": "2020", "new": "2019"}
            ),
            _entry("record-amend", {"record": record, "field": "page", "old": "1-9", "new": None}),
            _entry("record-amend", {"record": record, "field": "volume", "old": None, "new": "7"}),
        ],
        record_id=record,
        commits=commits,
    )
    assert steps[0].text == "ada corrected the title: it was “Old” and is now “New”."
    assert steps[0].why == "Truncated." and steps[0].when == "6 Nov 2026, 13:04 UTC"
    assert steps[1].text.startswith("ada corrected the date") and steps[1].why == "Per the DOI."
    assert steps[2].text == "ada removed the pages (it was “1-9”)."
    assert steps[2].why == "Wrong pages."
    assert steps[3].text == "ada filled in the volume: “7”." and steps[3].why == ""
    for step in steps:
        assert step.label == "Correction" and "None" not in step.text


def test_every_kind_of_entry_reads_as_a_sentence() -> None:
    record = "rec_a"
    cases = {
        "search": {"id": "S-01-medline", "database": "MEDLINE", "platform": "Ovid",
                   "executed_by": "ada", "executed": "2026-10-01", "hits": 8,
                   "export_files": ["m.ris"], "peer_reviewed_by": None, "query": "PENDING"},
        "import": {"source": "m.ris", "count": 1, "import_id": "imp_1"},
        "record-add": {"record": record, "import_id": "imp_1"},
        "screen": {"stage": "title-abstract", "decision": "exclude", "criteria": ["EXC-01"],
                   "criteria_version": 4, "note": "Animal study."},
        "adjudicate": {"stage": "title-abstract", "decision": "include", "criteria": [],
                       "rationale": "Meets INC-01."},
        "dedup-merge": {"canonical": record, "absorbed": "rec_b"},
        "dedup-distinct": {"a": record, "b": "rec_c"},
        "dedup-unmerge": {"canonical": record, "restored": "rec_b"},
        "suggestion": {"op": "screen", "args": {"decision": "include"}, "status": "pending",
                       "rationale": "Looks relevant."},
        "suggestion-resolve": {"outcome": "accepted", "reason": "Agreed."},
        "something-new": {"some_key": None, "other": ["x", "y"]},
    }  # fmt: skip
    steps = {k: timeline.describe(_entry(k, body), record_id=record) for k, body in cases.items()}
    assert steps["search"].text == (
        "Found by the search S-01-medline of MEDLINE on Ovid, run by ada on 2026-10-01."
    )
    assert ("Query", "not recorded yet") in steps["search"].details
    assert ("Export files", "m.ris") in steps["search"].details
    assert steps["import"].text == "ada imported m.ris (1 record)."
    assert steps["screen"].text == "ada decided EXCLUDE at title-abstract, citing EXC-01."
    assert steps["screen"].why == "Animal study."
    assert steps["adjudicate"].why == "Meets INC-01."
    assert "merged rec_b into this record" in steps["dedup-merge"].text
    assert "kept this record and rec_c apart" in steps["dedup-distinct"].text
    assert "rec_b is a record of its own again" in steps["dedup-unmerge"].text
    assert steps["suggestion-resolve"].why == "Agreed."
    assert steps["something-new"].details == [("Some key", "none"), ("Other", "x, y")]
    merged_away = timeline.describe(
        _entry("dedup-merge", {"canonical": "rec_z", "absorbed": record}), record_id=record
    )
    assert "merged this record into rec_z" in merged_away.text
    for step in steps.values():
        text = step.text + " ".join(f"{a} {b}" for a, b in step.details)
        assert "None" not in text and "['" not in text and "_by" not in text


def test_the_reason_is_the_body_without_subject_or_trailers() -> None:
    message = (
        "screen(title-abstract): screen 2 records (2 include)\n\n"
        "Screening decisions recorded in the\nbrowser.\n\n"
        "Changed decisions:\n- rec_a at title-abstract: exclude -> include. Why: wrong\nkey\n\n"
        "Strata-Op: screen\nStrata-Actor: ada\n\nCo-Authored-By: Someone <s@example.org>\n"
    )
    assert _reason(message) == (
        "Screening decisions recorded in the browser.\n"
        "Changed decisions:\n"
        "- rec_a at title-abstract: exclude -> include. Why: wrong key"
    )
    assert _reason("init: create the review\n") == ""


def test_the_log_carries_when_and_why(tmp_path: Path) -> None:
    root = tmp_path / "review"
    init_repository(root, title="Log", actor_handle="ada", actor_name="Ada")
    (root / "note.txt").write_text("x\n")
    gitio.add_all(root)
    gitio.commit(
        root, "fix(rec_a): corrected title\n\nThe export cut it\nshort.\n\nStrata-Op: fix\n"
    )
    newest = domain_log(open_repo(root))[0]
    assert newest.reason == "The export cut it short." and newest.trailers == {"Op": "fix"}
    assert timeline.when(newest.date).endswith(" UTC")
