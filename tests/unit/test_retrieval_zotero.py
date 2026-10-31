"""A document held in Zotero is recorded by its item key, alongside the DOI, and never by a local
path (openspec:zotero-integration#retrieval-through-zotero)."""

from __future__ import annotations

from pathlib import Path

import pytest

from strata.core import fulltext
from strata.protocol import retrieval
from tests.unit._m3 import add_records, decide, init_review, rpt

_ZOTERO = {"library": "users/12345", "item_key": "AB3D9XYZ"}


def _setup(tmp_path: Path):  # type: ignore[no-untyped-def]
    repo = init_review(tmp_path)
    ids = add_records(repo, 2)
    decide(repo, "title-abstract", ids)
    return repo


def test_the_manifest_entry_records_the_doi_and_the_zotero_item_key(tmp_path: Path) -> None:
    repo = _setup(tmp_path)

    retrieval.record_retrieval(
        repo,
        report=rpt(1),
        status="retrieved",
        actor="ethan",
        source="zotero",
        version="version-of-record",
        zotero=_ZOTERO,
        retrieved_on="2026-03-28",
    )

    [entry] = fulltext.read_manifest(repo)
    assert entry == {
        "report": rpt(1),
        "locator": {"doi": "10.1000/test.1"},
        "version": "version-of-record",
        "retrieved": "2026-03-28",
        "source": "zotero",
        "actor": "ethan",
        "zotero": _ZOTERO,
    }
    assert "path" not in entry


def test_a_zotero_item_and_a_local_path_are_not_recorded_together(tmp_path: Path) -> None:
    repo = _setup(tmp_path)

    with pytest.raises(retrieval.RetrievalError, match="instead of a local path"):
        retrieval.record_retrieval(
            repo,
            report=rpt(1),
            status="retrieved",
            actor="ethan",
            source="zotero",
            path="cepeda-2008.pdf",
            zotero=_ZOTERO,
        )

    assert fulltext.read_manifest(repo) == []


def test_a_zotero_item_only_goes_with_a_retrieved_outcome(tmp_path: Path) -> None:
    repo = _setup(tmp_path)

    with pytest.raises(retrieval.RetrievalError, match="retrieved"):
        retrieval.record_retrieval(
            repo,
            report=rpt(1),
            status="not-retrieved",
            actor="ethan",
            reason="no-access",
            zotero=_ZOTERO,
        )


def test_a_malformed_item_key_is_refused_before_anything_is_written(tmp_path: Path) -> None:
    repo = _setup(tmp_path)

    with pytest.raises(Exception, match="item_key"):
        retrieval.record_retrieval(
            repo,
            report=rpt(1),
            status="retrieved",
            actor="ethan",
            source="zotero",
            zotero={"library": "users/12345", "item_key": "not a key"},
        )

    assert fulltext.read_manifest(repo) == []
    assert list(repo.path("events", "retrieval").glob("*.ndjson")) == []
