"""Compare what two surfaces left in git, with the parts that legitimately differ masked.

Used by the tests that hold the command line and the web interface to the same result
(openspec:architecture#mutating-operations-are-shared-services).

Those tests build two identical reviews one after the other and compare what each recorded, but
an import, a retrieval and a search stamp the day they happened on what they commit. A run that
crosses 00:00 UTC between the two builds (the slow legs of CI take over an hour) would then record
two different days and fail for no reason. `pin_day` (the `same_day` fixture) holds the day still
for the whole test, so the comparison is of the two surfaces and never of the clock. The day is
pinned rather than masked out of the comparison because a mask could hide a real difference.
"""

from __future__ import annotations

import json
import re
import sys
from collections.abc import Callable
from datetime import UTC, date, datetime, tzinfo
from pathlib import Path

import pytest

from strata import gitio

_IMPORT_ID = re.compile(r"imp_[0-9a-z]{26}")
_EVENT_ID = re.compile(r"ev_[0-9a-z]{26}")
_STUDY_ID = re.compile(r"std_[0-9a-z]{16}")
_TIMESTAMP = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z")
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}")
_TEMP_DIR = re.compile(r"/tmp/\S*?/(?=[^/\s]+\.(?:ris|json|csv|xlsx))")


PINNED_DAY = date(2026, 6, 15)

# Where production code stamps a day on what it commits: the module and the `datetime` name it
# reads the clock through (`date.today()`, or `datetime.now(UTC).date()` in retrieval). The
# clocks it does not read through here are on purpose: an event's `ts` and id are masked below and
# must keep moving to stay in order, and the year bounds in `core.ids` and `core.fieldedit` and the
# enrichment log in `ingest.enrich.unpaywall` are not in anything these tests compare
# (`tests/integration/test_equivalence_clock.py` fails when a new clock read is in neither list).
DAY_STAMPS: tuple[tuple[str, str], ...] = (
    ("strata.cli.main", "date"),
    ("strata.core.init", "date"),
    ("strata.ingest.pipeline", "date"),
    ("strata.integrations.zotero.operations", "date"),
    ("strata.protocol.retrieval", "datetime"),
    ("strata.web.search_routes", "date"),
)
OTHER_CLOCKS = (
    "strata.core.events",
    "strata.core.fieldedit",
    "strata.core.ids",
    "strata.ingest.enrich.unpaywall",
)

_pinned_day: date | None = None


def install_clock(monkeypatch: pytest.MonkeyPatch, utc_now: Callable[[], datetime]) -> None:
    """Make every module in `DAY_STAMPS` read the time from `utc_now()` (an aware UTC datetime).

    `pin_day` is this with a time that never changes; the tests of the pin use it with one that
    does, to stand in for the real clock.
    """

    class Date(date):
        @classmethod
        def today(cls) -> date:
            return utc_now().date()

    class Datetime(datetime):
        @classmethod
        def now(cls, tz: tzinfo | None = None) -> datetime:
            moment = utc_now()
            return moment.astimezone(tz) if tz else moment.replace(tzinfo=None)

    for module, name in DAY_STAMPS:
        monkeypatch.setattr(f"{module}.{name}", Date if name == "date" else Datetime)


def pin_day(monkeypatch: pytest.MonkeyPatch, day: date = PINNED_DAY) -> None:
    """Hold the day that imports, retrievals, searches and `init` stamp at `day`, for this test."""
    moment = datetime(day.year, day.month, day.day, 12, tzinfo=UTC)
    install_clock(monkeypatch, lambda: moment)
    monkeypatch.setattr(sys.modules[__name__], "_pinned_day", day)


def mask(text: str) -> str:
    """Generated ids, timestamps and the hash chain that covers them, and temp paths."""
    text = _IMPORT_ID.sub("<IMPORT>", text)
    text = _EVENT_ID.sub("<EVENT>", text)
    text = _STUDY_ID.sub("<STUDY>", text)
    text = _TIMESTAMP.sub("<TS>", text)
    return _TEMP_DIR.sub("", text)


def committed_snapshot(root: Path, revision: str = "HEAD") -> dict[str, str]:
    """What `revision` changed: its commit message, and every file it touched, masked.

    Event files are reduced to their type, actor and body, because everything else in an event is
    an id, a timestamp or a digest. Everything else (record ids, manifests, raw files, the PRISMA
    counts, the search files) is compared as written.

    Refuses to run unless the day is pinned (the `same_day` fixture): two snapshots are only
    comparable if no day passed between the reviews they come from.
    """
    if _pinned_day is None:
        raise RuntimeError(
            "committed_snapshot compares reviews built at different moments, so the day they "
            "stamp must be held still: use the `same_day` fixture "
            "(pytestmark = pytest.mark.usefixtures('same_day'))"
        )
    names = gitio.run(["show", "--name-only", "--format=", revision], cwd=root).stdout
    message = gitio.run(["log", "-1", "--format=%B", revision], cwd=root).stdout
    snapshot = {"<message>": mask(message)}
    for name in sorted(n for n in names.splitlines() if n):
        content = gitio.run(["show", f"{revision}:{name}"], cwd=root).stdout
        if name.startswith("events/"):
            content = "\n".join(
                json.dumps(
                    {k: json.loads(line)[k] for k in ("ev", "actor", "body")}, sort_keys=True
                )
                for line in content.splitlines()
            )
        snapshot[mask(name)] = mask(content)
    return snapshot
