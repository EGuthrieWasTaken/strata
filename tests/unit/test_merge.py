"""The merge drivers and the normalisation of merged event files
(openspec:git-integration#merge-drivers, openspec:event-log)."""

# ruff: noqa: E501
from __future__ import annotations

import json
from pathlib import Path

from strata.core import merge
from strata.core.canon import canonical_json
from strata.core.events import append_new_event, read_events, verify_chain


def _rec(i: int, **fields: object) -> dict[str, object]:
    base: dict[str, object] = {
        "id": f"rec_{i:016d}",
        "type": "article-journal",
        "title": f"Title {i}",
        "strata": {
            "canonical_key": f"sig:{i}",
            "canonical": True,
            "sources": [{"import": "imp_a", "row": i, "database": "pubmed"}],
        },
    }
    base.update(fields)
    return base


def _text(*records: dict[str, object]) -> str:
    return "".join(canonical_json(r) + "\n" for r in sorted(records, key=lambda r: str(r["id"])))


def _ids(text: str) -> list[str]:
    return [json.loads(line)["id"] for line in text.splitlines()]


def test_regenerate_driver_has_nothing_to_decide() -> None:
    assert merge.merge_regenerate() is None


def test_an_id_on_one_side_only_is_kept_and_identical_ids_are_kept() -> None:
    base = _text(_rec(1))
    text, notes = merge.merge_records_text(base, _text(_rec(1), _rec(2)), _text(_rec(1), _rec(3)))
    assert _ids(text) == [_rec(1)["id"], _rec(2)["id"], _rec(3)["id"]] and notes == []


def test_a_field_changed_on_one_side_wins_without_a_note() -> None:
    base = _text(_rec(1, title="Old"))
    text, notes = merge.merge_records_text(
        base, _text(_rec(1, title="Old")), _text(_rec(1, title="New", DOI="10.1/x"))
    )
    merged = json.loads(text)
    assert merged["title"] == "New" and merged["DOI"] == "10.1/x" and notes == []


def test_sources_are_a_set_union() -> None:
    a, b = _rec(1), _rec(1)
    a["strata"] = {
        "canonical": True,
        "canonical_key": "sig:1",
        "sources": [{"import": "imp_a", "row": 1}],
    }
    b["strata"] = {
        "canonical": True,
        "canonical_key": "sig:1",
        "sources": [{"import": "imp_a", "row": 1}, {"import": "imp_b", "row": 4, "via": "website"}],
    }
    text, _ = merge.merge_records_text(_text(_rec(1)), _text(a), _text(b))
    assert [s["import"] for s in json.loads(text)["strata"]["sources"]] == ["imp_a", "imp_b"]


def test_a_record_merged_away_on_either_side_stays_merged_away() -> None:
    gone = _rec(1)
    gone["strata"] = {
        "canonical_key": "sig:1",
        "canonical": False,
        "sources": [{"import": "imp_a", "row": 1}],
    }
    text, _ = merge.merge_records_text(_text(_rec(1)), _text(gone), _text(_rec(1, title="Edited")))
    merged = json.loads(text)
    assert merged["strata"]["canonical"] is False and merged["title"] == "Edited"


def test_both_changed_goes_to_the_more_trusted_source() -> None:
    base = _text(_rec(1, title="Base"))
    ours = _rec(1, title="From scopus")
    ours["strata"] = {
        "canonical_key": "sig:1",
        "canonical": True,
        "sources": [{"database": "scopus"}],
    }
    theirs = _rec(1, title="From crossref")
    theirs["strata"] = {
        "canonical_key": "sig:1",
        "canonical": True,
        "sources": [{"database": "crossref"}],
    }
    text, notes = merge.merge_records_text(
        base, _text(ours), _text(theirs), trust=["Crossref", "PubMed", "Scopus"]
    )
    assert json.loads(text)["title"] == "From crossref"
    assert [(n.field, n.reason) for n in notes] == [
        ("title", "the more trusted source (dedup.source_trust) wins")
    ]


def test_both_changed_with_equal_trust_keeps_the_longer_abstract() -> None:
    base = _text(_rec(1, abstract="A"))
    text, notes = merge.merge_records_text(
        base,
        _text(_rec(1, abstract="short")),
        _text(_rec(1, abstract="a much longer abstract")),
        trust=["pubmed"],
    )
    assert json.loads(text)["abstract"] == "a much longer abstract"
    assert notes[0].reason == "the longer abstract wins" and notes[0].old == "short"


