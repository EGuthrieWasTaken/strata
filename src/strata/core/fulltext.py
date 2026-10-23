"""`fulltext/manifest.ndjson`: which document was assessed, identified by identifier and version.

Implements openspec:full-text-retrieval#full-text-manifest-by-identifier and
openspec:full-text-retrieval#documents-are-never-identified-by-content-hash. The manifest is
committed; the files it points at are not
(openspec:domain-model#full-text-files-are-never-committed).

A document is identified by its `locator` (a DOI, or a PMID/PMCID/arXiv id/ISBN/URL where no DOI
exists) and its `version`. `path` is a local convenience with no guarantee, and `sha256`, when
present, is advisory metadata that nothing here compares, warns about, or uses to decide whether
two reviewers saw the same document.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from strata.core.canon import canonical_json
from strata.core.ids import normalise_doi
from strata.core.repo import Repo
from strata.core.validate import validate

MANIFEST_PATH = ("fulltext", "manifest.ndjson")

VERSIONS = (
    "preprint",
    "accepted-manuscript",
    "version-of-record",
    "corrected",
    "retracted",
    "unknown",
)

# Locator keys in order of preference when one identifier has to stand for the document.
_LOCATOR_PREFERENCE = ("doi", "pmid", "pmcid", "arxiv", "isbn", "url")


def manifest_path(repo: Repo) -> Path:
    return repo.path(*MANIFEST_PATH)


def locator_key(locator: dict[str, str]) -> str:
    """The single identifier that stands for a locator: `doi:10.1/x`, `pmid:123`, ..."""
    for kind in _LOCATOR_PREFERENCE:
        value = locator.get(kind)
        if value:
            return f"{kind}:{value}"
    raise ValueError("a locator needs at least one of " + ", ".join(_LOCATOR_PREFERENCE))


def locator_from_record(record: dict[str, Any]) -> dict[str, str]:
    """Best locator a bibliographic record offers, DOI first (the DOI is normalised).

    Returns an empty dict when the record carries no usable identifier at all.
    """
    locator: dict[str, str] = {}
    doi = normalise_doi(record.get("DOI"))
    if doi:
        locator["doi"] = doi
    for field, key in (("PMID", "pmid"), ("PMCID", "pmcid"), ("ISBN", "isbn"), ("URL", "url")):
        value = record.get(field)
        if value:
            locator[key] = str(value)
    return locator


def read_manifest(repo: Repo) -> list[dict[str, Any]]:
    """Every manifest entry, in file order. A missing file is an empty manifest."""
    path = manifest_path(repo)
    if not path.exists():
        return []
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


def append_manifest_entry(repo: Repo, entry: dict[str, Any]) -> dict[str, Any]:
    """Validate and append one entry. The manifest is append-only: a later entry for the same
    report supersedes an earlier one in `latest_by_report`, and nothing is ever rewritten."""
    validate("fulltext-entry", entry)
    path = manifest_path(repo)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8", newline="\n") as handle:
        handle.write(canonical_json(entry) + "\n")
    return entry


def latest_by_report(entries: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """The most recent entry per report (file order is chronological: the file is append-only)."""
    return {entry["report"]: entry for entry in entries}
