"""link / pull / push / status / open against a real review and a fake Zotero, once per pinned
Zotero major version where the transport matters (openspec:zotero-integration)."""

from __future__ import annotations

import json
import tomllib
from pathlib import Path
from typing import Any

import pytest

from strata import gitio
from strata.core import records as records_mod
from strata.core.commit import RationaleRejectedError
from strata.core.events import iter_event_files, read_events
from strata.core.repo import open_repo
from strata.ingest.pipeline import ImportPipelineError, list_import_manifests
from strata.integrations.zotero import mapping as mapping_mod
from strata.integrations.zotero import operations as zotero_ops
from strata.integrations.zotero.connect import read_link
from strata.report import counts as counts_mod
from tests.integration._zotero import (
    CEPEDA,
    ONLY_HERE,
    ROEDIGER,
    SMITH,
    connector_for,
    review_with,
)
from tests.unit._m3 import decide
from tests.zotero_fake import API_KEY, LOCAL_HOST, MAJOR_VERSIONS, FakeZotero

LIB = "users/12345"
WHY = "recording what this step did to the review's Zotero link"


def _link(repo, fake, **kwargs):  # type: ignore[no-untyped-def]
    kwargs.setdefault("library", LIB)  # the fixture person has a group too, so one must be chosen
    return zotero_ops.link(
        repo, actor="ethan", connector=connector_for(fake), rationale=WHY, **kwargs
    )


def _git(repo, *args: str) -> str:  # type: ignore[no-untyped-def]
    return gitio.run(list(args), cwd=repo.root).stdout


def _commit_subjects(repo) -> list[str]:  # type: ignore[no-untyped-def]
    return gitio.log(repo.root, fmt="%s")


# --------------------------------------------------------------------------------------- link


@pytest.mark.parametrize("major", MAJOR_VERSIONS)
def test_link_maps_the_records_it_can_match_by_the_canonical_key_ladder(
    tmp_path: Path, major: str
) -> None:
    repo, ids = review_with(tmp_path, CEPEDA, ROEDIGER, SMITH, ONLY_HERE)
    fake = FakeZotero(major)

    result = _link(repo, fake)

    rows = {r.item_key: r for r in mapping_mod.read_mapping(repo)}
    assert set(rows) == {"AB3D9XYZ", "CD4E5FGH", "JK6L7MNP"}
    assert (rows["AB3D9XYZ"].record, rows["AB3D9XYZ"].via) == (ids[0], "doi")
    assert (rows["CD4E5FGH"].record, rows["CD4E5FGH"].via) == (ids[1], "doi")
    assert (rows["JK6L7MNP"].record, rows["JK6L7MNP"].via) == (ids[2], "signature")
    assert all(r.library == LIB and r.item_version > 0 for r in rows.values())
    assert result.rows_written == 3
    # The library's Okafor item matches nothing in the review: reported, not forced onto a record.
    assert [i.ref.key for i in result.report.unmatched] == ["QR8S2TUV"]
    assert result.committed is True


def test_link_over_the_local_api_asks_for_no_key_and_records_a_read_only_link(
    tmp_path: Path,
) -> None:
    repo, _ = review_with(tmp_path, CEPEDA)
    fake = FakeZotero("7")

    result = zotero_ops.link(
        repo,
        actor="ethan",
        connector=connector_for(fake, keychain=False, key=None),  # no key, no keychain
        library=LIB,
        rationale=WHY,
    )

    assert result.transport == "local"
    assert result.write is False and result.write_note is not None
    assert "strata zotero link --web" in result.write_note
    assert {r.host for r in fake.requests} == {LOCAL_HOST}
    link = read_link(open_repo(repo.root))
    assert link is not None and (link.library, link.transport, link.write) == (LIB, "auto", False)


def test_link_over_the_web_checks_write_permission_now_not_at_push_time(tmp_path: Path) -> None:
    repo, _ = review_with(tmp_path, CEPEDA)

    allowed = _link(repo, FakeZotero("7"), web=True)
    assert allowed.transport == "web" and allowed.write is True and allowed.write_note is None
    assert read_link(open_repo(repo.root)).write is True  # type: ignore[union-attr]

    repo2, _ = review_with(tmp_path / "second", CEPEDA)
    denied = _link(repo2, FakeZotero("7", key_can_write=False), web=True)
    assert denied.write is False
    assert denied.write_note is not None and "cannot write" in denied.write_note
    assert read_link(open_repo(repo2.root)).write is False  # type: ignore[union-attr]


