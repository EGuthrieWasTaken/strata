"""Detection profiles for common platform CSV exports.

Implements docs/spec/05-workflow-import.md §2.2: match a CSV export to a
known platform by its header row, so importing a Scopus or Web of Science
export doesn't require `--map` every time.

Each profile's `signature` is a small set of column names distinctive enough,
in combination, to identify the platform reliably -- not every column the
platform ever emits, since export customisation and version drift make a
full-header match too brittle.

These column names are compiled from each platform's public export
documentation and community references (e.g. published systematic-review
tooling that consumes the same exports), **not verified against a live
export file from every platform listed**. Per the `parser.yml` issue
template (docs/spec/14-testing.md §9.2), a real export that doesn't match one
of these signatures is the bug to report, and the fix is almost always
widening or correcting a signature or mapping here -- never a reason to
distrust `--map`, which always works regardless of whether a profile matches.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Profile:
    name: str
    signature: frozenset[str]
    mapping: dict[str, str]


SCOPUS = Profile(
    name="scopus",
    signature=frozenset({"Authors", "Title", "Year", "Source title", "EID"}),
    mapping={
        "title": "Title",
        "author": "Authors",
        "year": "Year",
        "container-title": "Source title",
        "volume": "Volume",
        "issue": "Issue",
        "page-start": "Page start",
        "page-end": "Page end",
        "DOI": "DOI",
        "PMID": "PubMed ID",
        "ISBN": "ISBN",
        "URL": "Link",
        "abstract": "Abstract",
        "keyword": "Author Keywords",
    },
)

WEB_OF_SCIENCE = Profile(
    name="web-of-science",
    signature=frozenset(
        {"Authors", "Article Title", "Source Title", "Publication Year", "UT (Unique WOS ID)"}
    ),
    mapping={
        "title": "Article Title",
        "author": "Authors",
        "year": "Publication Year",
        "container-title": "Source Title",
        "volume": "Volume",
        "issue": "Issue",
        "page-start": "Start Page",
        "page-end": "End Page",
        "DOI": "DOI",
        "PMID": "PubMed ID",
        "ISBN": "ISBN",
        "abstract": "Abstract",
        "keyword": "Author Keywords",
    },
)

EBSCOHOST = Profile(
    name="ebscohost",
    signature=frozenset({"Authors", "Title", "Journal Name", "Accession Number"}),
    mapping={
        "title": "Title",
        "author": "Authors",
        "year": "Publication Date",
        "container-title": "Journal Name",
        "volume": "Volume",
        "issue": "Issue",
        "page-start": "Start Page",
        "DOI": "DOI",
        "ISBN": "ISSN",
        "abstract": "Abstract",
        "keyword": "Subjects",
    },
)

PROQUEST = Profile(
    name="proquest",
    signature=frozenset({"Title", "Author", "Publication title", "ProQuest document ID"}),
    mapping={
        "title": "Title",
        "author": "Author",
        "year": "Publication year",
        "container-title": "Publication title",
        "volume": "Volume",
        "issue": "Issue",
        "page": "Pages",
        "DOI": "DOI",
        "ISBN": "ISSN",
        "abstract": "Abstract",
        "keyword": "Subject",
    },
)

DIMENSIONS = Profile(
    name="dimensions",
    signature=frozenset({"Title", "Authors", "Source title", "PubYear"}),
    mapping={
        "title": "Title",
        "author": "Authors",
        "year": "PubYear",
        "container-title": "Source title",
        "volume": "Volume",
        "issue": "Issue",
        "page": "Pagination",
        "DOI": "DOI",
        "PMID": "PMID",
        "abstract": "Abstract",
        "keyword": "MeSH terms",
    },
)

GOOGLE_SCHOLAR_POP = Profile(
    name="google-scholar-publish-or-perish",
    signature=frozenset({"Authors", "Title", "Year", "Source", "GSRank"}),
    mapping={
        "title": "Title",
        "author": "Authors",
        "year": "Year",
        "container-title": "Source",
        "volume": "Volume",
        "issue": "Issue",
        "page-start": "StartPage",
        "page-end": "EndPage",
        "DOI": "DOI",
        "ISBN": "ISSN",
        "abstract": "Abstract",
    },
)

PROFILES = (SCOPUS, WEB_OF_SCIENCE, EBSCOHOST, PROQUEST, DIMENSIONS, GOOGLE_SCHOLAR_POP)


def detect_profile(header: list[str]) -> Profile | None:
    """The first profile whose signature is a subset of `header`, or `None`."""
    header_set = set(header)
    for profile in PROFILES:
        if profile.signature <= header_set:
            return profile
    return None
