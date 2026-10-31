"""`strata zotero ...` and the Zotero hooks in `retrieve` and `screen`, through the real CLI against
a real review and a fake Zotero (openspec:zotero-integration)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from strata import gitio
from strata.cli.main import (
    EXIT_CONFLICT,
    EXIT_GENERIC,
    EXIT_OK,
    EXIT_RATIONALE_REFUSED,
    EXIT_USAGE,
    EXIT_VALIDATION,
    app,
)
from strata.core import fulltext
from strata.integrations.zotero import connect as zotero_connect
from strata.integrations.zotero import credentials
from tests.integration._zotero import CEPEDA, ONLY_HERE, ROEDIGER, SMITH, review_with
from tests.unit._m3 import decide
from tests.unit._zotero import MemoryKeystore
from tests.zotero_fake import API_KEY, FakeZotero

runner = CliRunner()
WHY = "linking this review to the team's shared Zotero library"
LIB = "users/12345"


def _text(result: Any) -> str:
    """What a command printed, with the terminal's line wrapping undone."""
    return " ".join(str(result.output).split())


def _install(
    monkeypatch: pytest.MonkeyPatch,
    fake: FakeZotero,
    *,
    keychain: bool = True,
    key: str | None = API_KEY,
    environ: dict[str, str] | None = None,
) -> MemoryKeystore:
    """Route every Zotero request of the CLI to `fake`, with a keychain (or none)."""
    store = MemoryKeystore(available_=keychain, secret=key if keychain else None)
    monkeypatch.setattr(zotero_connect, "make_http_transport", lambda: fake)
    monkeypatch.setattr(credentials, "KeyringStore", lambda: store)
    monkeypatch.delenv(credentials.ENV_VAR, raising=False)
    for name, value in (environ or {}).items():
        monkeypatch.setenv(name, value)
    return store


def _run(root: Path, *args: str, why: str | None = WHY, input: str | None = None):  # type: ignore[no-untyped-def]
    prefix = ["--why", why] if why else []
    return runner.invoke(app, [*prefix, "-C", str(root), *args], input=input)


def _linked(root: Path, *extra: str):  # type: ignore[no-untyped-def]
    result = _run(root, "zotero", "link", "--by", "ethan", "--library", LIB, *extra)
    assert result.exit_code == EXIT_OK, result.output
    return result


# --------------------------------------------------------------------------------------- link


