"""Unit tests for strata.ingest.profiles."""

from __future__ import annotations

from strata.ingest.profiles import (
    DIMENSIONS,
    EBSCOHOST,
    GOOGLE_SCHOLAR_POP,
    PROFILES,
    PROQUEST,
    SCOPUS,
    WEB_OF_SCIENCE,
    detect_profile,
)


def test_detect_profile_scopus() -> None:
    header = ["Authors", "Title", "Year", "Source title", "Volume", "DOI", "EID"]
    assert detect_profile(header) is SCOPUS


def test_detect_profile_web_of_science() -> None:
    header = [
        "Authors",
        "Article Title",
        "Source Title",
        "Publication Year",
        "UT (Unique WOS ID)",
        "DOI",
    ]
    assert detect_profile(header) is WEB_OF_SCIENCE


def test_detect_profile_ebscohost() -> None:
    header = ["Authors", "Title", "Journal Name", "Accession Number", "Volume"]
    assert detect_profile(header) is EBSCOHOST


def test_detect_profile_proquest() -> None:
    header = ["Title", "Author", "Publication title", "ProQuest document ID"]
    assert detect_profile(header) is PROQUEST


def test_detect_profile_dimensions() -> None:
    header = ["Title", "Authors", "Source title", "PubYear", "DOI"]
    assert detect_profile(header) is DIMENSIONS


def test_detect_profile_google_scholar_pop() -> None:
    header = ["Authors", "Title", "Year", "Source", "GSRank", "Cites"]
    assert detect_profile(header) is GOOGLE_SCHOLAR_POP


def test_detect_profile_no_match_returns_none() -> None:
    assert detect_profile(["Some", "Random", "Columns"]) is None


def test_detect_profile_partial_signature_does_not_match() -> None:
    # Missing "EID" and "Source title" -- not enough to be mistaken for Scopus.
    assert detect_profile(["Authors", "Title", "Year"]) is None


def test_every_profile_mapping_includes_title() -> None:
    for profile in PROFILES:
        assert "title" in profile.mapping, profile.name
