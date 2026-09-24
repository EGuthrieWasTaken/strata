import json
from pathlib import Path

import pytest

from strata.core.events import (
    ChainError,
    append_event,
    append_new_event,
    append_new_events,
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


def test_append_new_events_matches_calling_append_new_event_per_entry(tmp_path: Path) -> None:
    """`append_new_events` must be semantically identical to a loop of
    `append_new_event` calls, just without the O(n) re-read per call."""
    sequential_path = tmp_path / "sequential.ndjson"
    batched_path = tmp_path / "batched.ndjson"
    entries = [("note", "ethan", {"subject": "a", "text": str(i)}) for i in range(5)]

    for ev, actor, body in entries:
        append_new_event(sequential_path, ev=ev, actor=actor, body=body)
    append_new_events(batched_path, entries)

    sequential_events = read_events(sequential_path)
    batched_events = read_events(batched_path)
    assert len(batched_events) == 5
    assert verify_chain(batched_path) == []  # internally self-consistent

    previous_digest = None
    for seq_event, batch_event in zip(sequential_events, batched_events, strict=True):
        # `id` (and so `digest`, which is computed over it) is a freshly
        # generated ULID each call, so it necessarily differs between the
        # two independent runs -- what must match is the seq numbering, the
        # body content, and that each entry's `prev` correctly chains to the
        # *previous batched entry's own* digest (not the sequential run's).
        assert seq_event["seq"] == batch_event["seq"]
        assert seq_event["body"] == batch_event["body"]
        assert batch_event.get("prev") == previous_digest
        previous_digest = batch_event["digest"]


def test_append_new_events_continues_seq_and_prev_from_existing_file(tmp_path: Path) -> None:
    path = tmp_path / "events.ndjson"
    first = append_new_event(path, ev="note", actor="ethan", body={"subject": "a", "text": "1"})
    envelopes = append_new_events(
        path,
        [
            ("note", "ethan", {"subject": "b", "text": "2"}),
            ("note", "ethan", {"subject": "c", "text": "3"}),
        ],
    )
    assert envelopes[0]["seq"] == first["seq"] + 1
    assert envelopes[0]["prev"] == first["digest"]
    assert envelopes[1]["seq"] == first["seq"] + 2
    assert envelopes[1]["prev"] == envelopes[0]["digest"]
    assert len(read_events(path)) == 3


def test_append_new_events_empty_list_is_a_no_op(tmp_path: Path) -> None:
    path = tmp_path / "events.ndjson"
    assert append_new_events(path, []) == []
    assert not path.exists()


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