def test_link_never_puts_the_api_key_in_the_repository(tmp_path: Path) -> None:
    repo, _ = review_with(tmp_path, CEPEDA)

    _link(repo, FakeZotero("6"))  # Zotero 6 has no local API: the key is used

    for path in repo.root.rglob("*"):
        if path.is_file() and ".git/" not in path.as_posix():
            assert API_KEY.encode() not in path.read_bytes(), path
    gitlog = _git(repo, "log", "-p", "--all")
    assert API_KEY not in gitlog
    manifest = tomllib.loads((repo.root / "strata.toml").read_text(encoding="utf-8"))
    assert set(manifest["zotero"]) == {"library", "transport", "write"}


def test_link_makes_the_mapping_merge_by_union_in_a_review_that_lacks_the_rule(
    tmp_path: Path,
) -> None:
    repo, _ = review_with(tmp_path, CEPEDA)
    attributes = repo.root / ".gitattributes"
    attributes.write_text(
        attributes.read_text(encoding="utf-8").replace("integrations/*.ndjson  merge=union\n", "")
    )
    assert "integrations/" not in attributes.read_text(encoding="utf-8")

    _link(repo, FakeZotero("7"))
    _link(repo, FakeZotero("7"))

    text = attributes.read_text(encoding="utf-8")
    assert text.count("integrations/*.ndjson") == 1


def test_link_is_idempotent_and_a_rerun_commits_nothing(tmp_path: Path) -> None:
    repo, _ = review_with(tmp_path, CEPEDA, ROEDIGER)
    fake = FakeZotero("7")
    _link(repo, fake)
    commits = _commit_subjects(repo)
    mapping = (repo.root / "integrations" / "zotero.ndjson").read_bytes()

    again = zotero_ops.link(
        repo, actor="ethan", connector=connector_for(fake), library=LIB, commit=True
    )

    assert again.rows_written == 0 and again.committed is False
    assert (repo.root / "integrations" / "zotero.ndjson").read_bytes() == mapping
    assert _commit_subjects(repo) == commits


def test_a_link_that_would_change_something_is_refused_without_a_rationale_before_any_write(
    tmp_path: Path,
) -> None:
    repo, _ = review_with(tmp_path, CEPEDA)
    before = gitio.run(["status", "--porcelain"], cwd=repo.root).stdout

    with pytest.raises(RationaleRejectedError, match="rationale is required"):
        zotero_ops.link(
            repo,
            actor="ethan",
            connector=connector_for(FakeZotero("7")),
            library=LIB,
            commit=True,
        )

    assert gitio.run(["status", "--porcelain"], cwd=repo.root).stdout == before
    assert not (repo.root / "integrations").exists()
    assert read_link(open_repo(repo.root)) is None


def test_link_follows_an_item_edited_in_zotero_with_a_new_row_not_a_rewrite(
    tmp_path: Path,
) -> None:
    repo, _ = review_with(tmp_path, CEPEDA)
    fake = FakeZotero("7")
    _link(repo, fake)
    first = (repo.root / "integrations" / "zotero.ndjson").read_bytes()
    new_version = fake.edit_item(LIB, "AB3D9XYZ", volume="19")

    _link(repo, fake)

    text = (repo.root / "integrations" / "zotero.ndjson").read_bytes()
    assert text.startswith(first) and len(text.splitlines()) == 2
    (current,) = mapping_mod.current_rows(mapping_mod.read_mapping(repo), LIB)
    assert current.item_version == new_version
    assert current.linked == json.loads(first)["linked"]  # when it was first linked is kept


def test_link_names_the_libraries_when_there_is_a_choice_and_takes_a_group(tmp_path: Path) -> None:
    repo, _ = review_with(tmp_path, CEPEDA)
    fake = FakeZotero("7")

    with pytest.raises(zotero_ops.ZoteroOperationError, match="groups/777 \\(Lab reading group\\)"):
        _link(repo, fake, library=None)
    result = _link(repo, fake, library="groups/777")

    assert result.library == "groups/777"
    assert read_link(open_repo(repo.root)).library == "groups/777"  # type: ignore[union-attr]
    with pytest.raises(zotero_ops.ZoteroOperationError, match="is not one of your libraries"):
        _link(repo, fake, library="groups/1")


