"""Property test for canonical serialisation, per openspec:test-suite#property-invariants.

P3: `parse(canon(x)) == x` for every schema. `canonical_json` is a
hand-written recursive serialiser (openspec:canonical-serialisation), not
a thin wrapper over `json.dumps`, so this genuinely exercises its own
recursion and per-type formatting rather than restating a stdlib guarantee.
"""

from __future__ import annotations

import json
import random

import pytest
from hypothesis import assume, given
from hypothesis import strategies as st

from strata.core.canon import canonical_json

# Only values `canonical_json` actually accepts (openspec:canonical-serialisation#ndjson-rules: no
# NaN/
# Infinity) and only `list`/`dict` containers -- a `tuple` would round-trip
# through JSON as a `list`, which is a real, known asymmetry of JSON itself,
# not something P3 is about.
_json_scalars = st.one_of(
    st.none(),
    st.booleans(),
    st.integers(min_value=-(10**15), max_value=10**15),
    st.floats(allow_nan=False, allow_infinity=False, width=64),
    st.text(max_size=30),
)


@st.composite
def json_values(draw: st.DrawFn, depth: int = 0) -> object:
    if depth >= 3:
        return draw(_json_scalars)
    return draw(
        st.one_of(
            _json_scalars,
            st.lists(json_values(depth=depth + 1), max_size=5),
            st.dictionaries(
                st.text(min_size=1, max_size=10), json_values(depth=depth + 1), max_size=5
            ),
        )
    )


@pytest.mark.req("P3")
@given(json_values())
def test_p3_serialisation_round_trip(value: object) -> None:
    assert json.loads(canonical_json(value)) == value


@pytest.mark.req("P3")
@given(
    st.fixed_dictionaries(
        {
            "id": st.text(
                alphabet=st.characters(min_codepoint=97, max_codepoint=122), min_size=1, max_size=20
            ),
            "type": st.just("article-journal"),
            "title": st.text(max_size=50),
            "strata": st.fixed_dictionaries(
                {
                    "canonical_key": st.text(min_size=1, max_size=30),
                    "canonical": st.booleans(),
                    "sources": st.lists(
                        st.fixed_dictionaries({"import": st.text(min_size=1, max_size=20)}),
                        max_size=3,
                    ),
                }
            ),
        }
    )
)
def test_p3_serialisation_round_trip_record_shaped(record: dict[str, object]) -> None:
    """The same property, over a record-schema-shaped document specifically --
    P3's "for every schema" wording (openspec:test-suite#property-invariants), not just arbitrary
    JSON."""
    assert json.loads(canonical_json(record)) == record


# --- AI participation: the optional `agent` envelope key joins P3 and P4 ---------------------

from strata.core.canon import ENVELOPE_KEY_ORDER, serialise_envelope  # noqa: E402
from strata.core.events import compute_digest  # noqa: E402

_handles = st.from_regex(r"[a-z0-9][a-z0-9-]{0,31}", fullmatch=True)
_agent_keys = st.fixed_dictionaries(
    {"model": st.text(min_size=1, max_size=40), "invoked_by": _handles},
    optional={
        "client": st.fixed_dictionaries(
            {}, optional={"name": st.text(min_size=1, max_size=20), "version": st.text(min_size=1)}
        )
    },
)


@st.composite
def envelopes(draw: st.DrawFn, *, agent: bool | None = None) -> dict[str, object]:
    """An event envelope, with the `agent` key present, absent, or either (`agent=None`)."""
    envelope: dict[str, object] = {
        "ev": draw(st.sampled_from(["screen", "note", "retrieval", "suggestion"])),
        "id": "ev_"
        + draw(st.text(alphabet="0123456789abcdefghjkmnpqrstvwxyz", min_size=26, max_size=26)),
        "ts": "2026-01-01T00:00:00Z",
        "actor": draw(_handles),
        "seq": draw(st.integers(min_value=1, max_value=10**6)),
        "body": draw(
            st.dictionaries(st.text(min_size=1, max_size=8), json_values(depth=2), max_size=4)
        ),
        "tool": "strata/0.1.0",
    }
    if draw(st.booleans() if agent is None else st.just(agent)):
        envelope["agent"] = draw(_agent_keys)
    if draw(st.booleans()):
        envelope["prev"] = "sha256:" + "0" * 64
    return envelope


@pytest.mark.req("P3")
@given(envelopes())
def test_p3_an_envelope_round_trips_with_or_without_an_agent_key(
    envelope: dict[str, object],
) -> None:
    assert json.loads(serialise_envelope(envelope)) == envelope


@pytest.mark.req("P4")
@given(envelopes(), st.randoms())
def test_p4_an_envelope_serialises_the_same_whatever_order_it_was_built_in(
    envelope: dict[str, object], rng: random.Random
) -> None:
    items = list(envelope.items())
    rng.shuffle(items)
    assert serialise_envelope(dict(items)) == serialise_envelope(envelope)
    assert compute_digest(dict(items)) == compute_digest(envelope)


@pytest.mark.req("P4")
@given(envelopes(agent=True))
def test_p4_the_agent_key_sits_between_actor_and_seq_and_nowhere_else(
    envelope: dict[str, object],
) -> None:
    keys = list(json.loads(serialise_envelope(envelope)))
    assert keys.index("agent") == keys.index("actor") + 1 == keys.index("seq") - 1
    assert keys == [k for k in ENVELOPE_KEY_ORDER if k in envelope]


@pytest.mark.req("P4")
@given(envelopes(agent=True), st.text(min_size=1, max_size=40))
def test_p4_the_digest_covers_the_agent_key(envelope: dict[str, object], model: str) -> None:
    agent = envelope["agent"]
    assert isinstance(agent, dict)
    assume(model != agent["model"])
    changed = {**envelope, "agent": {**agent, "model": model}}
    assert compute_digest(changed) != compute_digest(envelope)
    stripped = {k: v for k, v in envelope.items() if k != "agent"}
    assert compute_digest(stripped) != compute_digest(envelope)


@pytest.mark.req("P4")
@given(envelopes(agent=False))
def test_p4_an_envelope_without_the_key_serialises_as_it_did_before_the_key_existed(
    envelope: dict[str, object],
) -> None:
    """The old order, written out here rather than imported, so changing the module cannot change
    what this checks."""
    before = ("ev", "id", "ts", "actor", "seq", "body", "tool", "prev", "digest")
    from strata.core.canon import canonical_json

    expected = (
        "{"
        + ",".join(
            f"{json.dumps(k)}:{canonical_json(envelope[k])}" for k in before if k in envelope
        )
        + "}"
    )
    assert serialise_envelope(envelope) == expected
