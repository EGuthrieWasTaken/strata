"""Unit tests for strata.core.records."""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

from strata.core import aliases as aliases_mod
from strata.core.events import iter_event_files, read_events
from strata.core.fieldedit import FixFieldError
from strata.core.filters import FilterEvaluationError
from strata.core.ids import record_id as id_for_key
from strata.core.records import (
    AmbiguousRecordIdError,
    RecordNotFoundError,
    amend_field,
    get_record,
    index_by_id,
    preview_amendment,
    read_records,
    record_field_resolver,
    records_path,
    records_sharing_identity,
    resolve_id_prefix,
    write_records,
)
from strata.core.repo import Repo
from strata.core.validate import SchemaValidationError

_MANIFEST = """\
schema_version = 1
created_with = "strata/0.1.0"

[project]
id = "prj_x"
title = "T"
slug = "t"
created = "2026-01-01"

[[actors]]
handle = "ethan"
name = "Ethan"
role = "lead"
"""


def _repo(tmp_path: Path) -> Repo:
    (tmp_path / "strata.toml").write_text(_MANIFEST, encoding="utf-8")
    return Repo(root=tmp_path, config=tomllib.loads(_MANIFEST))


def _record(record_id: str, title: str = "T") -> dict:
    return {
        "id": record_id,
        "type": "article-journal",
        "title": title,
        "strata": {
            "canonical_key": f"sig:{title.lower()}",
            "canonical": True,
            "sources": [{"import": "imp_01arz3ndektsv4rrffq69g5fav"}],
        },
    }