def test_link_asks_a_person_to_choose_when_given_a_chooser(tmp_path: Path) -> None:
    repo, _ = review_with(tmp_path, CEPEDA)
    offered: list[list[str]] = []

    def chooser(libraries):  # type: ignore[no-untyped-def]
        offered.append([lib.library for lib in libraries])
        return "groups/777"

    result = _link(repo, FakeZotero("7"), library=None, choose_library=chooser)

    assert offered == [["users/12345", "groups/777"]] and result.library == "groups/777"


def test_link_reports_a_near_miss_as_a_candidate_for_a_person(tmp_path: Path) -> None:
    near = {**CEPEDA, "title": CEPEDA["title"].replace("ridgeline", "ridge-line")}
    near.pop("DOI")  # no identifier to match on: only the fuzzy score is left
    repo, ids = review_with(tmp_path, near)
    fake = FakeZotero("7")

    result = _link(repo, fake)

    candidates = {c.item.ref.key: c for c in result.report.candidates}
    assert candidates["AB3D9XYZ"].candidates[0].record_id == ids[0]
    assert "AB3D9XYZ" not in {r.item_key for r in mapping_mod.read_mapping(repo)}  # never guessed


# ---------------------------------------------------------------------------------------- pull


def _pull(repo, fake, **kwargs):  # type: ignore[no-untyped-def]
    kwargs.setdefault("collection", "Hand-searched trials")
    kwargs.setdefault("via", "website")
    return zotero_ops.pull(
        repo, actor="ethan", connector=connector_for(fake), rationale=WHY, **kwargs
    )


def test_a_pull_needs_exactly_one_of_a_search_and_a_via(tmp_path: Path) -> None:
    repo, _ = review_with(tmp_path)
    fake = FakeZotero("7")
    _link(repo, fake)

    with pytest.raises(ImportPipelineError, match="exactly one of --search or --via"):
        _pull(repo, fake, via=None)
    with pytest.raises(ImportPipelineError, match="exactly one of --search or --via"):
        _pull(repo, fake, search_id="S-01-x", via="website")
    with pytest.raises(ImportPipelineError, match="invalid --via"):
        _pull(repo, fake, via="telepathy")
    assert list_import_manifests(repo) == []


def test_a_pull_before_a_link_says_to_link_first(tmp_path: Path) -> None:
    repo, _ = review_with(tmp_path)

    with pytest.raises(zotero_ops.NotLinkedError, match="strata zotero link"):
        _pull(repo, FakeZotero("7"))


@pytest.mark.parametrize("major", MAJOR_VERSIONS)
def test_a_hand_built_collection_is_pulled_as_other_methods_records(
    tmp_path: Path, major: str
) -> None:
    repo, _ = review_with(tmp_path)
    fake = FakeZotero(major)
    _link(repo, fake)

    result = _pull(repo, fake)

    assert (result.items_pulled, result.records_created, result.already_linked) == (3, 3, 0)
    records = records_mod.read_records(repo)
    assert {r["title"] for r in records} >= {SMITH["title"], ROEDIGER["title"]}
    (manifest,) = list_import_manifests(repo)
    assert manifest["via"] == "website" and manifest["search"] is None
    assert manifest["collection"] == {
        "manager": "zotero",
        "library": LIB,
        "key": "HANDPICK",
        "name": "Hand-searched trials",
    }
    assert manifest["source_file"].startswith("zotero-hand-searched-trials-")
    assert manifest["imported"] == manifest["source_file"].removesuffix(".json")[-10:]
    # PRISMA: a hand-built collection is counted under other methods, not as a database search
    box = json.loads(counts_mod.render_counts_json(repo))["identification"]
    assert box["other_methods"]["by_via"] == {"website": 3}
    assert box["databases"]["total"] == 0
    # and every pulled item is now linked to the record it became
    assert {r.item_key for r in mapping_mod.read_mapping(repo)} >= {
        "AB3D9XYZ",
        "CD4E5FGH",
        "JK6L7MNP",
    }


