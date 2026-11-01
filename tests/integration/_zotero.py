"""Builders for the Zotero integration tests: a review whose records match the fake library."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from strata.core.ids import canonical_key, record_id
from strata.core.repo import Repo
from strata.integrations.zotero.connect import Connection, connect
from strata.integrations.zotero.operations import Connector
from tests.unit._m3 import add_records, init_review
from tests.unit._zotero import MemoryKeystore, Sleeper
from tests.zotero_fake import API_KEY, FakeZotero

CEPEDA: dict[str, Any] = {
    "type": "article-journal",
    "title": "Spacing effects in learning: A temporal ridgeline of optimal retention",
    "author": [
        {"family": "Cepeda", "given": "Nicholas J."},
        {"family": "Vul", "given": "Edward"},
        {"family": "Rohrer", "given": "Doug"},
        {"family": "Wixted", "given": "John T."},
        {"family": "Pashler", "given": "Harold"},
    ],
    "container-title": "Psychological Science",
    "volume": "19",
    "issue": "11",
    "page": "1095-1102",
    "DOI": "10.1111/j.1467-9280.2008.02209.x",
    "issued": {"date-parts": [[2008, 11]]},
    "abstract": "Reviewers screen on this invented abstract about spacing practice.",
}
ROEDIGER: dict[str, Any] = {
    "type": "article-journal",
    "title": "Test-enhanced learning: Taking memory tests improves long-term retention",
    "author": [
        {"family": "Roediger", "given": "Henry L."},
        {"family": "Karpicke", "given": "Jeffrey D."},
    ],
    "container-title": "Psychological Science",
    "DOI": "10.1111/j.1467-9280.2006.01693.x",
    "issued": {"date-parts": [[2006, 3]]},
}
#: No DOI: identified by its title, year and first author.
SMITH: dict[str, Any] = {
    "type": "article-journal",
    "title": "Spacing effects in a classroom: a quasi-experiment",
    "author": [{"family": "Smith", "given": "Anna"}],
    "container-title": "Journal of Classroom Studies",
    "issued": {"date-parts": [[2010]]},
}
#: In the review but not in the Zotero library.
ONLY_HERE: dict[str, Any] = {
    "type": "article-journal",
    "title": "A trial only the review knows about",
    "author": [{"family": "Okonkwo", "given": "Ada"}],
    "container-title": "Journal of Trials",
    "DOI": "10.1000/only.here",
    "issued": {"date-parts": [[2015]]},
}


def make_record(csl: dict[str, Any]) -> dict[str, Any]:
    """A canonical record as an import would have made it from `csl`."""
    record = dict(csl)
    key, _ = canonical_key(record)
    record["id"] = record_id(key)
    record["strata"] = {
        "canonical_key": key,
        "canonical": True,
        "sources": [{"import": "imp_01arz3ndektsv4rrffq69g5fav", "database": "manual"}],
    }
    return record


def review_with(tmp_path: Path, *csls: dict[str, Any]) -> tuple[Repo, list[str]]:
    """A review (actors `ethan` and `sam`) with a record for each of `csls`; their ids, in order."""
    repo = init_review(tmp_path)
    if not csls:
        return repo, []
    return repo, add_records(repo, [make_record(c) for c in csls])


def connector_for(
    fake: FakeZotero,
    *,
    keychain: bool = True,
    key: str | None = API_KEY,
    environ: dict[str, str] | None = None,
) -> Connector:
    """A connector over the fake, with a key in the keychain unless told otherwise."""
    store = MemoryKeystore(available_=keychain, secret=key if keychain else None)

    def connector(preference: str, need_write: bool) -> Connection:
        return connect(
            preference,
            need_write=need_write,
            store=store,
            environ=environ if environ is not None else {},
            http=fake,
            sleep=Sleeper(),
        )

    return connector
