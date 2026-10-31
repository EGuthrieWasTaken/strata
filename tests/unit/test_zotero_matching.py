"""Matching Zotero items to records by the canonical-key ladder, and reporting what matches nothing
(openspec:zotero-integration#identity-mapping)."""

from __future__ import annotations

from typing import Any

from strata.core.ids import canonical_key, record_id
from strata.integrations.reference_manager import ItemRef, RemoteItem
from strata.integrations.zotero.matching import RecordIndex, ladder, match_items

REVIEW_THRESHOLD = 0.80


def _record(title: str, *, canonical: bool = True, **fields: Any) -> dict[str, Any]:
    record: dict[str, Any] = {"type": "article-journal", "title": title, **fields}
    key, _ = canonical_key(record)
    record["id"] = record_id(key)
    record["strata"] = {"canonical_key": key, "canonical": canonical, "sources": []}
    return record


def _item(key: str, title: str, **fields: Any) -> RemoteItem:
    csl = {"type": "article-journal", "title": title, **fields}
    return RemoteItem(ItemRef("users/12345", key), 1, csl)


_CEPEDA = {
    "author": [{"family": "Cepeda", "given": "Nicholas"}],
    "issued": {"date-parts": [[2008]]},
}


def _match(items: list[RemoteItem], records: list[dict[str, Any]], **kwargs: Any):  # type: ignore[no-untyped-def]
    return match_items(items, RecordIndex(records), review_threshold=REVIEW_THRESHOLD, **kwargs)


def test_the_ladder_lists_the_rungs_a_record_stands_on_in_order() -> None:
    rungs = ladder(
        {
            "title": "Spacing effects",
            "DOI": "https://doi.org/10.1000/ABC",
            "PMID": "PMID: 123",
            "ISBN": "978-0-12",
            **_CEPEDA,
        }
    )

    assert [name for name, _ in rungs] == ["doi", "pmid", "isbn", "signature"]
    assert rungs[0] == ("doi", "10.1000/abc")  # normalised as record identity normalises
    assert rungs[1] == ("pmid", "123")


def test_a_title_with_no_identifier_stands_on_the_signature_alone() -> None:
    assert [name for name, _ in ladder({"title": "Spacing effects", **_CEPEDA})] == ["signature"]


def test_an_item_with_the_same_doi_is_matched_on_the_doi_whatever_its_title() -> None:
    record = _record("Spacing effects in learning", DOI="10.1000/abc", **_CEPEDA)

    report = _match(
        [_item("AAAAAAAA", "Spacing effects: a corrected title", DOI="10.1000/ABC")], [record]
    )

    (match,) = report.matched
    assert (match.record_id, match.via) == (record["id"], "doi")
    assert not (report.ambiguous or report.candidates or report.unmatched)


def test_a_pmid_matches_when_there_is_no_doi() -> None:
    record = _record("Spacing effects in learning", PMID="123", **_CEPEDA)

    report = _match([_item("AAAAAAAA", "Spacing effects in learning", PMID="123")], [record])

    assert [(m.record_id, m.via) for m in report.matched] == [(record["id"], "pmid")]


def test_the_signature_matches_a_record_that_has_no_identifier() -> None:
    record = _record("Spacing effects in learning", **_CEPEDA)

    report = _match([_item("AAAAAAAA", "Spacing Effects in Learning!", **_CEPEDA)], [record])

    assert [(m.record_id, m.via) for m in report.matched] == [(record["id"], "signature")]


def test_a_higher_rung_wins_over_a_lower_one() -> None:
    by_doi = _record("Spacing effects", DOI="10.1000/abc", author=[{"family": "Other"}])
    by_signature = _record("Spacing effects in learning", **_CEPEDA)
    item = _item("AAAAAAAA", "Spacing effects in learning", DOI="10.1000/abc", **_CEPEDA)

    report = _match([item], [by_doi, by_signature])

    assert [(m.record_id, m.via) for m in report.matched] == [(by_doi["id"], "doi")]


def test_two_different_dois_are_two_papers_however_alike_their_titles() -> None:
    record = _record("Spacing effects in learning", DOI="10.1000/abc", **_CEPEDA)
    item = _item("AAAAAAAA", "Spacing effects in learning", DOI="10.1000/different", **_CEPEDA)

    report = _match([item], [record])

    assert report.matched == [] and report.candidates == []  # the DOI veto holds here too
    assert [i.ref.key for i in report.unmatched] == ["AAAAAAAA"]


