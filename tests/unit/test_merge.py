"""Unit tests for strata.dedup.merge, per docs/spec/05-workflow-import.md §3.5."""

from __future__ import annotations

from strata.dedup.merge import choose_canonical, merge_fields

_SOURCE_TRUST = ["crossref", "pubmed", "scopus", "wos", "embase", "ebsco", "manual"]


def _record(record_id: str, database: str | None = None, **fields) -> dict:
    sources = [{"database": database}] if database else []
    return {"id": record_id, "strata": {"sources": sources}, **fields}


def test_choose_canonical_by_completeness() -> None:
    a = _record("rec_0000000000000001", DOI="10.1/x", abstract="x", author=[{}], page="1")
    b = _record("rec_0000000000000002", DOI="10.1/x")
    canonical, absorbed = choose_canonical(a, b, _SOURCE_TRUST)
    assert canonical["id"] == "rec_0000000000000001"
    assert absorbed["id"] == "rec_0000000000000002"


def test_choose_canonical_falls_back_to_trust_when_completeness_ties() -> None:
    a = _record("rec_0000000000000001", database="ebsco", DOI="10.1/x")
    b = _record("rec_0000000000000002", database="pubmed", DOI="10.1/x")
    canonical, _absorbed = choose_canonical(a, b, _SOURCE_TRUST)
    assert canonical["id"] == "rec_0000000000000002"  # pubmed outranks ebsco


def test_choose_canonical_falls_back_to_lowest_id_when_trust_ties_too() -> None:
    a = _record("rec_0000000000000002", database="pubmed")
    b = _record("rec_0000000000000001", database="pubmed")
    canonical, absorbed = choose_canonical(a, b, _SOURCE_TRUST)
    assert canonical["id"] == "rec_0000000000000001"
    assert absorbed["id"] == "rec_0000000000000002"


def test_choose_canonical_untrusted_source_ranks_last() -> None:
    a = _record("rec_0000000000000001", database="some-unlisted-vendor")
    b = _record("rec_0000000000000002", database="manual")
    canonical, _absorbed = choose_canonical(a, b, _SOURCE_TRUST)
    assert canonical["id"] == "rec_0000000000000002"  # "manual" is listed; the other isn't


def test_merge_fields_copies_field_only_absorbed_has() -> None:
    canonical = _record("rec_0000000000000001", database="scopus", title="T")
    absorbed = _record("rec_0000000000000002", database="scopus", title="T", DOI="10.1/x")
    fields, provenance = merge_fields(canonical, absorbed, _SOURCE_TRUST)
    assert fields["DOI"] == "10.1/x"
    assert provenance["DOI"] == "scopus"


def test_merge_fields_conflict_resolved_by_trust() -> None:
    canonical = _record("rec_0000000000000001", database="ebsco", title="Canonical Title")
    absorbed = _record("rec_0000000000000002", database="pubmed", title="Absorbed Title")
    fields, provenance = merge_fields(canonical, absorbed, _SOURCE_TRUST)
    assert fields["title"] == "Absorbed Title"  # pubmed outranks ebsco
    assert provenance["title"] == "pubmed"


def test_merge_fields_conflict_canonical_more_trusted_keeps_canonical_value() -> None:
    canonical = _record("rec_0000000000000001", database="pubmed", title="Canonical Title")
    absorbed = _record("rec_0000000000000002", database="ebsco", title="Absorbed Title")
    fields, provenance = merge_fields(canonical, absorbed, _SOURCE_TRUST)
    assert fields["title"] == "Canonical Title"
    assert provenance["title"] == "pubmed"


def test_merge_fields_abstract_longest_wins() -> None:
    canonical = _record("rec_0000000000000001", abstract="Short.")
    absorbed = _record("rec_0000000000000002", abstract="A much longer abstract with detail.")
    fields, provenance = merge_fields(canonical, absorbed, _SOURCE_TRUST)
    assert fields["abstract"] == "A much longer abstract with detail."
    assert provenance["abstract"] == "merged"


def test_merge_fields_abstract_canonical_longer_wins() -> None:
    canonical = _record("rec_0000000000000001", abstract="A much longer abstract with detail.")
    absorbed = _record("rec_0000000000000002", abstract="Short.")
    fields, _provenance = merge_fields(canonical, absorbed, _SOURCE_TRUST)
    assert fields["abstract"] == "A much longer abstract with detail."


def test_merge_fields_keyword_union_preserves_order_canonical_first() -> None:
    canonical = _record("rec_0000000000000001", keyword="a; b")
    absorbed = _record("rec_0000000000000002", keyword="b; c")
    fields, provenance = merge_fields(canonical, absorbed, _SOURCE_TRUST)
    assert fields["keyword"] == "a; b; c"
    assert provenance["keyword"] == "merged"


def test_merge_fields_unknown_csl_field_preserved() -> None:
    canonical = _record("rec_0000000000000001")
    absorbed = _record("rec_0000000000000002", **{"publisher-place": "Geneva"})
    fields, _provenance = merge_fields(canonical, absorbed, _SOURCE_TRUST)
    assert fields["publisher-place"] == "Geneva"


def test_merge_fields_excludes_id_and_strata() -> None:
    canonical = _record("rec_0000000000000001", title="T")
    absorbed = _record("rec_0000000000000002", title="T")
    fields, _provenance = merge_fields(canonical, absorbed, _SOURCE_TRUST)
    assert "id" not in fields
    assert "strata" not in fields


def test_merge_fields_preserves_prior_field_provenance() -> None:
    canonical = {
        "id": "rec_0000000000000001",
        "title": "T",
        "strata": {"sources": [], "field_provenance": {"abstract": "an-earlier-merge"}},
    }
    absorbed = _record("rec_0000000000000002", DOI="10.1/x")
    _fields, provenance = merge_fields(canonical, absorbed, _SOURCE_TRUST)
    assert provenance["abstract"] == "an-earlier-merge"
    assert provenance["DOI"] == "manual"


def test_merge_fields_key_present_but_falsy_on_both_sides_is_skipped() -> None:
    canonical = _record("rec_0000000000000001", title="T", volume="")
    absorbed = _record("rec_0000000000000002", title="T")
    fields, provenance = merge_fields(canonical, absorbed, _SOURCE_TRUST)
    assert "volume" not in fields
    assert "volume" not in provenance


def test_merge_fields_neither_side_has_field_is_absent_from_result() -> None:
    canonical = _record("rec_0000000000000001", title="T")
    absorbed = _record("rec_0000000000000002", title="T")
    fields, provenance = merge_fields(canonical, absorbed, _SOURCE_TRUST)
    assert "DOI" not in fields
    assert "DOI" not in provenance