def test_a_collection_of_a_database_search_is_pulled_against_that_search(tmp_path: Path) -> None:
    from strata.protocol.searches import add_search

    repo, _ = review_with(tmp_path)
    add_search(
        repo,
        database="PubMed",
        platform="NCBI",
        executed="2026-03-01",
        executed_by="ethan",
        search_id="S-01-pubmed",
        query="spacing AND learning",
    )
    fake = FakeZotero("7")
    _link(repo, fake)

    _pull(repo, fake, collection="Hand-searched trials", search_id="S-01-pubmed", via=None)

    (manifest,) = list_import_manifests(repo)
    assert manifest["search"] == "S-01-pubmed" and manifest["via"] is None
    box = json.loads(counts_mod.render_counts_json(repo))["identification"]
    assert box["databases"]["by_search"] == {"S-01-pubmed": 3}


def test_pulling_an_unchanged_collection_again_changes_nothing(tmp_path: Path) -> None:
    repo, _ = review_with(tmp_path)
    fake = FakeZotero("7")
    _link(repo, fake)
    _pull(repo, fake)
    commits = _commit_subjects(repo)
    mapping = (repo.root / "integrations" / "zotero.ndjson").read_bytes()
    records = (repo.root / "records" / "records.ndjson").read_bytes()

    again = _pull(repo, fake)

    assert (again.records_created, again.already_linked, again.rows_written) == (0, 3, 0)
    assert again.import_id is None and again.committed is False
    assert (repo.root / "integrations" / "zotero.ndjson").read_bytes() == mapping
    assert (repo.root / "records" / "records.ndjson").read_bytes() == records
    assert _commit_subjects(repo) == commits
    assert len(list_import_manifests(repo)) == 1


def test_a_pull_commits_with_its_collection_and_import_in_the_trailers(tmp_path: Path) -> None:
    repo, _ = review_with(tmp_path)
    fake = FakeZotero("7")
    _link(repo, fake)

    result = _pull(repo, fake)

    message = _git(repo, "log", "-1", "--format=%B")
    assert "pull Hand-searched trials from Zotero" in message
    assert "Strata-Op: zotero-pull" in message
    assert "Strata-Collection: HANDPICK" in message
    assert f"Strata-Import: {result.import_id}" in message
    assert WHY in message


def test_a_title_corrected_in_zotero_is_recorded_as_a_record_amend_event(tmp_path: Path) -> None:
    repo, ids = review_with(tmp_path, CEPEDA, ROEDIGER)
    fake = FakeZotero("7")
    _link(repo, fake)
    corrected = "Spacing effects in learning: a temporal ridgeline of optimal retention"
    new_version = fake.edit_item(LIB, "AB3D9XYZ", title=corrected)

    result = _pull(repo, fake)

    assert records_mod.get_record(repo, ids[0])["title"] == corrected  # type: ignore[index]
    events = [
        e for p in iter_event_files(repo.root) for e in read_events(p) if e["ev"] == "record-amend"
    ]
    (title_event,) = [e for e in events if e["body"]["record"] == ids[0]]
    assert title_event["body"] == {
        "record": ids[0],
        "field": "title",
        "old": CEPEDA["title"],
        "new": corrected,
        "source": "zotero",
    }
    assert title_event["actor"] == "ethan"
    # Zotero's fuller metadata for the other record is carried in the same way, each field an event
    assert {e["body"]["field"] for e in events if e["body"]["record"] == ids[1]} == {
        "volume",
        "issue",
        "page",
    }
    # the link follows the item's new version, so a later push is not refused over this edit
    current = {r.item_key: r for r in mapping_mod.current_rows(mapping_mod.read_mapping(repo), LIB)}
    assert current["AB3D9XYZ"].item_version == new_version
    assert result.committed is True


def test_a_correction_to_a_record_with_no_doi_keeps_its_id_and_aliases_the_new_identity(
    tmp_path: Path,
) -> None:
    repo, ids = review_with(tmp_path, SMITH)
    fake = FakeZotero("7")
    _link(repo, fake)
    fake.edit_item(
        LIB, "JK6L7MNP", title="Spacing effects in a classroom: a quasi-experimental study"
    )

    result = _pull(repo, fake)

    (amendment,) = [a for a in result.amendments if a.changed]
    assert amendment.alias is not None
    smiths = [r for r in records_mod.read_records(repo) if "classroom" in r["title"]]
    assert [r["id"] for r in smiths] == ids  # the record kept its id; no second one appeared
    assert smiths[0]["title"].endswith("quasi-experimental study")
    assert result.records_created == 2  # only the collection's two other items are new


