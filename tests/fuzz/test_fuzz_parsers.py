"""Fuzz testing for strata.ingest.parsers: docs/spec/14-testing.md §6.

Wired into the nightly `fuzz` job (`.github/workflows/nightly.yml`, which
already runs `pytest tests/fuzz -q` if this directory exists) -- not the
pull-request gate: mutation fuzzing explores a large input space and is
allowed to take longer than a per-commit budget affords.

Uses `hypothesis`-driven mutation, not `atheris` (§6 names either):
`atheris` needs a native libFuzzer-linked CPython build, which is fragile to
install portably across the three-OS CI matrix this project targets (Linux/
macOS/Windows); `hypothesis` is already a project dependency, and its
`st.binary()`/composite strategies cover the same ground -- bit flips,
truncation, insertion -- against the same seed corpus, without a new,
platform-sensitive dependency.

Every parser's actual contract (docs/spec/05-workflow-import.md §2.1): a row
that fails to parse becomes a `RejectedRow` inside the returned
`ParseResult`, never a raised exception -- "reports a `ParseError`" in §6's
more abstract wording. So the only thing this suite asserts is that
`parse()` returns at all, for any input, without raising, hanging, or (so
far as a Python-level test can observe) executing anything. It deliberately
does not check *which* rows got rejected -- that is the golden-fixture
suite's job (`tests/golden/`).
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from strata.ingest.parsers import (
    ParseResult,
    bibtex,
    csl_json,
    csv_tsv,
    decode_bytes,
    medline,
    normalise_newlines,
    ris,
)

_FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "exports"
_MAX_MUTATIONS = 8
_SETTINGS = settings(
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.data_too_large],
    deadline=None,
    max_examples=200,
)


def _seed_corpus(directory: Path) -> list[bytes]:
    """Every fixture file's raw bytes under `directory`, or `[b""]` if none exist
    yet (so a strategy can still be built without crashing test collection)."""
    if not directory.exists():
        return [b""]
    seeds = [p.read_bytes() for p in sorted(directory.iterdir()) if p.is_file()]
    return seeds or [b""]


@st.composite
def _mutated_bytes(draw: st.DrawFn, seeds: list[bytes]) -> bytes:
    """One seed fixture with 0-8 local byte mutations applied: a flip,
    insertion, deletion, or truncation at a random position -- "mutating
    bytes/encoding/structure" per §6, anchored to real export bytes rather
    than fully unstructured noise."""
    buffer = bytearray(draw(st.sampled_from(seeds)))
    for _ in range(draw(st.integers(min_value=0, max_value=_MAX_MUTATIONS))):
        if not buffer:
            buffer.extend(draw(st.binary(min_size=1, max_size=20)))
            continue
        pos = draw(st.integers(min_value=0, max_value=len(buffer) - 1))
        kind = draw(st.sampled_from(["flip", "insert", "delete", "truncate"]))
        if kind == "flip":
            buffer[pos] = draw(st.integers(min_value=0, max_value=255))
        elif kind == "insert":
            buffer.insert(pos, draw(st.integers(min_value=0, max_value=255)))
        elif kind == "delete":
            del buffer[pos]
        else:  # truncate
            del buffer[pos:]
    return bytes(buffer)


def _assert_survives(parse_fn: Callable[[str], ParseResult], raw: bytes) -> None:
    text, _encoding = decode_bytes(raw)
    text = normalise_newlines(text)
    result = parse_fn(text)
    assert isinstance(result, ParseResult)


@_SETTINGS
@given(_mutated_bytes(_seed_corpus(_FIXTURES_DIR / "csl-json")))
def test_fuzz_csl_json_never_raises(raw: bytes) -> None:
    _assert_survives(csl_json.parse, raw)


@_SETTINGS
@given(_mutated_bytes(_seed_corpus(_FIXTURES_DIR / "ris")))
def test_fuzz_ris_never_raises(raw: bytes) -> None:
    _assert_survives(ris.parse, raw)


@_SETTINGS
@given(_mutated_bytes(_seed_corpus(_FIXTURES_DIR / "bibtex")))
def test_fuzz_bibtex_never_raises(raw: bytes) -> None:
    _assert_survives(bibtex.parse, raw)


@_SETTINGS
@given(_mutated_bytes(_seed_corpus(_FIXTURES_DIR / "medline")))
def test_fuzz_medline_never_raises(raw: bytes) -> None:
    _assert_survives(medline.parse, raw)


@_SETTINGS
@given(_mutated_bytes(_seed_corpus(_FIXTURES_DIR / "csv")))
def test_fuzz_csv_never_raises(raw: bytes) -> None:
    text, _encoding = decode_bytes(raw)
    text = normalise_newlines(text)
    header = csv_tsv.read_header(text, delimiter=",")
    mapping = {"title": header[0]} if header else {"title": "Title"}
    try:
        result = csv_tsv.parse(text, delimiter=",", mapping=mapping)
    except csv_tsv.ColumnMappingError:
        return  # a controlled, documented rejection of the mapping itself
    assert isinstance(result, ParseResult)