def test_both_changed_otherwise_takes_the_lexicographically_smaller_value() -> None:
    base = _text(_rec(1, title="Base"))
    text, notes = merge.merge_records_text(
        base, _text(_rec(1, title="Beta")), _text(_rec(1, title="Alpha"))
    )
    assert (
        json.loads(text)["title"] == "Alpha"
        and notes[0].reason == "the lexicographically smaller value wins"
    )


def test_merging_is_symmetric_in_its_result() -> None:
    base = _text(_rec(1, title="Base", abstract="A"))
    ours = _text(_rec(1, title="Beta", abstract="A longer one"))
    theirs = _text(_rec(1, title="Alpha", abstract="A"))
    assert (
        merge.merge_records_text(base, ours, theirs)[0]
        == merge.merge_records_text(base, theirs, ours)[0]
    )


def test_the_file_driver_rewrites_ours_and_leaves_a_note(tmp_path: Path) -> None:
    base, ours, theirs = tmp_path / "base", tmp_path / "ours", tmp_path / "theirs"
    base.write_text(_text(_rec(1, title="Base")), encoding="utf-8")
    ours.write_text(_text(_rec(1, title="Beta")), encoding="utf-8")
    theirs.write_text(_text(_rec(1, title="Alpha")), encoding="utf-8")
    notes = tmp_path / ".strata" / "cache" / "merge-notes.ndjson"
    resolutions = merge.merge_records_files(base, ours, theirs, trust=[], notes=notes)
    assert json.loads(ours.read_text())["title"] == "Alpha" and len(resolutions) == 1
    assert merge.read_notes(notes)[0]["field"] == "title"
    assert merge.read_notes(tmp_path / "missing") == []


# --- event files ----------------------------------------------------------------------------


def test_a_well_ordered_linear_file_is_left_alone(tmp_path: Path) -> None:
    path = tmp_path / "e.ndjson"
    for i in range(3):
        append_new_event(
            path,
            ev="screen",
            actor="ethan",
            body={
                "stage": "title-abstract",
                "record": f"rec_{i:016d}",
                "decision": "include",
                "criteria": [],
                "criteria_version": 1,
            },
        )
    before = path.read_bytes()
    assert merge.normalise_event_file(path, relative="e.ndjson") is None
    assert path.read_bytes() == before


def test_a_union_merged_file_is_sorted_deduplicated_and_relinked(tmp_path: Path) -> None:
    left, right = tmp_path / "l.ndjson", tmp_path / "r.ndjson"
    for i in range(2):
        append_new_event(
            left,
            ev="screen",
            actor="ethan",
            body={
                "stage": "title-abstract",
                "record": f"rec_a{i:015d}",
                "decision": "include",
                "criteria": [],
                "criteria_version": 1,
            },
        )
    shared = read_events(left)[0]
    for i in range(2):
        append_new_event(
            right,
            ev="screen",
            actor="ethan",
            body={
                "stage": "title-abstract",
                "record": f"rec_b{i:015d}",
                "decision": "exclude",
                "criteria": ["EXC-01"],
                "criteria_version": 1,
            },
        )
    # What a union merge leaves: both sides' lines concatenated, the shared first line twice.
    merged = tmp_path / "merged.ndjson"
    merged.write_text(
        left.read_text() + right.read_text() + json.dumps(shared) + "\n", encoding="utf-8"
    )
    relink = merge.normalise_event_file(merged, relative="events/screen/x.ndjson")
    assert (
        relink is not None
        and relink.duplicates_dropped == 1
        and relink.file == "events/screen/x.ndjson"
    )
    events = read_events(merged)
    assert len(events) == 4 and [(e["ts"], e["id"]) for e in events] == sorted(
        (e["ts"], e["id"]) for e in events
    )
    assert [e["seq"] for e in events] == [1, 2, 3, 4]
    assert events[0].get("prev") is None and all(
        events[i]["prev"] == events[i - 1]["digest"] for i in range(1, 4)
    )
    assert verify_chain(merged) == []
    assert merge.normalise_event_file(merged, relative="x") is None  # idempotent