def test_zotero_never_removes_a_field_a_record_has(tmp_path: Path) -> None:
    repo, ids = review_with(tmp_path, CEPEDA)
    fake = FakeZotero("7")
    _link(repo, fake)  # Zotero's Cepeda item carries no abstract

    result = _pull(repo, fake)

    assert records_mod.get_record(repo, ids[0])["abstract"] == CEPEDA["abstract"]  # type: ignore[index]
    assert [a for a in result.amendments if a.changed] == []


def test_a_pull_never_touches_a_screening_decision(tmp_path: Path) -> None:
    repo, ids = review_with(tmp_path, CEPEDA, ROEDIGER)
    decide(repo, "title-abstract", ids)
    fake = FakeZotero("7")
    _link(repo, fake)
    fake.edit_item(LIB, "AB3D9XYZ", title="A different title entirely about spacing")
    screening = {p.name: p.read_bytes() for p in (repo.root / "events" / "screen").glob("*.ndjson")}
    assert screening

    _pull(repo, fake)

    after = {p.name: p.read_bytes() for p in (repo.root / "events" / "screen").glob("*.ndjson")}
    assert after == screening


def test_a_pulled_item_that_matches_an_existing_record_is_added_as_a_source_not_a_duplicate(
    tmp_path: Path,
) -> None:
    repo, ids = review_with(tmp_path, ROEDIGER)  # already imported from a database search
    fake = FakeZotero("7")

    _link(repo, fake)  # links Roediger to CD4E5FGH, but not the collection's other items
    result = zotero_ops.pull(
        repo,
        actor="ethan",
        connector=connector_for(fake),
        collection="Hand-searched trials",
        via="website",
        rationale=WHY,
    )

    assert result.already_linked == 1 and result.records_created == 2
    assert [r["id"] for r in records_mod.read_records(repo)].count(ids[0]) == 1


def test_an_item_whose_record_has_gone_from_the_review_is_reported_not_reimported(
    tmp_path: Path,
) -> None:
    repo, ids = review_with(tmp_path, CEPEDA)
    fake = FakeZotero("7")
    _link(repo, fake)
    records_mod.write_records(repo, [])  # the record is removed from the review

    result = _pull(repo, fake)

    assert result.vanished == ("AB3D9XYZ",)
    assert result.records_created == 2  # the other two items are new to this review
    assert ids[0] not in {r["id"] for r in records_mod.read_records(repo)}


# ---------------------------------------------------------------------------------------- push


def _included(tmp_path: Path, *csls: dict[str, Any]):  # type: ignore[no-untyped-def]
    repo, ids = review_with(tmp_path, *csls)
    decide(repo, "title-abstract", ids)
    decide(repo, "full-text", ids)
    return repo, ids


def _push(repo, fake, **kwargs):  # type: ignore[no-untyped-def]
    kwargs.setdefault("collection", "Included studies")
    return zotero_ops.push(
        repo,
        actor="ethan",
        connector=connector_for(fake),
        set_name="included",
        rationale=WHY,
        **kwargs,
    )


def test_a_push_needs_a_link_that_can_write(tmp_path: Path) -> None:
    repo, _ = _included(tmp_path, CEPEDA)
    with pytest.raises(zotero_ops.NotLinkedError):
        _push(repo, FakeZotero("7"))

    _link(repo, FakeZotero("7"))  # over the local API: read-only
    with pytest.raises(zotero_ops.ZoteroOperationError, match="cannot write"):
        _push(repo, FakeZotero("7"))


def test_only_the_included_set_exists(tmp_path: Path) -> None:
    repo, _ = _included(tmp_path, CEPEDA)

    with pytest.raises(zotero_ops.ZoteroOperationError, match="unknown set 'everything'"):
        zotero_ops.pushable_records(repo, "everything")


