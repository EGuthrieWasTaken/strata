"""The `agent` envelope key: openspec:event-log#event-envelope.

The golden lines are written out by hand, and the digests of the agent lines are computed here with
`hashlib` over the bytes the specification says, so the tests do not merely restate what the code
emits. The person's line was produced by the serialiser as it stood before the key existed, so it
pins "an event without it MUST serialise exactly as it did before".
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from strata.core import merge
from strata.core.canon import serialise_envelope
from strata.core.events import (
    AgentScopeError,
    agent_scope,
    append_event,
    append_new_event,
    append_new_events,
    build_envelope,
    compute_digest,
    current_agent_actor,
    read_events,
    verify_chain,
)

_PREV = "sha256:" + "0" * 64
_ID = "ev_01m62y4n2etk2j22640hhrn4z8"

#: A person's screening decision exactly as every earlier version of strata wrote it.
PERSON_LINE = (
    '{"ev":"screen","id":"ev_01m62y4n2etk2j22640hhrn4z8","ts":"2026-11-02T09:14:07Z",'
    '"actor":"ada","seq":41,"body":{"decision":"include","record":"rec_0000000000000042",'
    '"stage":"title-abstract"},"tool":"strata/0.1.0",'
    '"prev":"sha256:0000000000000000000000000000000000000000000000000000000000000000",'
    '"digest":"sha256:344ed9a8ec4600f5e60d8963f374f16156ff99905aa600af0a06801054a9bcdc"}'
)

#: The same decision made by an agent for `ada`: `agent` sits between `actor` and `seq`, and its
#: own keys are sorted like every object in a canonical line.
AGENT_BODY = (
    '{"ev":"screen","id":"ev_01m62y4n2etk2j22640hhrn4z8","ts":"2026-11-02T09:14:07Z",'
    '"actor":"claude-opus","agent":{"client":{"name":"claude-code","version":"2.1.3"},'
    '"invoked_by":"ada","model":"claude-opus-5-5"},"seq":41,'
    '"body":{"decision":"include","record":"rec_0000000000000042","stage":"title-abstract"},'
    '"tool":"strata/0.1.0",'
    '"prev":"sha256:0000000000000000000000000000000000000000000000000000000000000000"'
)
AGENT_DIGEST = "sha256:" + hashlib.sha256((AGENT_BODY + "}").encode("utf-8")).hexdigest()
AGENT_LINE = AGENT_BODY + f',"digest":"{AGENT_DIGEST}"' + "}"

AGENT_KEY = {
    "model": "claude-opus-5-5",
    "client": {"name": "claude-code", "version": "2.1.3"},
    "invoked_by": "ada",
}
BODY = {"stage": "title-abstract", "record": "rec_0000000000000042", "decision": "include"}


def _envelope(actor: str, **extra: Any) -> dict[str, Any]:
    return build_envelope(
        ev="screen",
        actor=actor,
        seq=41,
        body=BODY,
        prev=_PREV,
        ts="2026-11-02T09:14:07Z",
        event_id=_ID,
        **extra,
    )


# ------------------------------------------------------------------------------ golden lines


def test_golden_a_persons_event_is_byte_identical_to_what_earlier_versions_wrote() -> None:
    assert serialise_envelope(_envelope("ada")) == PERSON_LINE


def test_golden_an_agent_event_carries_the_key_between_actor_and_seq() -> None:
    envelope = _envelope("claude-opus", agent=AGENT_KEY)
    assert serialise_envelope(envelope) == AGENT_LINE
    assert envelope["digest"] == AGENT_DIGEST
    assert list(json.loads(AGENT_LINE)) == [
        "ev", "id", "ts", "actor", "agent", "seq", "body", "tool", "prev", "digest",
    ]  # fmt: skip


def test_the_digest_covers_the_agent_value() -> None:
    base = _envelope("claude-opus", agent=AGENT_KEY)
    for changed in (
        {**AGENT_KEY, "model": "claude-opus-5-6"},
        {**AGENT_KEY, "invoked_by": "sam"},
        {**AGENT_KEY, "client": {"name": "claude-code", "version": "2.1.4"}},
    ):
        assert _envelope("claude-opus", agent=changed)["digest"] != base["digest"]
    assert _envelope("claude-opus")["digest"] != base["digest"]  # nor can the key be dropped
    assert compute_digest({k: v for k, v in base.items() if k != "digest"}) == base["digest"]


def test_an_agent_event_and_a_persons_event_differ_only_by_the_key() -> None:
    person = json.loads(PERSON_LINE)
    agent = json.loads(AGENT_LINE)
    assert {k: v for k, v in agent.items() if k not in ("agent", "actor", "digest")} == {
        k: v for k, v in person.items() if k not in ("actor", "digest")
    }


# --------------------------------------------------------------------------------- the scope


def test_inside_an_agent_scope_every_event_carries_the_key(tmp_path: Path) -> None:
    path = tmp_path / "events.ndjson"
    with agent_scope("claude-opus", AGENT_KEY):
        assert current_agent_actor() == "claude-opus"
        first = append_new_event(path, ev="note", actor="claude-opus", body={"subject": "a"})
        batch = append_new_events(
            path,
            [("note", "claude-opus", {"subject": "b"}), ("note", "claude-opus", {"subject": "c"})],
        )
    assert current_agent_actor() is None
    assert first["agent"] == AGENT_KEY
    assert all(e["agent"] == AGENT_KEY for e in batch)
    assert [e["agent"] for e in read_events(path)] == [AGENT_KEY] * 3
    assert verify_chain(path) == []


def test_outside_a_scope_an_event_is_a_persons(tmp_path: Path) -> None:
    path = tmp_path / "events.ndjson"
    with agent_scope("claude-opus", AGENT_KEY):
        pass
    event = append_new_event(path, ev="note", actor="ada", body={"subject": "a"})
    assert "agent" not in event


def test_a_scope_ends_even_when_the_write_fails() -> None:
    with pytest.raises(RuntimeError), agent_scope("claude-opus", AGENT_KEY):
        raise RuntimeError("the write failed")
    assert current_agent_actor() is None


def test_an_agents_write_cannot_record_an_event_under_a_persons_handle(tmp_path: Path) -> None:
    """The point of a scope: an agent's events are its own, never a person's."""
    path = tmp_path / "events.ndjson"
    with agent_scope("claude-opus", AGENT_KEY), pytest.raises(AgentScopeError, match="'ada'"):
        append_new_event(path, ev="note", actor="ada", body={"subject": "a"})
    assert not path.exists()  # nothing was written


def test_scopes_nest_and_restore(tmp_path: Path) -> None:
    other = {**AGENT_KEY, "invoked_by": "sam"}
    with agent_scope("claude-opus", AGENT_KEY):
        with agent_scope("opus-two", other):
            assert current_agent_actor() == "opus-two"
        assert current_agent_actor() == "claude-opus"


def test_an_explicit_key_wins_over_the_scope(tmp_path: Path) -> None:
    explicit = {**AGENT_KEY, "invoked_by": "sam"}
    with agent_scope("claude-opus", AGENT_KEY):
        envelope = build_envelope(
            ev="note", actor="claude-opus", seq=1, body={"subject": "a"}, agent=explicit
        )
    assert envelope["agent"] == explicit


def test_the_key_is_copied_so_the_caller_cannot_change_a_written_event() -> None:
    key = dict(AGENT_KEY)
    envelope = build_envelope(ev="note", actor="claude-opus", seq=1, body={}, agent=key)
    key["model"] = "other"
    assert envelope["agent"]["model"] == "claude-opus-5-5"


# ------------------------------------------------------------------ relinking merged files


def test_relinking_a_merged_agent_file_keeps_every_key(tmp_path: Path) -> None:
    """`strata sync` re-links a file where two machines appended; the agent key must survive."""
    path = tmp_path / "events" / "note" / "claude-opus.ndjson"
    with agent_scope("claude-opus", AGENT_KEY):
        append_new_event(path, ev="note", actor="claude-opus", body={"subject": "a"})
        late = build_envelope(
            ev="note", actor="claude-opus", seq=1, body={"subject": "b"}, ts="2020-01-01T00:00:00Z"
        )
        append_event(path, late)  # a second chain that arrived through a merge, earlier in time
    relink = merge.normalise_event_file(path, relative="events/note/claude-opus.ndjson")
    assert relink is not None
    events = read_events(path)
    assert [e["body"]["subject"] for e in events] == ["b", "a"]
    assert all(e["agent"] == AGENT_KEY for e in events)
    assert verify_chain(path) == []
