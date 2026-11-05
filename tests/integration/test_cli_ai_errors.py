"""The CLI's refusals and machine-readable output for the AI commands: a busy repository lock, an
upgrade or setting the operation refuses, a suggestion that cannot be resolved, and `--json`.

openspec:cli#ai-participation-commands, openspec:ai-participation#the-ai-ledger-and-audit."""

from __future__ import annotations

import json
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any, NoReturn

import pytest
from typer.testing import CliRunner

from strata.cli import main as cli_main
from strata.cli.main import EXIT_CONFLICT, EXIT_GENERIC, EXIT_OK, EXIT_USAGE, app
from strata.core import agent_ops as agent_ops_mod
from strata.core import ledger as ledger_mod
from strata.core import migrate as migrate_mod
from strata.core import operations as ops_mod
from strata.core.manifest import ConfigError, load_manifest_doc, write_manifest
from strata.core.repo import LockTimeoutError, Repo, open_repo
from strata.protocol import suggestions as sugg
from tests.unit._m3 import decide
from tests.unit._m6 import STAGE, context, suggest_screen, suggest_world

runner = CliRunner()
WHY = "Agree: the abstract meets the population criterion."


@pytest.fixture(scope="module")
def template(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, list[str]]:
    repo, ids = suggest_world(tmp_path_factory.mktemp("template"))
    return repo.root, ids


@pytest.fixture
def world(template: tuple[Path, list[str]], tmp_path: Path) -> tuple[Repo, list[str]]:
    source, ids = template
    target = tmp_path / "review"
    shutil.copytree(source, target)
    return open_repo(target), ids


def _run(root: Path, *args: str, why: str | None = WHY, expect: int = EXIT_OK) -> str:
    prefix = ["-C", str(root)] + (["--why", why] if why else [])
    result = runner.invoke(app, [*prefix, *args])
    assert result.exit_code == expect, result.output
    return " ".join(result.output.split())


def _busy(*_args: Any, **_kwargs: Any) -> NoReturn:
    raise LockTimeoutError("the review is being changed by process 4242; try again in a moment")


def _raising(exc: Exception) -> Callable[..., NoReturn]:
    def raise_it(*_args: Any, **_kwargs: Any) -> NoReturn:
        raise exc

    return raise_it


def _open_up(repo: Repo) -> Repo:
    doc = load_manifest_doc(repo.root)
    doc["ai"]["show_suggestions"] = "always"
    write_manifest(repo.root, doc)
    return open_repo(repo.root)


# ---------------------------------------------------------------------- upgrade, enable, policy


def _format_one(tmp_path: Path) -> Path:
    root = tmp_path / "old"
    result = runner.invoke(
        app, ["init", str(root), "--title", "T", "--actor", "ethan", "--actor-name", "Ethan"]
    )
    assert result.exit_code == EXIT_OK, result.output
    return root


def test_a_migration_the_operation_refuses_is_a_usage_error_with_its_reason(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _format_one(tmp_path)
    monkeypatch.setattr(
        ops_mod,
        "migrate_repository",
        _raising(migrate_mod.MigrationError("the working tree has uncommitted changes")),
    )
    out = _run(root, "migrate", expect=EXIT_USAGE)
    assert "uncommitted changes" in out


def test_a_migration_waiting_on_a_busy_lock_says_so_and_changes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _format_one(tmp_path)
    monkeypatch.setattr(ops_mod, "migrate_repository", _busy)
    assert "process 4242" in _run(root, "migrate", expect=EXIT_GENERIC)


@pytest.mark.parametrize(
    "problem",
    [migrate_mod.MigrationError("not a clean tree"), ConfigError(["the manifest is unreadable"])],
)
def test_enabling_ai_reports_what_stopped_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, problem: Exception
) -> None:
    root = _format_one(tmp_path)
    monkeypatch.setattr(ops_mod, "enable_ai", _raising(problem))
    assert str(problem) in _run(root, "ai", "enable", expect=EXIT_USAGE)