def test_a_push_adds_what_zotero_has_creates_what_it_lacks_and_records_both(
    tmp_path: Path,
) -> None:
    repo, ids = _included(tmp_path, CEPEDA, SMITH, ONLY_HERE)
    fake = FakeZotero("7")
    _link(repo, fake, web=True)

    result = _push(repo, fake)

    statuses = {o.record_id: o.status for o in result.outcomes}
    assert statuses == {ids[0]: "added", ids[1]: "added", ids[2]: "created"}
    items = fake.libraries[LIB].items
    assert "INCLUDED" in items["AB3D9XYZ"]["collections"]
    assert items["AB3D9XYZ"]["collections"] == ["HANDPICK", "INCLUDED"]  # other membership kept
    (created,) = [o for o in result.outcomes if o.status == "created"]
    assert created.ref is not None and items[created.ref.key]["collections"] == ["INCLUDED"]
    rows = {r.record: r for r in mapping_mod.current_rows(mapping_mod.read_mapping(repo), LIB)}
    assert rows[ids[2]].via == "created" and rows[ids[2]].item_key == created.ref.key
    assert rows[ids[0]].via == "doi"  # an item strata did not create stays marked as such
    assert result.committed is True
    assert "Strata-Op: zotero-push" in _git(repo, "log", "-1", "--format=%B")


def test_a_push_run_twice_is_a_no_op_the_second_time(tmp_path: Path) -> None:
    repo, _ = _included(tmp_path, CEPEDA, ONLY_HERE)
    fake = FakeZotero("7")
    _link(repo, fake, web=True)
    _push(repo, fake)
    writes_before = len(fake.writes())
    commits = _commit_subjects(repo)

    again = _push(repo, fake)

    assert {o.status for o in again.outcomes} == {"unchanged"}
    assert len(fake.writes()) == writes_before and again.committed is False
    assert _commit_subjects(repo) == commits


def test_an_item_edited_in_zotero_since_the_link_is_refused_and_a_pull_clears_it(
    tmp_path: Path,
) -> None:
    repo, ids = _included(tmp_path, CEPEDA, SMITH)
    fake = FakeZotero("7")
    _link(repo, fake, web=True)
    fake.edit_item(LIB, "JK6L7MNP", title="Spacing effects in a classroom: a quasi-experiment!")

    first = _push(repo, fake)

    assert {o.record_id: o.status for o in first.outcomes} == {ids[0]: "added", ids[1]: "refused"}
    assert "INCLUDED" not in fake.libraries[LIB].items["JK6L7MNP"]["collections"]
    assert first.count("refused") == 1

    _pull(repo, fake)  # sees the edit, so strata now holds the item's current version
    second = _push(repo, fake)
    assert {o.record_id: o.status for o in second.outcomes}[ids[1]] == "added"


def test_a_push_never_deletes_and_leaves_the_content_of_items_it_did_not_create(
    tmp_path: Path,
) -> None:
    repo, _ = _included(tmp_path, CEPEDA, SMITH, ONLY_HERE)
    fake = FakeZotero("7")
    _link(repo, fake, web=True)
    before = {k: json.dumps(i["csl"], sort_keys=True) for k, i in fake.libraries[LIB].items.items()}

    _push(repo, fake)

    assert {r.method for r in fake.requests} <= {"GET", "POST"}
    after = {k: json.dumps(i["csl"], sort_keys=True) for k, i in fake.libraries[LIB].items.items()}
    for key, content in before.items():
        assert after[key] == content, key
    assert set(before) <= set(after)  # nothing was removed from the library


def test_a_mapped_item_deleted_in_zotero_is_reported_stale_by_a_push(tmp_path: Path) -> None:
    repo, ids = _included(tmp_path, CEPEDA)
    fake = FakeZotero("7")
    _link(repo, fake, web=True)
    fake.delete_item(LIB, "AB3D9XYZ")

    result = _push(repo, fake)

    assert [(o.record_id, o.status) for o in result.outcomes] == [(ids[0], "stale")]


def test_nothing_included_pushes_nothing(tmp_path: Path) -> None:
    repo, _ = review_with(tmp_path, CEPEDA)  # no decisions
    fake = FakeZotero("7")
    _link(repo, fake, web=True)

    result = _push(repo, fake)

    assert result.outcomes == () and result.committed is False
    assert fake.writes() == []


# -------------------------------------------------------------------------------------- status