def test_an_item_that_two_records_share_a_rung_with_is_ambiguous_never_guessed() -> None:
    # Two records with different DOIs (so two identities) that both carry the item's PMID.
    first = _record("Spacing effects in learning", DOI="10.1000/one", PMID="123", **_CEPEDA)
    second = _record("Spacing effects: a reprint", DOI="10.1000/two", PMID="123", **_CEPEDA)

    report = _match([_item("AAAAAAAA", "Anything", PMID="123")], [first, second])

    (ambiguous,) = report.ambiguous
    assert ambiguous.via == "pmid"
    assert set(ambiguous.record_ids) == {first["id"], second["id"]}
    assert report.matched == []


def test_an_item_matching_a_record_that_was_merged_away_matches_the_record_that_remains() -> None:
    kept = _record("Spacing effects in learning", DOI="10.1000/abc", **_CEPEDA)
    absorbed = _record("Spacing effects in learning", PMID="123", canonical=False, **_CEPEDA)
    kept["strata"]["absorbed"] = [absorbed["id"]]

    report = _match([_item("AAAAAAAA", "Spacing effects", PMID="123")], [kept, absorbed])

    assert [(m.record_id, m.via) for m in report.matched] == [(kept["id"], "pmid")]


_PUBLISHED = {**_CEPEDA, "container-title": "Psychological Science", "page": "1095-1102"}


def test_a_close_but_not_exact_item_is_a_candidate_for_a_person_not_a_match() -> None:
    record = _record(
        "Spacing effects in learning: a temporal ridgeline of optimal retention", **_PUBLISHED
    )
    typo = _item(
        "AAAAAAAA",
        "Spacing effects in learning: a temporal ridge-line of optimal retention",
        **_PUBLISHED,
    )

    report = _match([typo], [record])

    assert report.matched == []  # not linked: it is not the same on any rung
    (candidate,) = report.candidates
    assert candidate.candidates[0].record_id == record["id"]
    assert candidate.candidates[0].score >= REVIEW_THRESHOLD


def test_an_item_like_nothing_in_the_review_is_unmatched() -> None:
    record = _record("Spacing effects in learning", DOI="10.1000/abc", **_CEPEDA)
    unrelated = _item(
        "AAAAAAAA",
        "Retrieval practice in secondary school science",
        author=[{"family": "Okafor"}],
        issued={"date-parts": [[2017]]},
    )

    report = _match([unrelated], [record])

    assert [i.ref.key for i in report.unmatched] == ["AAAAAAAA"]
    assert not (report.matched or report.ambiguous or report.candidates)


def test_a_record_already_linked_is_not_offered_as_a_candidate() -> None:
    record = _record(
        "Spacing effects in learning: a temporal ridgeline of optimal retention", **_PUBLISHED
    )
    typo = _item(
        "AAAAAAAA",
        "Spacing effects in learning: a temporal ridge-line of optimal retention",
        **_PUBLISHED,
    )

    report = _match([typo], [record], exclude_records=frozenset({record["id"]}))

    assert report.candidates == [] and [i.ref.key for i in report.unmatched] == ["AAAAAAAA"]


def test_every_item_lands_in_exactly_one_list() -> None:
    by_doi = _record("One", DOI="10.1000/one", **_CEPEDA)
    items = [
        _item("AAAAAAAA", "One", DOI="10.1000/one"),
        _item("BBBBBBBB", "Nothing like the others", author=[{"family": "Zed"}]),
    ]

    report = _match(items, [by_doi])

    placed = (
        [m.item.ref.key for m in report.matched]
        + [a.item.ref.key for a in report.ambiguous]
        + [c.item.ref.key for c in report.candidates]
        + [u.ref.key for u in report.unmatched]
    )
    assert sorted(placed) == ["AAAAAAAA", "BBBBBBBB"]


def test_the_pmcid_and_arxiv_rungs_are_part_of_the_ladder_in_identity_order() -> None:
    rungs = ladder({"title": "T", "PMCID": "pmc123", "arXiv": "arXiv:2101.00001", **_CEPEDA})

    assert [r for r in rungs if r[0] in ("pmcid", "arxiv")] == [
        ("pmcid", "PMC123"),
        ("arxiv", "2101.00001"),
    ]
    assert [name for name, _ in rungs] == ["pmcid", "arxiv", "signature"]


def test_an_item_matches_a_record_on_its_arxiv_id() -> None:
    record = _record("A preprint", arXiv="2101.00001", **_CEPEDA)

    report = _match([_item("AAAAAAAA", "A preprint, retitled", arXiv="arxiv:2101.00001")], [record])

    assert [(m.record_id, m.via) for m in report.matched] == [(record["id"], "arxiv")]
