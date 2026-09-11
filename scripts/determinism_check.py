"""Emit a fixture exercising canonical serialisation and identity assignment.

Run twice under two different `PYTHONHASHSEED` values by the CI `determinism`
job (docs/spec/14-testing.md §9.3); the output MUST be byte-identical both
times (docs/spec/02-repository-format.md §5, property P4/P5).
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from strata.core.canon import canonical_json, serialise_envelope
from strata.core.events import build_envelope
from strata.core.ids import canonical_key, record_id

_SAMPLE_RECORDS = [
    {
        "title": "Über spacing effects in learning &amp; retention",
        "issued": {"date-parts": [[2008]]},
        "author": [{"family": "van Cepeda"}, {"family": "Pashler"}],
        "DOI": "https://doi.org/10.1111/j.1467-9280.2008.02209.x",
    },
    {
        "title": "A study of <i>retrieval</i> practice",
        "issued": {"date-parts": [[1990, 5]]},
        "author": [{"family": "Roediger"}],
        "PMID": "19076480",
    },
    {"title": "", "ISBN": "978-0-13-468599-1"},
]


def build_fixture() -> str:
    lines = []
    for record in _SAMPLE_RECORDS:
        key, deterministic = canonical_key(record)
        rid = record_id(key)
        lines.append(canonical_json({"record_id": rid, "key": key, "deterministic": deterministic}))

    envelope = build_envelope(
        ev="note",
        actor="ethan",
        seq=1,
        body={"subject": "determinism-fixture", "text": "fixed content, fixed clock"},
        ts="2026-01-01T00:00:00Z",
        event_id="ev_01arz3ndektsv4rrffq69g5fav",
    )
    lines.append(serialise_envelope(envelope))
    return "\n".join(lines) + "\n"


def main(out_path: Path) -> None:
    out_path.write_text(build_fixture(), encoding="utf-8")


if __name__ == "__main__":
    main(Path(sys.argv[1]))