def test_status_counts_mapped_unmapped_and_stale_links(tmp_path: Path) -> None:
    repo, ids = review_with(tmp_path, CEPEDA, ROEDIGER, ONLY_HERE)
    fake = FakeZotero("7")
    _link(repo, fake)
    fake.delete_item(LIB, "CD4E5FGH")

    report = zotero_ops.status(repo, connector=connector_for(fake))

    assert (report.records, report.mapped) == (3, 2)
    assert report.unmapped == (ids[2],)
    assert report.stale == ((ids[1], "CD4E5FGH"),)
    assert report.unreachable is None and report.library == LIB


def test_status_reports_the_counts_even_when_zotero_cannot_be_reached(tmp_path: Path) -> None:
    repo, ids = review_with(tmp_path, CEPEDA, ONLY_HERE)
    _link(repo, FakeZotero("7"))
    down = FakeZotero("7", local_running=False)

    report = zotero_ops.status(repo, connector=connector_for(down, keychain=False, key=None))

    assert (report.records, report.mapped) == (2, 1)
    assert report.unmapped == (ids[1],)
    assert report.stale is None  # not guessed: Zotero could not be asked
    assert report.unreachable is not None and "API key" in report.unreachable


def test_status_degrades_on_any_zotero_error_not_only_an_unreachable_one(tmp_path: Path) -> None:
    repo, ids = review_with(tmp_path, CEPEDA, ONLY_HERE)
    _link(repo, FakeZotero("7"))
    rejected = FakeZotero("6")  # no local API, so the Web API, which refuses the wrong key

    report = zotero_ops.status(
        repo, connector=connector_for(rejected, key="NOT-THE-RIGHT-KEY-AT-ALL")
    )

    assert (report.records, report.mapped) == (2, 1)
    assert report.stale is None
    assert report.unreachable is not None and "API key" in report.unreachable


def test_status_follows_a_link_to_a_record_that_was_merged_into_another(tmp_path: Path) -> None:
    repo, ids = review_with(tmp_path, CEPEDA, ONLY_HERE)
    _link(repo, FakeZotero("7"))  # links the Cepeda record
    cepeda, kept = records_mod.read_records(repo)
    # `strata dedup` later decides Cepeda's record is a duplicate of the other and absorbs it
    kept["strata"] = {**kept["strata"], "absorbed": [cepeda["id"]]}
    cepeda["strata"] = {**cepeda["strata"], "canonical": False}
    records_mod.write_records(repo, [cepeda, kept])

    report = zotero_ops.status(repo, connector=connector_for(FakeZotero("7")))

    assert report.records == 1 and report.mapped == 1  # the link now serves the record that remains
    assert report.unmapped == () and report.orphaned == ()


# ---------------------------------------------------------------------------------------- open


def test_open_goes_to_the_pdf_when_there_is_one_and_the_item_when_there_is_not(
    tmp_path: Path,
) -> None:
    repo, ids = review_with(tmp_path, CEPEDA, SMITH)
    fake = FakeZotero("7")
    _link(repo, fake)

    pdf = zotero_ops.open_target(repo, ids[0], connector=connector_for(fake))
    item = zotero_ops.open_target(repo, ids[1], connector=connector_for(fake))

    assert (pdf.kind, pdf.uri) == ("attachment", "zotero://open-pdf/library/items/PDF1AAAA")
    assert (item.kind, item.uri) == ("item", "zotero://select/library/items/JK6L7MNP")


def test_open_says_when_a_record_is_not_in_zotero(tmp_path: Path) -> None:
    repo, ids = review_with(tmp_path, CEPEDA, ONLY_HERE)
    fake = FakeZotero("7")
    _link(repo, fake)

    with pytest.raises(zotero_ops.NotLinkedError, match="is not linked to a Zotero item"):
        zotero_ops.open_target(repo, ids[1], connector=connector_for(fake))


def test_open_on_a_deleted_item_says_the_full_text_is_unavailable(tmp_path: Path) -> None:
    repo, ids = review_with(tmp_path, CEPEDA)
    fake = FakeZotero("7")
    _link(repo, fake)
    fake.delete_item(LIB, "AB3D9XYZ")

    with pytest.raises(zotero_ops.StaleLinkError, match="full text unavailable"):
        zotero_ops.open_target(repo, ids[0], connector=connector_for(fake))
