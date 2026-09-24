"""Golden fixture tests for the bibliographic export parsers.

Implements docs/spec/14-testing.md §3. Each fixture under
`tests/fixtures/exports/` is read as raw bytes, put through the same
decode/newline-normalisation pipeline the import pipeline uses, parsed, and
compared against a committed expected result -- see `tests/fixtures/SOURCES.md`
for what each fixture covers and where it came from.
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from typing import Any

import pytest

from strata.ingest.parsers import ParseResult, decode_bytes, normalise_newlines
from strata.ingest.parsers import bibtex as bibtex_parser
from strata.ingest.parsers import csl_json as csl_json_parser
from strata.ingest.parsers import csv_tsv as csv_tsv_parser
from strata.ingest.parsers import medline as medline_parser
from strata.ingest.parsers import ris as ris_parser
from strata.ingest.profiles import detect_profile

FIXTURES = Path(__file__).parent.parent / "fixtures" / "exports"

PARSERS = {
    "csl-json": csl_json_parser.parse,
    "ris": ris_parser.parse,
    "bibtex": bibtex_parser.parse,
    "medline": medline_parser.parse,
}


def _parse_fixture(format_dir: str, filename: str) -> tuple[ParseResult, str]:
    raw = (FIXTURES / format_dir / filename).read_bytes()
    text, encoding = decode_bytes(raw)
    text = normalise_newlines(text)
    return PARSERS[format_dir](text), encoding


def _load_expected(format_dir: str, filename: str) -> Any:
    path = FIXTURES / format_dir / filename
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.mark.parametrize(
    ("format_dir", "clean_file"),
    [
        ("csl-json", "clean.json"),
        ("ris", "clean.ris"),
        ("bibtex", "clean.bib"),
        ("medline", "clean.nbib"),
    ],
)
def test_clean_fixture_matches_expected_records(format_dir: str, clean_file: str) -> None:
    result, _encoding = _parse_fixture(format_dir, clean_file)
    expected = _load_expected(format_dir, clean_file.rsplit(".", 1)[0] + ".expected.json")
    assert result.rejected == []
    assert result.records == expected


@pytest.mark.parametrize(
    ("format_dir", "malformed_file"),
    [
        ("csl-json", "malformed.json"),
        ("ris", "malformed.ris"),
        ("ris", "malformed-bom.ris"),
        ("ris", "malformed-cp1252.ris"),
        ("bibtex", "malformed.bib"),
        ("medline", "malformed.nbib"),
    ],
)
def test_malformed_fixture_matches_expected(format_dir: str, malformed_file: str) -> None:
    result, encoding = _parse_fixture(format_dir, malformed_file)
    expected = _load_expected(format_dir, malformed_file.rsplit(".", 1)[0] + ".expected.json")
    assert encoding == expected["encoding"]
    assert result.records == expected["records"]
    assert [dataclasses.asdict(r) for r in result.rejected] == expected["rejected"]


def test_csl_json_malformed_fixture_isolates_bad_entries() -> None:
    """A bad entry must not swallow the valid ones on either side of it (§2.1)."""
    result, _ = _parse_fixture("csl-json", "malformed.json")
    titles = [r["title"] for r in result.records]
    assert titles == [
        "A valid record before the bad ones",
        "A valid record after the bad ones",
    ]
    assert len(result.rejected) == 2


def test_ris_malformed_fixture_isolates_bad_records() -> None:
    result, _ = _parse_fixture("ris", "malformed.ris")
    titles = [r["title"] for r in result.records]
    assert "Record with no closing ER tag" in titles
    assert "DOI with trailing punctuation" in titles
    assert any(r.error == "missing or empty title" for r in result.rejected)


def test_bibtex_malformed_fixture_isolates_bad_entries() -> None:
    result, _ = _parse_fixture("bibtex", "malformed.bib")
    titles = [r["title"] for r in result.records]
    assert titles == [
        "A valid record before the bad one",
        "A valid record after the bad ones",
    ]
    assert len(result.rejected) == 2


def test_medline_malformed_fixture_isolates_bad_records() -> None:
    result, _ = _parse_fixture("medline", "malformed.nbib")
    titles = [r["title"] for r in result.records]
    assert titles == [
        "A valid record before the bad one",
        "Diacritics in author names & an inconsistently indented abstract",
        "A valid record after the bad ones",
    ]
    assert len(result.rejected) == 1


def _parse_csv_fixture(filename: str) -> tuple[ParseResult, str, str]:
    """Unlike the uniform-interface parsers, CSV needs a profile-resolved mapping first."""
    raw = (FIXTURES / "csv" / filename).read_bytes()
    text, encoding = decode_bytes(raw)
    text = normalise_newlines(text)
    header = csv_tsv_parser.read_header(text, delimiter=",")
    profile = detect_profile(header)
    assert profile is not None, f"no profile matched {filename}'s header: {header!r}"
    header_set = set(header)
    mapping = {f: c for f, c in profile.mapping.items() if c in header_set}
    return csv_tsv_parser.parse(text, delimiter=",", mapping=mapping), encoding, profile.name


@pytest.mark.parametrize(
    ("filename", "expected_profile"),
    [("scopus-clean.csv", "scopus"), ("wos-clean.csv", "web-of-science")],
)
def test_csv_clean_fixture_matches_expected_records(filename: str, expected_profile: str) -> None:
    result, _encoding, profile_name = _parse_csv_fixture(filename)
    assert profile_name == expected_profile
    expected = _load_expected("csv", filename.rsplit(".", 1)[0] + ".expected.json")
    assert result.rejected == []
    assert result.records == expected


def test_csv_malformed_fixture_matches_expected() -> None:
    result, encoding, profile_name = _parse_csv_fixture("scopus-malformed.csv")
    assert profile_name == "scopus"
    expected = _load_expected("csv", "scopus-malformed.expected.json")
    assert encoding == expected["encoding"]
    assert result.records == expected["records"]
    assert [dataclasses.asdict(r) for r in result.rejected] == expected["rejected"]


def test_csv_malformed_fixture_isolates_bad_rows() -> None:
    result, _encoding, _profile = _parse_csv_fixture("scopus-malformed.csv")
    titles = [r["title"] for r in result.records]
    assert titles == [
        "A valid record before the bad one",
        "Diacritics & HTML entities in this title",
        "A valid record after the bad one",
    ]
    assert len(result.rejected) == 1


def test_csl_json_whole_document_failure_has_no_recovery() -> None:
    """Unlike the line-oriented formats, broken JSON syntax fails the whole document."""
    raw = (FIXTURES / "csl-json" / "broken-document.json").read_bytes()
    text, _encoding = decode_bytes(raw)
    result = csl_json_parser.parse(normalise_newlines(text))
    assert result.records == []
    assert len(result.rejected) == 1
    assert result.rejected[0].line is not None
