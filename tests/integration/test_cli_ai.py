"""`strata migrate`, `strata ai enable|policy` and `strata actor add --kind agent`:
openspec:repository-format#format-versioning, openspec:ai-participation, openspec:cli."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from strata import gitio
from strata.cli.main import EXIT_OK, EXIT_RATIONALE_REFUSED, EXIT_USAGE, app

runner = CliRunner()
WHY = "Piloting AI suggestions on screening, as agreed in the protocol."
KINDS = [
    "screening", "extraction", "risk-of-bias", "retrieval", "studies", "dedup", "records",
    "search-import", "criteria", "adjudication", "analysis",
]  # fmt: skip


def _init(tmp_path: Path) -> Path:
    root = tmp_path / "review"
    result = runner.invoke(
        app, ["init", str(root), "--title", "T", "--actor", "ethan", "--actor-name", "Ethan"]
    )
    assert result.exit_code == EXIT_OK, result.output
    return root


class _Out:
    """A command's output with Rich's line-wrapping undone, so a phrase is found where it broke."""

    def __init__(self, raw: object) -> None:
        self.output = " ".join(str(getattr(raw, "output", "")).split())


def _run(root: Path, *args: str, why: str | None = WHY, expect: int = EXIT_OK) -> _Out:
    prefix = ["-C", str(root)] + (["--why", why] if why else [])
    result = runner.invoke(app, [*prefix, *args])
    assert result.exit_code == expect, result.output
    return _Out(result)


def _commits(root: Path) -> list[str]:
    return gitio.log(root, fmt="%H")


def _last_message(root: Path) -> str:
    return gitio.commit_message(root, "HEAD")


def _enabled(tmp_path: Path) -> Path:
    root = _init(tmp_path)
    _run(root, "ai", "enable")
    return root


# ------------------------------------------------------------------------------ strata migrate


def test_a_version_1_repository_runs_every_command_unchanged_and_status_offers_format_2(
    tmp_path: Path,
) -> None:
    root = _init(tmp_path)
    before = _commits(root)
    status = _run(root, "status", why=None)
    assert "format 1; format 2 is available" in status.output
    assert "strata migrate" in status.output
    _run(root, "verify", why=None)
    _run(root, "actor", "list", why=None)
    assert _commits(root) == before
    assert gitio.run(["status", "--porcelain"], cwd=root).stdout == ""  # not modified
    assert (root / ".strata" / "schema-version").read_text() == "1\n"


def test_status_json_carries_the_format(tmp_path: Path) -> None:
    root = _init(tmp_path)
    payload = json.loads(_run(root, "--json", "status", why=None).output)
    assert (payload["schema_version"], payload["migration_available"]) == (1, True)


def test_migrate_upgrades_in_one_commit_with_the_rationale(tmp_path: Path) -> None:
    root = _init(tmp_path)
    before = _commits(root)
    result = _run(root, "migrate")
    assert "migrated" in result.output
    assert len(_commits(root)) == len(before) + 1
    assert (root / ".strata" / "schema-version").read_text() == "2\n"
    message = _last_message(root)
    assert message.startswith("migrate: upgrade to format 2")
    assert WHY in message
    assert "Strata-Op: migrate" in message
    assert "Strata-Schema-Version: 2" in message
    assert "Strata-Schema-From: 1" in message
    assert gitio.run(["status", "--porcelain"], cwd=root).stdout == ""


def test_migrating_twice_makes_no_second_commit(tmp_path: Path) -> None:
    root = _init(tmp_path)
    _run(root, "migrate")
    after_first = _commits(root)
    again = _run(root, "migrate", why=None)  # no rationale is asked for: nothing to record
    assert "already in format 2" in again.output
    assert _commits(root) == after_first


def test_status_no_longer_offers_a_migration_afterwards(tmp_path: Path) -> None:
    root = _init(tmp_path)
    _run(root, "migrate")
    assert "is available" not in _run(root, "status", why=None).output


def test_migrate_needs_a_rationale_and_leaves_the_tree_untouched_without_one(
    tmp_path: Path,
) -> None:
    root = _init(tmp_path)
    _run(root, "migrate", why=None, expect=EXIT_RATIONALE_REFUSED)
    assert (root / ".strata" / "schema-version").read_text() == "1\n"
    assert gitio.run(["status", "--porcelain"], cwd=root).stdout == ""


# --------------------------------------------------------------------------- strata ai enable


def test_enable_turns_ai_on_with_every_kind_off_in_one_commit(tmp_path: Path) -> None:
    root = _init(tmp_path)
    before = _commits(root)
    result = _run(root, "ai", "enable")
    assert "enabled" in result.output
    assert "upgraded from format 1" in result.output
    assert len(_commits(root)) == len(before) + 1
    toml = (root / "strata.toml").read_text(encoding="utf-8")
    assert "[ai]\nenabled = true" in toml
    policy = json.loads(_run(root, "--json", "ai", "policy", why=None).output)
    assert policy["enabled"] is True
    assert policy["policy"] == dict.fromkeys(KINDS, "off")
    assert (root / ".strata" / "schema-version").read_text() == "2\n"
    message = _last_message(root)
    assert message.startswith("ai-enable: enable AI participation")
    assert WHY in message
    assert "Strata-Op: ai-enable" in message
    assert "Strata-Schema-Version: 2" in message


def test_enable_on_a_review_already_in_format_2_does_not_mention_an_upgrade(tmp_path: Path) -> None:
    root = _init(tmp_path)
    _run(root, "migrate")
    result = _run(root, "ai", "enable")
    assert "upgraded" not in result.output
    assert "Strata-Schema" not in _last_message(root)


def test_enable_twice_is_a_no_op(tmp_path: Path) -> None:
    root = _enabled(tmp_path)
    commits = _commits(root)
    again = _run(root, "ai", "enable", why=None)
    assert "already enabled" in again.output
    assert _commits(root) == commits


def test_enable_needs_the_leads_rationale(tmp_path: Path) -> None:
    root = _init(tmp_path)
    _run(root, "ai", "enable", why=None, expect=EXIT_RATIONALE_REFUSED)
    assert "[ai]" not in (root / "strata.toml").read_text(encoding="utf-8")
    assert (root / ".strata" / "schema-version").read_text() == "1\n"


def test_the_enabled_review_verifies(tmp_path: Path) -> None:
    _run(_enabled(tmp_path), "verify", why=None)


# --------------------------------------------------------------------------- strata ai policy


def test_policy_lists_every_kind_with_its_mode(tmp_path: Path) -> None:
    root = _enabled(tmp_path)
    output = _run(root, "ai", "policy", why=None).output
    assert "AI participation is enabled" in output
    for kind in KINDS:
        assert kind in output
    assert output.count(" off") == len(KINDS)


def test_policy_says_when_ai_is_not_enabled(tmp_path: Path) -> None:
    output = _run(_init(tmp_path), "ai", "policy", why=None).output
    assert "not enabled" in output
    assert "strata ai enable" in output


def test_policy_for_one_kind_shows_its_mode(tmp_path: Path) -> None:
    root = _enabled(tmp_path)
    _run(root, "ai", "policy", "screening", "suggest")
    assert _run(root, "ai", "policy", "screening", why=None).output.strip() == "suggest"
    assert json.loads(_run(root, "--json", "ai", "policy", "screening", why=None).output) == {
        "kind": "screening",
        "mode": "suggest",
    }


def test_setting_a_mode_is_one_commit_with_the_old_and_new_modes(tmp_path: Path) -> None:
    root = _enabled(tmp_path)
    before = _commits(root)
    result = _run(
        root, "ai", "policy", "screening", "suggest", why="Piloting AI suggestions on screening"
    )
    assert "off -> suggest" in result.output
    assert len(_commits(root)) == len(before) + 1
    message = _last_message(root)
    assert message.startswith("ai-policy(screening): set screening to suggest")
    assert "Piloting AI suggestions on screening" in message
    for trailer in (
        "Strata-Op: ai-policy",
        "Strata-Kind: screening",
        "Strata-From: off",
        "Strata-To: suggest",
    ):
        assert trailer in message
    assert gitio.run(["status", "--porcelain"], cwd=root).stdout == ""


def test_the_change_is_in_strata_log(tmp_path: Path) -> None:
    root = _enabled(tmp_path)
    _run(root, "ai", "policy", "screening", "suggest")
    log = _run(root, "log", why=None).output
    assert "ai-policy(screening): set screening to suggest" in log
    assert "ai-enable: enable AI participation" in log


def test_a_mode_can_be_changed_again_and_the_history_keeps_both(tmp_path: Path) -> None:
    root = _enabled(tmp_path)
    _run(root, "ai", "policy", "screening", "suggest")
    _run(root, "ai", "policy", "screening", "count")
    assert "Strata-From: suggest" in _last_message(root)
    assert "Strata-To: count" in _last_message(root)


def test_setting_the_mode_a_kind_already_has_records_nothing(tmp_path: Path) -> None:
    root = _enabled(tmp_path)
    commits = _commits(root)
    result = _run(root, "ai", "policy", "screening", "off", why=None)
    assert "already off" in result.output
    assert _commits(root) == commits


def test_an_unknown_kind_is_refused_and_the_valid_kinds_are_named(tmp_path: Path) -> None:
    root = _enabled(tmp_path)
    commits = _commits(root)
    for args in (("poetry", "suggest"), ("poetry",)):
        result = _run(root, "ai", "policy", *args, expect=EXIT_USAGE)
        assert "unknown kind of work 'poetry'" in result.output
        assert "risk-of-bias" in result.output
    assert _commits(root) == commits


def test_an_unknown_mode_is_refused_and_the_modes_are_named(tmp_path: Path) -> None:
    root = _enabled(tmp_path)
    result = _run(root, "ai", "policy", "screening", "always", expect=EXIT_USAGE)
    assert "off, suggest, count" in result.output


def test_setting_a_mode_before_enabling_is_a_usage_error_naming_enable(tmp_path: Path) -> None:
    root = _init(tmp_path)
    commits = _commits(root)
    result = _run(root, "ai", "policy", "screening", "suggest", expect=EXIT_USAGE)
    assert "strata ai enable" in result.output
    assert _commits(root) == commits
    assert "[ai" not in (root / "strata.toml").read_text(encoding="utf-8")


def test_setting_a_mode_needs_a_rationale(tmp_path: Path) -> None:
    root = _enabled(tmp_path)
    _run(root, "ai", "policy", "screening", "suggest", why=None, expect=EXIT_RATIONALE_REFUSED)
    assert (
        json.loads(_run(root, "--json", "ai", "policy", why=None).output)["policy"]["screening"]
        == "off"
    )


# --------------------------------------------------------------- strata actor add --kind agent


def _add_agent(root: Path, *extra: str, expect: int = EXIT_OK, handle: str = "claude-opus"):  # type: ignore[no-untyped-def]
    return _run(
        root, "actor", "add", handle, "Claude Opus", "--kind", "agent", *extra, expect=expect
    )


def test_registering_an_agent_lists_it_with_its_model(tmp_path: Path) -> None:
    root = _enabled(tmp_path)
    _add_agent(root, "--model", "claude-opus-5-5", "--role", "screener")
    actors = json.loads(_run(root, "--json", "actor", "list", why=None).output)
    agent = next(a for a in actors if a["handle"] == "claude-opus")
    assert (agent["kind"], agent["model"], agent["role"]) == (
        "agent",
        "claude-opus-5-5",
        "screener",
    )
    human = next(a for a in actors if a["handle"] == "ethan")
    assert "kind" not in human  # a person's entry is exactly as it always was
    message = _last_message(root)
    assert "Strata-Kind: agent" in message
    assert "Strata-Model: claude-opus-5-5" in message
    assert "Strata-Op: actor-add" in message
    _run(root, "verify", why=None)


def test_the_listing_says_the_model_is_self_reported(tmp_path: Path) -> None:
    root = _enabled(tmp_path)
    _add_agent(root, "--model", "claude-opus-5-5")
    listing = _run(root, "actor", "list", why=None).output
    assert "AI agent" in listing
    assert "claude-opus-5-5" in listing
    assert "self-reported" in listing


def test_an_agent_cannot_be_registered_in_format_1(tmp_path: Path) -> None:
    root = _init(tmp_path)
    result = _add_agent(root, "--model", "claude-opus-5-5", expect=EXIT_USAGE)
    assert "format 2" in result.output
    assert "strata ai enable" in result.output
    assert "strata migrate" in result.output


def test_an_agent_cannot_be_registered_before_ai_is_enabled(tmp_path: Path) -> None:
    root = _init(tmp_path)
    _run(root, "migrate")
    result = _add_agent(root, "--model", "claude-opus-5-5", expect=EXIT_USAGE)
    assert "strata ai enable" in result.output
    assert "claude-opus" not in (root / "strata.toml").read_text(encoding="utf-8")


def test_an_agent_needs_a_model(tmp_path: Path) -> None:
    result = _add_agent(_enabled(tmp_path), expect=EXIT_USAGE)
    assert "--model MODEL" in result.output


def test_an_agent_cannot_be_a_lead(tmp_path: Path) -> None:
    result = _add_agent(_enabled(tmp_path), "--model", "m", "--role", "lead", expect=EXIT_USAGE)
    assert "cannot hold the role 'lead'" in result.output


def test_a_person_cannot_have_a_model(tmp_path: Path) -> None:
    root = _enabled(tmp_path)
    result = _run(root, "actor", "add", "sam", "Sam", "--model", "m", expect=EXIT_USAGE)
    assert "only for an agent" in result.output


def test_an_unknown_kind_is_refused(tmp_path: Path) -> None:
    root = _enabled(tmp_path)
    result = _run(root, "actor", "add", "r", "R", "--kind", "robot", expect=EXIT_USAGE)
    assert "'human' or 'agent'" in result.output


def test_one_model_cannot_be_registered_for_two_active_agents(tmp_path: Path) -> None:
    root = _enabled(tmp_path)
    _add_agent(root, "--model", "claude-opus-5-5")
    result = _add_agent(root, "--model", "claude-opus-5-5", handle="opus-two", expect=EXIT_USAGE)
    assert "already registered as the agent 'claude-opus'" in result.output


@pytest.mark.req("E_CONFIG")
def test_deactivating_an_agent_points_to_revoke(tmp_path: Path) -> None:
    root = _enabled(tmp_path)
    _add_agent(root, "--model", "claude-opus-5-5")
    commits = _commits(root)
    result = _run(root, "actor", "deactivate", "claude-opus", expect=EXIT_USAGE)
    assert "strata ai revoke claude-opus" in result.output
    assert _commits(root) == commits
    actors = json.loads(_run(root, "--json", "actor", "list", why=None).output)
    assert next(a for a in actors if a["handle"] == "claude-opus")["role"] != "inactive"


def test_deactivating_an_agent_with_history_is_refused_too(tmp_path: Path) -> None:
    root = _enabled(tmp_path)
    _add_agent(root, "--model", "claude-opus-5-5")
    from strata.core.events import agent_scope, append_new_event

    with agent_scope("claude-opus", {"model": "claude-opus-5-5", "invoked_by": "ethan"}):
        append_new_event(
            root / "events" / "note" / "claude-opus.ndjson",
            ev="note",
            actor="claude-opus",
            body={"subject": "s", "text": "t"},
        )
    result = _run(root, "actor", "deactivate", "claude-opus", expect=EXIT_USAGE)
    assert "strata ai revoke" in result.output
    assert "history stays in the record" in result.output


def test_a_person_is_deactivated_as_before(tmp_path: Path) -> None:
    root = _enabled(tmp_path)
    _run(root, "actor", "add", "sam", "Sam")
    _run(root, "actor", "deactivate", "sam")
    assert "deactivated" in _last_message(root) or "actor-deactivate" in _last_message(root)