def test_enabling_ai_waiting_on_a_busy_lock_says_so(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _format_one(tmp_path)
    monkeypatch.setattr(ops_mod, "enable_ai", _busy)
    assert "process 4242" in _run(root, "ai", "enable", expect=EXIT_GENERIC)


def test_setting_a_mode_waiting_on_a_busy_lock_says_so(
    world: tuple[Repo, list[str]], monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, _ = world
    monkeypatch.setattr(ops_mod, "set_ai_policy", _busy)
    assert "process 4242" in _run(
        repo.root, "ai", "policy", "dedup", "suggest", expect=EXIT_GENERIC
    )


# ------------------------------------------------------------------------------- suggestions


def test_adopting_while_the_review_is_busy_says_so_and_adopts_nothing(
    world: tuple[Repo, list[str]], monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, ids = world
    repo = _open_up(repo)
    item = suggest_screen(repo, ids[0])
    monkeypatch.setattr(agent_ops_mod, "adopt", _busy)
    out = _run(repo.root, "suggestions", "adopt", item["id"], "--by", "sam", expect=EXIT_GENERIC)
    assert "process 4242" in out
    assert sugg.get_suggestion(repo, item["id"]).status == sugg.PENDING


def test_adopting_after_the_review_moved_on_is_a_conflict_until_confirmed(
    world: tuple[Repo, list[str]],
) -> None:
    repo, ids = world
    repo = _open_up(repo)
    item = suggest_screen(repo, ids[0])
    _run(
        repo.root, "criteria", "add", "--kind", "exclusion", "--label", "Wrong setting",
        "--definition", "Not in schools.", "--applies-at", STAGE, "--by", "ethan",
        why="The protocol needs one for setting.",
    )  # fmt: skip
    out = _run(repo.root, "suggestions", "adopt", item["id"], "--by", "sam", expect=EXIT_CONFLICT)
    assert "Look again, then confirm" in out
    assert sugg.get_suggestion(repo, item["id"]).status == sugg.PENDING
    _run(repo.root, "suggestions", "adopt", item["id"], "--by", "sam", "--confirm")
    assert sugg.get_suggestion(repo, item["id"]).status == sugg.ADOPTED


def test_rejecting_twice_is_a_usage_error_naming_what_became_of_it(
    world: tuple[Repo, list[str]],
) -> None:
    repo, ids = world
    repo = _open_up(repo)
    item = suggest_screen(repo, ids[0])
    _run(
        repo.root,
        "suggestions",
        "reject",
        item["id"],
        "--by",
        "sam",
        why="Not convinced by this one.",
    )
    out = _run(
        repo.root, "suggestions", "reject", item["id"], "--by", "sam", why="Still not convinced.",
        expect=EXIT_USAGE,
    )  # fmt: skip
    assert "already rejected" in out


def test_rejecting_while_the_review_is_busy_says_so(
    world: tuple[Repo, list[str]], monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, ids = world
    repo = _open_up(repo)
    item = suggest_screen(repo, ids[0])
    monkeypatch.setattr(agent_ops_mod, "reject", _busy)
    out = _run(
        repo.root,
        "suggestions", "reject", item["id"], "--by", "sam",
        why="Not convinced either way.",
        expect=EXIT_GENERIC,
    )  # fmt: skip
    assert "process 4242" in out


def test_rejecting_prints_the_resolved_suggestion_as_json(world: tuple[Repo, list[str]]) -> None:
    repo, ids = world
    repo = _open_up(repo)
    item = suggest_screen(repo, ids[0])
    out = _run(
        repo.root, "--json", "suggestions", "reject", item["id"], "--by", "sam",
        why="Not convinced by this one.",
    )  # fmt: skip
    payload = json.loads(out)
    assert payload["id"] == item["id"] and payload["status"] == "rejected"
    assert payload["resolution"]["reason"] == "Not convinced by this one."


def test_adopting_prints_the_events_it_wrote_as_json(world: tuple[Repo, list[str]]) -> None:
    repo, ids = world
    repo = _open_up(repo)
    item = suggest_screen(repo, ids[0])
    payload = json.loads(
        _run(repo.root, "--json", "suggestions", "adopt", item["id"], "--by", "sam")
    )
    assert payload["suggestion"] == item["id"] and payload["by"] == "sam"
    assert len(payload["events"]) == 1


def test_a_criteria_suggestion_lists_what_it_would_make_stale(
    world: tuple[Repo, list[str]],
) -> None:
    repo, ids = world
    repo = _open_up(repo)
    decide(repo, STAGE, ids[:2], "include", actors=("ethan",))
    sugg.make_suggestion(
        repo,
        context=context(),
        op="criteria-retire",
        args={"criterion": "EXC-01"},
        rationale="It duplicates EXC-02.",
    )
    (item,) = json.loads(_run(repo.root, "--json", "suggestions", "list"))
    assert item["op"] == "criteria-retire"
    assert set(item["preview"]) == {"stale_decisions", "by_stage"}
    assert "record" not in item and "stage" not in item


def test_list_all_under_blinding_hides_the_blinded_but_keeps_what_was_resolved(
    world: tuple[Repo, list[str]],
) -> None:
    repo, ids = world
    repo = _open_up(repo)
    resolved = suggest_screen(repo, ids[0])
    _run(
        repo.root,
        "suggestions",
        "reject",
        resolved["id"],
        "--by",
        "sam",
        why="Not convinced by this one.",
    )
    doc = load_manifest_doc(repo.root)
    doc["ai"]["show_suggestions"] = "after-own-decision"
    write_manifest(repo.root, doc)
    repo = open_repo(repo.root)
    waiting = suggest_screen(repo, ids[1])
    listed = {
        s["id"]: s["status"]
        for s in json.loads(_run(repo.root, "--json", "suggestions", "list", "--all"))
    }
    assert listed == {resolved["id"]: "rejected"}
    assert waiting["id"] not in listed
    decide(repo, STAGE, ids[1:2], "include", actors=("ethan",))
    shown = {
        s["id"]
        for s in json.loads(
            _run(repo.root, "--json", "suggestions", "list", "--all", "--by", "ethan")
        )
    }
    assert shown == {resolved["id"], waiting["id"]}


# ------------------------------------------------------------------------- revoke, report, mcp


def test_revoking_prints_what_it_marked_as_json(world: tuple[Repo, list[str]]) -> None:
    repo, ids = world
    decide(repo, STAGE, ids[:1], "include", actors=("sam",))
    payload = json.loads(
        _run(
            repo.root,
            "--json",
            "ai",
            "revoke",
            "claude-opus",
            "--by",
            "ethan",
            why="The agent is retired.",
        )
    )
    assert payload["agent"] == "claude-opus" and payload["committed"] is True
    assert isinstance(payload["marked_stale"], int)


def test_revoking_while_the_review_is_busy_says_so(
    world: tuple[Repo, list[str]], monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, _ = world
    monkeypatch.setattr(ops_mod, "revoke_agent", _busy)
    out = _run(repo.root, "ai", "revoke", "claude-opus", "--by", "ethan", expect=EXIT_GENERIC)
    assert "process 4242" in out


def test_the_ledger_line_counts_work_that_wrote_files_not_events() -> None:
    line = cli_main._kind_line("analysis", ledger_mod.KindLedger(file_work=3))
    assert "3 piece(s) of work committed" in line
    assert "suggested" not in line and "counted" not in line


def test_the_mcp_server_will_not_start_for_a_person_who_is_not_in_the_review(
    world: tuple[Repo, list[str]],
) -> None:
    repo, _ = world
    out = _run(repo.root, "mcp", "--as", "nobody", expect=EXIT_USAGE)
    assert "nobody" in out