def test_link_over_the_local_api_says_what_it_matched_and_what_it_did_not(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, _ = review_with(tmp_path, CEPEDA, ROEDIGER, SMITH, ONLY_HERE)
    _install(monkeypatch, FakeZotero("7"), keychain=False, key=None)

    result = _run(repo.root, "zotero", "link", "--by", "ethan", "--library", LIB)

    assert result.exit_code == EXIT_OK, result.output
    assert "linked users/12345 through the local API" in _text(result)
    assert "linked read-only through the local API" in _text(result)
    assert "matched 3 of 4 library items" in _text(result)
    assert "not in this review: QR8S2TUV" in _text(result)
    assert "Strata-Op: zotero-link" in gitio.run(["log", "-1", "--format=%B"], cwd=repo.root).stdout


def test_link_as_json_is_machine_readable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo, _ = review_with(tmp_path, CEPEDA, ONLY_HERE)
    _install(monkeypatch, FakeZotero("7"))

    result = runner.invoke(
        app,
        ["--json", "--why", WHY, "-C", str(repo.root), "zotero", "link", "--by", "ethan",
         "--library", LIB],
    )  # fmt: skip

    assert result.exit_code == EXIT_OK, result.output
    payload = json.loads(result.stdout)
    assert payload["library"] == LIB and payload["transport"] == "local"
    assert payload["matched"] == 1 and payload["unmatched"] == ["CD4E5FGH", "JK6L7MNP", "QR8S2TUV"]
    assert payload["write"] is False and payload["committed"] is True


def test_link_with_a_key_only_in_the_environment_says_it_is_not_being_kept(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, _ = review_with(tmp_path, CEPEDA)
    _install(
        monkeypatch,
        FakeZotero("6"),  # no local API: the Web API, and so a key, is needed
        keychain=False,
        key=None,
        environ={credentials.ENV_VAR: API_KEY},
    )

    result = _run(repo.root, "zotero", "link", "--by", "ethan", "--library", LIB)

    assert result.exit_code == EXIT_OK, result.output
    assert "not being stored anywhere" in _text(result)
    assert "using the Web API" in _text(result)
    for path in repo.root.rglob("*"):
        if path.is_file() and ".git/" not in path.as_posix():
            assert API_KEY.encode() not in path.read_bytes(), path


def test_link_with_no_key_anywhere_says_how_to_provide_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, _ = review_with(tmp_path, CEPEDA)
    _install(monkeypatch, FakeZotero("6"), keychain=False, key=None)

    result = _run(repo.root, "zotero", "link", "--by", "ethan", "--library", LIB)

    assert result.exit_code == EXIT_GENERIC
    assert credentials.ENV_VAR in _text(result) and "no Zotero API key" in _text(result)


def test_link_with_a_choice_of_libraries_and_no_terminal_lists_them(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, _ = review_with(tmp_path, CEPEDA)
    _install(monkeypatch, FakeZotero("7"))

    result = _run(repo.root, "zotero", "link", "--by", "ethan")

    assert result.exit_code == EXIT_USAGE
    assert "users/12345 (My Library)" in _text(result) and "groups/777" in _text(result)


def test_link_without_a_rationale_is_refused_and_writes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, _ = review_with(tmp_path, CEPEDA)
    _install(monkeypatch, FakeZotero("7"))

    result = _run(repo.root, "zotero", "link", "--by", "ethan", "--library", LIB, why=None)

    assert result.exit_code == EXIT_RATIONALE_REFUSED
    assert "rationale is required" in _text(result)
    assert not (repo.root / "integrations").exists()


def test_every_zotero_command_refuses_a_review_that_is_not_linked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, ids = review_with(tmp_path, CEPEDA)
    _install(monkeypatch, FakeZotero("7"))

    for args in (
        ["zotero", "status"],
        ["zotero", "open", ids[0]],
        ["zotero", "pull", "--collection", "x", "--by", "ethan", "--via", "website"],
        ["zotero", "push", "--collection", "x", "--by", "ethan"],
    ):
        result = _run(repo.root, *args)
        assert result.exit_code == EXIT_USAGE, (args, result.output)
        assert "not linked" in _text(result) or "not linked to a Zotero" in _text(result)


# ---------------------------------------------------------------------------------------- pull


def test_pull_a_hand_built_collection_reports_what_it_brought_in(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, _ = review_with(tmp_path)
    _install(monkeypatch, FakeZotero("7"))
    _linked(repo.root)

    result = _run(
        repo.root, "zotero", "pull", "--collection", "Hand-searched trials", "--by", "ethan",
        "--via", "website",
    )  # fmt: skip

    assert result.exit_code == EXIT_OK, result.output
    assert "pulled 3 items from 'Hand-searched trials'" in _text(result)
    assert "3 new records" in _text(result)
    message = gitio.run(["log", "-1", "--format=%B"], cwd=repo.root).stdout
    assert "Strata-Op: zotero-pull" in message and "Strata-Collection: HANDPICK" in message


def test_a_review_that_has_been_linked_and_pulled_still_verifies_clean(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, ids = review_with(tmp_path, CEPEDA)
    fake = FakeZotero("7")
    _install(monkeypatch, fake)
    _linked(repo.root)
    fake.edit_item(LIB, "AB3D9XYZ", title="Spacing effects in learning: a corrected title")
    pulled = _run(
        repo.root, "zotero", "pull", "--collection", "Hand-searched trials", "--by", "ethan",
        "--via", "website",
    )  # fmt: skip
    assert pulled.exit_code == EXIT_OK, pulled.output

    verified = _run(repo.root, "verify")

    assert verified.exit_code == EXIT_OK, verified.output
    assert gitio.run(["status", "--porcelain"], cwd=repo.root).stdout == ""  # all of it committed


def test_pull_without_a_search_or_a_via_is_a_usage_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, _ = review_with(tmp_path)
    _install(monkeypatch, FakeZotero("7"))
    _linked(repo.root)

    result = _run(
        repo.root, "zotero", "pull", "--collection", "Hand-searched trials", "--by", "ethan"
    )

    assert result.exit_code == EXIT_USAGE
    assert "exactly one of --search or --via" in _text(result)


def test_pull_shows_what_zotero_corrected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo, ids = review_with(tmp_path, CEPEDA)
    fake = FakeZotero("7")
    _install(monkeypatch, fake)
    _linked(repo.root)
    fake.edit_item(LIB, "AB3D9XYZ", title="Spacing effects in learning: a corrected title")

    result = _run(
        repo.root, "zotero", "pull", "--collection", "Hand-searched trials", "--by", "ethan",
        "--via", "website",
    )  # fmt: skip

    assert result.exit_code == EXIT_OK, result.output
    assert f"corrected {ids[0]} title:" in _text(result)
    assert "a corrected title" in _text(result)


def test_pull_as_json(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo, _ = review_with(tmp_path)
    _install(monkeypatch, FakeZotero("7"))
    _linked(repo.root)

    result = runner.invoke(
        app,
        ["--json", "--why", WHY, "-C", str(repo.root), "zotero", "pull", "--collection",
         "Hand-searched trials", "--by", "ethan", "--via", "website"],
    )  # fmt: skip

    payload = json.loads(result.stdout)
    assert payload["items"] == 3 and payload["records_created"] == 3
    assert payload["import"].startswith("imp_") and payload["committed"] is True


# ---------------------------------------------------------------------------------------- push


def _web_linked(root: Path) -> None:
    _linked(root, "--web")


def test_push_reports_what_it_created_added_and_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, ids = review_with(tmp_path, CEPEDA, SMITH, ONLY_HERE)
    decide(repo, "title-abstract", ids)
    decide(repo, "full-text", ids)
    fake = FakeZotero("7")
    _install(monkeypatch, fake)
    _web_linked(repo.root)
    fake.edit_item(LIB, "JK6L7MNP", title="Spacing effects in a classroom: a quasi-experiment!")

    result = _run(repo.root, "zotero", "push", "--collection", "Included studies", "--by", "ethan")

    assert result.exit_code == EXIT_CONFLICT, result.output  # one item was refused
    assert "1 created, 1 added, 0 already there" in _text(result)
    assert f"refused {ids[1]}" in _text(result) and "pull it" in _text(result)
    assert {r.method for r in fake.requests} <= {"GET", "POST"}


def test_push_over_a_read_only_link_says_how_to_make_it_writable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, ids = review_with(tmp_path, CEPEDA)
    decide(repo, "title-abstract", ids)
    decide(repo, "full-text", ids)
    _install(monkeypatch, FakeZotero("7"))
    _linked(repo.root)

    result = _run(repo.root, "zotero", "push", "--collection", "Included studies", "--by", "ethan")

    assert result.exit_code == EXIT_USAGE
    assert "strata zotero link --web" in _text(result)


# ----------------------------------------------------------------------------- status and open


def test_status_lists_stale_links_and_unmapped_records(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, ids = review_with(tmp_path, CEPEDA, ROEDIGER, ONLY_HERE)
    fake = FakeZotero("7")
    _install(monkeypatch, fake)
    _linked(repo.root)
    fake.delete_item(LIB, "CD4E5FGH")

    result = _run(repo.root, "zotero", "status")

    assert result.exit_code == EXIT_OK, result.output
    assert "2 of 3 records mapped" in _text(result)
    assert "1 not mapped" in _text(result)
    assert f"{ids[1]} item CD4E5FGH (full text unavailable)" in _text(result)

    as_json = runner.invoke(app, ["--json", "-C", str(repo.root), "zotero", "status"])
    payload = json.loads(as_json.stdout)
    assert payload["mapped"] == 2 and payload["stale"] == [{"record": ids[1], "item": "CD4E5FGH"}]


def test_open_prints_the_link_and_launches_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, ids = review_with(tmp_path, CEPEDA)
    _install(monkeypatch, FakeZotero("7"))
    _linked(repo.root)
    launched: list[str] = []
    monkeypatch.setattr("webbrowser.open", lambda url: launched.append(url) or True)

    printed = _run(repo.root, "zotero", "open", ids[0][:12], "--print-only")
    opened = _run(repo.root, "zotero", "open", ids[0])

    assert printed.exit_code == opened.exit_code == EXIT_OK
    assert "zotero://open-pdf/library/items/PDF1AAAA" in _text(printed)
    assert launched == ["zotero://open-pdf/library/items/PDF1AAAA"]  # only the second launched it


def test_open_on_a_record_with_no_item_or_a_deleted_one_says_why(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, ids = review_with(tmp_path, CEPEDA, ONLY_HERE)
    fake = FakeZotero("7")
    _install(monkeypatch, fake)
    _linked(repo.root)

    not_in_zotero = _run(repo.root, "zotero", "open", ids[1])
    fake.delete_item(LIB, "AB3D9XYZ")
    deleted = _run(repo.root, "zotero", "open", ids[0])

    assert not_in_zotero.exit_code == deleted.exit_code == EXIT_USAGE
    assert "is not linked to a Zotero item" in _text(not_in_zotero)
    assert "full text unavailable" in _text(deleted)


# ------------------------------------------------------------------------------------ retrieval


def _sought(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake: FakeZotero):  # type: ignore[no-untyped-def]
    """A linked review whose two records both passed title/abstract screening."""
    repo, ids = review_with(tmp_path, CEPEDA, SMITH)
    decide(repo, "title-abstract", ids)
    _install(monkeypatch, fake)
    _linked(repo.root)
    return repo, ids


def test_the_retrieval_queue_shows_which_reports_have_an_attachment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, _ = _sought(tmp_path, monkeypatch, FakeZotero("7"))

    listed = _run(repo.root, "retrieve", "--by", "ethan", "--list")
    as_json = runner.invoke(app, ["--json", "-C", str(repo.root), "retrieve", "--by", "ethan"])

    assert listed.exit_code == EXIT_OK, listed.output
    assert "2 reports sought. 2 outstanding. Zotero: 1 attachments found." in _text(listed)
    assert "[Zotero: pdf]" in _text(listed) and "[Zotero: none]" in _text(listed)
    payload = json.loads(as_json.stdout)
    assert payload["zotero_attachments_found"] == 1
    states = {r["record"]: r["zotero"] for r in payload["reports"]}
    assert sorted(s["state"] for s in states.values()) == ["none", "pdf"]


def test_the_queue_offers_to_open_a_pdf_in_zotero_and_records_the_item_key_not_a_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, ids = _sought(tmp_path, monkeypatch, FakeZotero("7"))
    launched: list[str] = []
    monkeypatch.setattr("webbrowser.open", lambda url: launched.append(url) or True)

    # report 1 has a PDF: open it, then record it as retrieved from Zotero (default version);
    # report 2 has none: skip it
    result = _run(repo.root, "retrieve", "--by", "ethan", input="o\nz\n\ns\n")

    assert result.exit_code == EXIT_OK, result.output
    assert "Zotero: PDF attachment present" in _text(result)
    assert "[o] open in Zotero" in _text(result)
    assert launched == ["zotero://open-pdf/library/items/PDF1AAAA"]
    (entry,) = fulltext.read_manifest(repo)
    assert entry["locator"] == {"doi": CEPEDA["DOI"].lower()}  # the DOI ...
    assert entry["zotero"] == {"library": LIB, "item_key": "AB3D9XYZ"}  # ... and the item key
    assert entry["source"] == "zotero" and "path" not in entry
    assert entry["version"] == "version-of-record"


def test_a_report_with_no_attachment_is_not_offered_zotero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, _ = _sought(tmp_path, monkeypatch, FakeZotero("7"))

    result = _run(repo.root, "retrieve", "--by", "ethan", input="s\ns\n")

    assert _text(result).count("[o] open in Zotero") == 1  # only the report that has a PDF
    assert "Zotero: in the library, no file attached" in _text(result)


def test_retrieved_from_zotero_non_interactively_records_the_item(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, ids = _sought(tmp_path, monkeypatch, FakeZotero("7"))
    report = "rpt_" + ids[0][len("rec_") :]

    result = _run(
        repo.root, "retrieve", "--by", "ethan", "--report", report, "--outcome", "retrieved",
        "--version", "accepted-manuscript", "--zotero",
    )  # fmt: skip

    assert result.exit_code == EXIT_OK, result.output
    (entry,) = fulltext.read_manifest(repo)
    assert entry["zotero"] == {"library": LIB, "item_key": "AB3D9XYZ"}
    assert entry["source"] == "zotero" and entry["version"] == "accepted-manuscript"


def test_retrieved_from_zotero_is_refused_when_zotero_has_no_attachment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, ids = _sought(tmp_path, monkeypatch, FakeZotero("7"))
    report = "rpt_" + ids[1][len("rec_") :]

    result = _run(
        repo.root, "retrieve", "--by", "ethan", "--report", report, "--outcome", "retrieved",
        "--zotero",
    )  # fmt: skip

    assert result.exit_code == EXIT_USAGE
    assert "no attachment" in _text(result)
    assert fulltext.read_manifest(repo) == []


def test_the_queue_carries_on_when_zotero_cannot_be_reached(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, _ = _sought(tmp_path, monkeypatch, FakeZotero("7"))
    _install(monkeypatch, FakeZotero("7", local_running=False), keychain=False, key=None)

    result = _run(repo.root, "retrieve", "--by", "ethan", "--list")

    assert result.exit_code == EXIT_OK, result.output
    assert "2 reports sought. 2 outstanding. Zotero: not reachable." in _text(result)
    assert "carrying on without it" in _text(result)


# --------------------------------------------------------------------------------- screening


def _full_text_ready(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake: FakeZotero):  # type: ignore[no-untyped-def]
    repo, ids = review_with(tmp_path, CEPEDA)
    decide(repo, "title-abstract", ids)
    _install(monkeypatch, fake)
    _linked(repo.root)
    return repo, ids


def test_full_text_screening_shows_where_the_full_text_is_in_zotero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, ids = _full_text_ready(tmp_path, monkeypatch, FakeZotero("7"))

    result = _run(repo.root, "screen", "full-text", "--by", "ethan", input="i\n\n")

    assert result.exit_code == EXIT_OK, result.output
    assert "Full text: PDF attachment present in Zotero" in _text(result)
    assert f"strata zotero open {ids[0]}" in _text(result)


def test_screening_proceeds_when_the_zotero_item_was_deleted_and_says_the_full_text_is_unavailable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = FakeZotero("7")
    repo, ids = _full_text_ready(tmp_path, monkeypatch, fake)
    fake.delete_item(LIB, "AB3D9XYZ")

    result = _run(repo.root, "screen", "full-text", "--by", "ethan", input="i\n\n")

    assert result.exit_code == EXIT_OK, result.output
    assert "Full text unavailable" in _text(result)
    assert "1 decision(s) recorded" in _text(result)  # the decision was made all the same


def test_screening_proceeds_when_zotero_is_not_running(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, ids = _full_text_ready(tmp_path, monkeypatch, FakeZotero("7"))
    _install(monkeypatch, FakeZotero("7", local_running=False), keychain=False, key=None)

    result = _run(repo.root, "screen", "full-text", "--by", "ethan", input="i\n\n")

    assert result.exit_code == EXIT_OK, result.output
    assert "screening carries on without it" in _text(result)
    assert "1 decision(s) recorded" in _text(result)


def test_title_abstract_screening_never_asks_zotero_anything(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = FakeZotero("7")
    repo, _ = review_with(tmp_path, CEPEDA)
    _install(monkeypatch, fake)
    _linked(repo.root)
    asked_before = len(fake.requests)

    result = _run(repo.root, "screen", "title-abstract", "--by", "ethan", input="i\n\n")

    assert result.exit_code == EXIT_OK, result.output
    assert len(fake.requests) == asked_before
    assert "Full text" not in _text(result)


# --------------------------------------------------------------------- Zotero absent entirely


def test_every_core_workflow_runs_with_zotero_absent_and_never_mentions_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """openspec:zotero-integration#optional-and-isolated: screen, extract and analyse without
    Zotero installed, and nothing fails or warns because it is missing."""

    def forbidden(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("a core workflow reached for Zotero or the keychain")

    monkeypatch.setattr(zotero_connect, "make_http_transport", forbidden)
    monkeypatch.setattr(credentials, "KeyringStore", forbidden)
    repo, ids = review_with(tmp_path, CEPEDA, ROEDIGER, SMITH)
    decide(repo, "title-abstract", ids)
    decide(repo, "full-text", ids[:2], actors=("ethan", "sam"))
    report = "rpt_" + ids[0][len("rec_") :]

    steps: list[tuple[str, ...]] = [
        ("status",),
        ("records", "list"),
        ("verify",),
        ("retrieve", "--by", "ethan", "--list"),
        ("retrieve", "--by", "ethan", "--report", report, "--outcome", "retrieved",
         "--source", "institutional-access", "--version", "version-of-record"),
        ("screen", "full-text", "--by", "ethan"),
        ("studies", "--by", "ethan", "--list"),
        ("prisma", "--by", "ethan"),
    ]  # fmt: skip
    outputs: list[str] = []
    for step in steps:
        result = _run(repo.root, *step, input="q\n")
        assert result.exit_code in (EXIT_OK, EXIT_USAGE), (step, result.output)
        outputs.append(result.output.lower())

    assert not any("zotero" in output for output in outputs)
    assert not any("keychain" in output or "api key" in output for output in outputs)


def test_an_api_key_in_strata_toml_is_reported_by_verify(tmp_path: Path) -> None:
    repo, _ = review_with(tmp_path, CEPEDA)
    manifest = repo.root / "strata.toml"
    manifest.write_text(
        manifest.read_text(encoding="utf-8")
        + '\n[zotero]\nlibrary = "users/12345"\napi_key = "SECRET"\n',
        encoding="utf-8",
    )

    result = _run(repo.root, "verify")

    assert result.exit_code == EXIT_VALIDATION, result.output
    assert "E_SCHEMA" in _text(result) and "api_key" in _text(result)


def test_no_zotero_command_is_needed_for_a_review_to_verify(tmp_path: Path) -> None:
    repo, _ = review_with(tmp_path, CEPEDA)

    result = _run(repo.root, "verify")

    assert result.exit_code == EXIT_OK, result.output
