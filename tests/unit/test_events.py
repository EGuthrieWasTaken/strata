import json
from pathlib import Path

import pytest

from strata.core.events import (
    ChainError,
    append_event,
    append_new_event,
    build_envelope,
    compute_digest,
    iter_event_files,
    last_digest,
    next_seq,
    read_events,
    verify_chain,
)


def test_build_envelope_computes_digest_over_preceding_fields() -> None:
    envelope = build_envelope(ev="note", actor="ethan", seq=1, body={"subject": "x", "text": "y"})
    without_digest = {k: v for k, v in envelope.items() if k != "digest"}
    assert envelope["digest"] == compute_digest(without_digest)


def test_append_and_read_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "events.ndjson"
    e1 = append_new_event(path, ev="note", actor="ethan", body={"subject": "a", "text": "1"})
    e2 = append_new_event(path, ev="note", actor="ethan", body={"subject": "b", "text": "2"})
    events = read_events(path)
    assert [e["id"] for e in events] == [e1["id"], e2["id"]]
    assert e2["prev"] == e1["digest"]
    assert e2["seq"] == e1["seq"] + 1


def test_verify_chain_detects_digest_tamper(tmp_path: Path) -> None:
    path = tmp_path / "events.ndjson"
    append_new_event(path, ev="note", actor="ethan", body={"subject": "a", "text": "1"})
    text = path.read_text(encoding="utf-8")
    tampered = text.replace('"text":"1"', '"text":"TAMPERED"')
    path.write_text(tampered, encoding="utf-8")
    violations = verify_chain(path)
    assert len(violations) == 1
    assert violations[0].reason == "digest mismatch"


def test_verify_chain_detects_broken_prev(tmp_path: Path) -> None:
    path = tmp_path / "events.ndjson"
    envelope1 = build_envelope(ev="note", actor="ethan", seq=1, body={"subject": "a", "text": "1"})
    append_event(path, envelope1)
    bogus_prev_envelope = build_envelope(
        ev="note",
        actor="ethan",
        seq=2,
        body={"subject": "b", "text": "2"},
        prev="sha256:" + "0" * 64,
    )
    append_event(path, bogus_prev_envelope)
    violations = verify_chain(path)
    assert any("does not match any earlier digest" in v.reason for v in violations)


def test_verify_chain_allows_restart_matching_earlier_digest(tmp_path: Path) -> None:
    """A union merge of two divergent same-actor tails: docs/spec 02 §4.2's caveat.

    `e2b` restarts from `e1`'s digest rather than the immediately preceding
    line (`e2a`'s), which is exactly the case the union-merge caveat exists
    to permit.
    """
    path = tmp_path / "events.ndjson"
    e1 = build_envelope(ev="note", actor="ethan", seq=1, body={"subject": "a", "text": "1"})
    e2a = build_envelope(
        ev="note", actor="ethan", seq=2, body={"subject": "a", "text": "2a"}, prev=e1["digest"]
    )
    e2b = build_envelope(
        ev="note", actor="ethan", seq=2, body={"subject": "a", "text": "2b"}, prev=e1["digest"]
    )
    for envelope in (e1, e2a, e2b):
        append_event(path, envelope)
    violations = verify_chain(path)
    assert violations == []


def test_read_events_skips_truncated_trailing_line(tmp_path: Path) -> None:
    path = tmp_path / "events.ndjson"
    append_new_event(path, ev="note", actor="ethan", body={"subject": "a", "text": "1"})
    with open(path, "a", encoding="utf-8") as f:
        f.write('{"ev":"note","id":"ev_broken", "trunc')  # no trailing newline, invalid JSON
    events = read_events(path)
    assert len(events) == 1


def test_next_seq_and_last_digest_on_empty_file(tmp_path: Path) -> None:
    path = tmp_path / "events.ndjson"
    assert next_seq(path) == 1
    assert last_digest(path) is None


def test_read_events_skips_blank_lines(tmp_path: Path) -> None:
    path = tmp_path / "events.ndjson"
    envelope = build_envelope(ev="note", actor="ethan", seq=1, body={"subject": "a", "text": "1"})
    path.write_text(json.dumps(envelope) + "\n\n", encoding="utf-8")
    events = read_events(path)
    assert len(events) == 1


def test_read_events_raises_on_malformed_non_trailing_line(tmp_path: Path) -> None:
    path = tmp_path / "events.ndjson"
    envelope = build_envelope(ev="note", actor="ethan", seq=1, body={"subject": "a", "text": "1"})
    path.write_text('{"broken": \n' + json.dumps(envelope) + "\n", encoding="utf-8")
    with pytest.raises(ChainError, match="not the last line"):
        read_events(path)


def test_verify_chain_skips_seen_digests_update_when_digest_missing(tmp_path: Path) -> None:
    path = tmp_path / "events.ndjson"
    envelope = build_envelope(ev="note", actor="ethan", seq=1, body={"subject": "a", "text": "1"})
    del envelope["digest"]
    path.write_text(json.dumps(envelope) + "\n", encoding="utf-8")
    violations = verify_chain(path)
    assert any(v.reason == "digest mismatch" for v in violations)


def test_iter_event_files_empty_when_no_events_dir(tmp_path: Path) -> None:
    assert iter_event_files(tmp_path) == []


def test_iter_event_files_finds_ndjson_files(tmp_path: Path) -> None:
    path = tmp_path / "events" / "screen" / "title-abstract.ethan.ndjson"
    append_new_event(path, ev="note", actor="ethan", body={"subject": "a", "text": "1"})
    files = iter_event_files(tmp_path)
    assert files == [path]