def test_read_records_missing_file_returns_empty(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    assert read_records(repo) == []


def test_write_then_read_round_trips(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    records = [_record("rec_0000000000000002"), _record("rec_0000000000000001")]
    write_records(repo, records)
    reloaded = read_records(repo)
    assert [r["id"] for r in reloaded] == ["rec_0000000000000001", "rec_0000000000000002"]


def test_write_records_sorts_on_disk_byte_wise(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    write_records(repo, [_record("rec_zzzzzzzzzzzzzzzz"), _record("rec_0000000000000001")])
    text = records_path(repo).read_text(encoding="utf-8")
    lines = [line for line in text.split("\n") if line]
    assert lines[0].startswith('{"author"') is False  # sanity: not asserting field order here
    assert '"id":"rec_0000000000000001"' in lines[0]
    assert '"id":"rec_zzzzzzzzzzzzzzzz"' in lines[1]


def test_write_records_rejects_invalid_record(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    invalid = _record("rec_0000000000000001")
    del invalid["title"]
    with pytest.raises(SchemaValidationError):
        write_records(repo, [invalid])


def test_index_by_id(tmp_path: Path) -> None:
    records = [_record("rec_0000000000000001"), _record("rec_0000000000000002")]
    index = index_by_id(records)
    assert set(index) == {"rec_0000000000000001", "rec_0000000000000002"}
    assert index["rec_0000000000000001"]["id"] == "rec_0000000000000001"


def test_get_record_found_and_missing(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    write_records(repo, [_record("rec_0000000000000001")])
    assert get_record(repo, "rec_0000000000000001") is not None
    assert get_record(repo, "rec_nonexistent0000") is None


def test_get_record_missing_file_returns_none(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    assert get_record(repo, "rec_0000000000000001") is None


def test_get_record_skips_a_substring_false_positive(tmp_path: Path) -> None:
    """`get_record`'s line-prefilter is a plain substring search on
    `"id":"<value>"` (cheap next to parsing every line as JSON at scale --
    see its docstring). That means a line whose *raw text* happens to
    contain another record's id/needle verbatim, without actually being
    that record, must still be skipped rather than mis-returned -- the
    final `record["id"] == record_id` check is what guards that, and this
    directly exercises it via a hand-written NDJSON file (canonical JSON's
    own string-escaping makes this awkward to trigger through
    `write_records`, so this writes the file directly)."""
    repo = _repo(tmp_path)
    path = records_path(repo)
    path.parent.mkdir(parents=True, exist_ok=True)
    # A JSON string can't contain a literal unescaped quote, so the only way
    # the raw substring `"id":"rec_target0000001"` can appear verbatim in
    # otherwise-valid JSON without *being* that record is as a nested
    # object's own "id" key -- exactly what this decoy line does.
    decoy_line = (
        '{"id":"rec_decoy00000000001","nested":{"id":"rec_target0000001"},'
        '"strata":{"canonical":true},"title":"Decoy"}'
    )
    target_line = '{"id":"rec_target0000001","strata":{"canonical":true},"title":"Target"}'
    path.write_text(decoy_line + "\n" + target_line + "\n", encoding="utf-8")

    found = get_record(repo, "rec_target0000001")
    assert found is not None
    assert found["id"] == "rec_target0000001"
    assert found["title"] == "Target"


def test_read_records_skips_blank_lines(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    write_records(repo, [_record("rec_0000000000000001")])
    path = records_path(repo)
    path.write_text(path.read_text(encoding="utf-8") + "\n\n", encoding="utf-8")
    assert len(read_records(repo)) == 1


# ---- resolve_id_prefix --------------------------------------------------------


def test_resolve_id_prefix_unambiguous(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    write_records(repo, [_record("rec_0000000000000001"), _record("rec_1111111111111111")])
    assert resolve_id_prefix(repo, "rec_000") == "rec_0000000000000001"


def test_resolve_id_prefix_full_id(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    write_records(repo, [_record("rec_0000000000000001")])
    assert resolve_id_prefix(repo, "rec_0000000000000001") == "rec_0000000000000001"


def test_resolve_id_prefix_no_match_raises(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    write_records(repo, [_record("rec_0000000000000001")])
    with pytest.raises(RecordNotFoundError):
        resolve_id_prefix(repo, "rec_zzz")


def test_resolve_id_prefix_ambiguous_raises(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    write_records(repo, [_record("rec_0000000000000001"), _record("rec_0000000000000002")])
    with pytest.raises(AmbiguousRecordIdError) as exc_info:
        resolve_id_prefix(repo, "rec_000")
    assert exc_info.value.matches == ["rec_0000000000000001", "rec_0000000000000002"]
    assert "rec_0000000000000001" in str(exc_info.value)


# ---- record_field_resolver -----------------------------------------------------


def _full_record() -> dict:
    return {
        "id": "rec_0000000000000001",
        "type": "article-journal",
        "title": "A Title",
        "abstract": "An abstract.",
        "DOI": "10.1000/x",
        "PMID": "12345",
        "container-title": "A Journal",
        "issued": {"date-parts": [[2020]]},
        "author": [{"family": "Smith"}, {"family": "Jones"}, "not-a-dict", {"given": "no-family"}],
        "strata": {
            "canonical_key": "sig:a-title",
            "canonical": True,
            "sources": [
                {"import": "imp_01arz3ndektsv4rrffq69g5fav", "via": "database", "search": "S-01"},
                {"import": "imp_01arz3ndektsv4rrffq69g5fav", "via": "citation-searching"},
            ],
        },
    }


@pytest.mark.parametrize(
    ("field", "expected"),
    [
        ("id", "rec_0000000000000001"),
        ("doi", "10.1000/x"),
        ("pmid", "12345"),
        ("title", "A Title"),
        ("abstract", "An abstract."),
        ("journal", "A Journal"),
        ("year", 2020),
        ("authors", ["Smith", "Jones"]),
        ("via", "database"),
        ("search", "S-01"),
    ],
)
def test_record_field_resolver_known_fields(field: str, expected: object) -> None:
    resolve = record_field_resolver(_full_record())
    assert resolve(field) == expected


def test_record_field_resolver_missing_optional_fields_are_falsy_defaults() -> None:
    resolve = record_field_resolver(
        {"id": "rec_0000000000000001", "type": "article-journal", "title": "T", "strata": {}}
    )
    assert resolve("doi") is None
    assert resolve("pmid") is None
    assert resolve("abstract") == ""
    assert resolve("journal") == ""
    assert resolve("year") is None
    assert resolve("authors") == []
    assert resolve("via") is None
    assert resolve("search") is None


@pytest.mark.parametrize(
    "field", ["tiab", "fulltext", "stale", "criteria", "rob_overall", "derived_from_pvalue"]
)
def test_record_field_resolver_not_yet_available_scalar_fields(field: str) -> None:
    resolve = record_field_resolver(_full_record())
    with pytest.raises(FilterEvaluationError, match="not available yet"):
        resolve(field)


@pytest.mark.parametrize("field", ["actor_decision.ethan", "rob.selection"])
def test_record_field_resolver_not_yet_available_prefixed_fields(field: str) -> None:
    resolve = record_field_resolver(_full_record())
    with pytest.raises(FilterEvaluationError, match="not available yet"):
        resolve(field)


def test_record_field_resolver_unknown_field_raises() -> None:
    resolve = record_field_resolver(_full_record())
    with pytest.raises(FilterEvaluationError, match="unknown filter field"):
        resolve("not_a_real_field")


# ---- amend_field ----------------------------------------------------------------


def _doi_record(record_id: str, doi: str | None, title: str = "Spacing effects") -> dict:
    record = {
        "id": record_id,
        "type": "article-journal",
        "title": title,
        "author": [{"family": "Cepeda", "given": "N."}],
        "issued": {"date-parts": [[2008, 3]]},
        "strata": {
            "canonical_key": f"doi:{doi}" if doi else "sig:spacing effects|2008|cepeda",
            "canonical": True,
            "sources": [{"import": "imp_01arz3ndektsv4rrffq69g5fav"}],
        },
    }
    if doi:
        record["DOI"] = doi
    return record


def test_amend_field_updates_value_and_returns_old_new(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    write_records(repo, [_record("rec_0000000000000001", title="Old Title")])
    amendment = amend_field(
        repo, record_id="rec_0000000000000001", field="title", value="New Title", actor="ethan"
    )
    assert (amendment.old, amendment.new, amendment.changed) == ("Old Title", "New Title", True)
    assert get_record(repo, "rec_0000000000000001")["title"] == "New Title"


def test_amend_field_appends_record_amend_event(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    write_records(repo, [_record("rec_0000000000000001", title="Old Title")])
    amend_field(
        repo, record_id="rec_0000000000000001", field="title", value="New Title", actor="ethan"
    )
    events = [e for path in iter_event_files(repo.root) for e in read_events(path)]
    amend_events = [e for e in events if e["ev"] == "record-amend"]
    assert len(amend_events) == 1
    assert amend_events[0]["body"] == {
        "record": "rec_0000000000000001",
        "field": "title",
        "old": "Old Title",
        "new": "New Title",
        "source": "manual",
    }


def test_amend_field_unknown_record_raises(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    write_records(repo, [_record("rec_0000000000000001")])
    with pytest.raises(RecordNotFoundError):
        amend_field(repo, record_id="rec_nonexistent0000", field="title", value="x", actor="ethan")


@pytest.mark.parametrize("field", ["id", "type", "strata", "no-such-field"])
def test_amend_field_rejects_a_field_that_is_not_metadata(tmp_path: Path, field: str) -> None:
    repo = _repo(tmp_path)
    write_records(repo, [_record("rec_0000000000000001")])
    with pytest.raises(FixFieldError, match="cannot be corrected with `strata fix`"):
        amend_field(repo, record_id="rec_0000000000000001", field=field, value="x", actor="ethan")


def test_a_value_the_record_already_has_writes_and_records_nothing(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    write_records(repo, [_record("rec_0000000000000001", title="Same")])
    before = records_path(repo).read_text()

    amendment = amend_field(
        repo, record_id="rec_0000000000000001", field="title", value="  Same  ", actor="ethan"
    )

    assert amendment.changed is False and amendment.event is None
    assert records_path(repo).read_text() == before
    assert not list(iter_event_files(repo.root))


def test_a_doi_is_stored_as_an_import_would_store_it(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    write_records(repo, [_doi_record("rec_0000000000000001", "10.1000/a")])
    amend_field(
        repo,
        record_id="rec_0000000000000001",
        field="DOI",
        value="  https://doi.org/10.1000/B.  ",
        actor="ethan",
    )
    assert get_record(repo, "rec_0000000000000001")["DOI"] == "10.1000/b"


def test_an_empty_value_removes_the_field_but_never_the_title(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    record = _doi_record("rec_0000000000000001", "10.1000/a")
    record["abstract"] = "An abstract."
    write_records(repo, [record])

    removed = amend_field(
        repo, record_id="rec_0000000000000001", field="abstract", value=" ", actor="ethan"
    )

    assert removed.new is None
    assert "abstract" not in get_record(repo, "rec_0000000000000001")
    with pytest.raises(FixFieldError, match="title cannot be empty"):
        amend_field(repo, record_id="rec_0000000000000001", field="title", value="", actor="ethan")


def test_authors_are_read_from_text_and_year_keeps_the_month(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    write_records(repo, [_doi_record("rec_0000000000000001", "10.1000/a")])

    amend_field(
        repo,
        record_id="rec_0000000000000001",
        field="author",
        value="Cepeda, Nicholas J.; Vul, Edward; World Health Organization",
        actor="ethan",
    )
    amend_field(repo, record_id="rec_0000000000000001", field="year", value="2009", actor="ethan")

    record = get_record(repo, "rec_0000000000000001")
    assert record["author"] == [
        {"family": "Cepeda", "given": "Nicholas J."},
        {"family": "Vul", "given": "Edward"},
        {"literal": "World Health Organization"},
    ]
    assert record["issued"] == {"date-parts": [[2009, 3]]}
    events = [e for path in iter_event_files(repo.root) for e in read_events(path)]
    assert [e["body"]["field"] for e in events] == [
        "author",
        "issued",
    ]  # `year` is stored as `issued`


def test_correcting_the_identity_keeps_the_id_and_makes_the_new_id_an_alias(
    tmp_path: Path,
) -> None:
    repo = _repo(tmp_path)
    write_records(repo, [_doi_record("rec_0000000000000001", "10.1000/wrong")])

    amendment = amend_field(
        repo, record_id="rec_0000000000000001", field="DOI", value="10.1000/right", actor="ethan"
    )

    record = get_record(repo, "rec_0000000000000001")
    assert record["strata"]["canonical_key"] == "doi:10.1000/right"
    assert amendment.alias is not None and amendment.alias.startswith("rec_")
    entries = aliases_mod.read_aliases(repo)
    assert [(e["alias"], e["canonical"], e["reason"]) for e in entries] == [
        (amendment.alias, "rec_0000000000000001", "correction")
    ]
    assert entries[0]["event"] == amendment.event["id"]
    assert aliases_mod.resolve(repo, amendment.alias) == "rec_0000000000000001"


def test_a_correction_that_leaves_the_identity_alone_makes_no_alias(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    write_records(repo, [_doi_record("rec_0000000000000001", "10.1000/a")])

    # The record has a DOI, so the title and year are not part of its identity.
    amend_field(repo, record_id="rec_0000000000000001", field="title", value="New", actor="ethan")
    amend_field(repo, record_id="rec_0000000000000001", field="year", value="2010", actor="ethan")

    assert aliases_mod.read_aliases(repo) == []
    assert get_record(repo, "rec_0000000000000001")["strata"]["canonical_key"] == "doi:10.1000/a"


def test_a_year_is_part_of_the_identity_of_a_record_with_no_identifier(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    write_records(repo, [_doi_record("rec_0000000000000001", None)])

    amendment = amend_field(
        repo, record_id="rec_0000000000000001", field="year", value="2009", actor="ethan"
    )

    assert amendment.alias is not None
    key = get_record(repo, "rec_0000000000000001")["strata"]["canonical_key"]
    assert key == "sig:spacing effects|2009|cepeda"


def test_correcting_onto_the_identity_of_another_record_names_it_and_makes_no_alias(
    tmp_path: Path,
) -> None:
    repo = _repo(tmp_path)
    holder = id_for_key("doi:10.1000/b")  # a record's id is the hash of its key
    write_records(
        repo,
        [
            _doi_record("rec_0000000000000001", "10.1000/a"),
            _doi_record(holder, "10.1000/b", title="Another"),
        ],
    )

    amendment = amend_field(
        repo, record_id="rec_0000000000000001", field="DOI", value="10.1000/b", actor="ethan"
    )

    assert amendment.alias is None and amendment.shares_identity_with == holder
    assert aliases_mod.read_aliases(repo) == []
    assert records_sharing_identity(repo, get_record(repo, "rec_0000000000000001")) == [holder]


def test_preview_says_whether_a_correction_would_change_anything(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    write_records(repo, [_record("rec_0000000000000001", title="Same")])
    assert (
        preview_amendment(repo, record_id="rec_0000000000000001", field="title", value="Same")
        is False
    )
    assert (
        preview_amendment(repo, record_id="rec_0000000000000001", field="title", value="Other")
        is True
    )
    with pytest.raises(FixFieldError):
        preview_amendment(repo, record_id="rec_0000000000000001", field="id", value="x")
    with pytest.raises(RecordNotFoundError):
        preview_amendment(repo, record_id="rec_nonexistent0000", field="title", value="x")
