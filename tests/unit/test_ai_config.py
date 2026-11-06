"""The manifest rules for agents (`E_CONFIG`, `E_SCHEMA`) and what `strata verify` makes of an
`agent` envelope key: openspec:data-schemas#agent-actors-and-ai-settings and
openspec:ai-participation#every-agent-event-is-attributed."""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

from strata.core import agents as agents_mod
from strata.core import events as events_mod
from strata.core import manifest as manifest_mod
from strata.core.repo import Repo, open_repo
from strata.core.validate import SchemaValidationError, validate
from strata.core.verify import verify_repository
from strata.protocol import pool as pool_mod
from strata.protocol.screening import record_screen_decision
from tests.unit._m3 import add_records, decide
from tests.unit._m6 import AGENT, MODEL, ai_review

_BASE = """\
schema_version = {version}
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

[[actors]]
handle = "sam"
name = "Sam"
role = "screener"
"""

_AGENT_ACTOR = """
[[actors]]
handle = "claude-opus"
name = "Claude Opus"
role = "screener"
kind = "agent"
model = "claude-opus-5-5"
"""

_AI_ON = """
[ai]
enabled = true
"""


def _repo(tmp_path: Path, extra: str = "", *, version: int = 2) -> Repo:
    text = _BASE.format(version=version) + extra
    (tmp_path / "strata.toml").write_text(text, encoding="utf-8")
    (tmp_path / ".strata").mkdir(exist_ok=True)
    (tmp_path / ".strata" / "schema-version").write_text(f"{version}\n", encoding="utf-8")
    return Repo(root=tmp_path, config=tomllib.loads(text))


def _codes(repo: Repo, *, fast: bool = False) -> list[str]:
    return [i.code for i in verify_repository(repo, fast=fast).issues]


# ------------------------------------------------------------------ E_CONFIG, per scenario


def test_a_valid_agent_configuration_has_no_problems(tmp_path: Path) -> None:
    repo = _repo(tmp_path, _AGENT_ACTOR + _AI_ON)
    assert manifest_mod.config_problems(repo.config) == []
    assert _codes(repo) == []


@pytest.mark.req("E_CONFIG")
def test_an_agent_without_a_model_is_a_config_error(tmp_path: Path) -> None:
    extra = _AGENT_ACTOR.replace('model = "claude-opus-5-5"\n', "") + _AI_ON
    repo = _repo(tmp_path, extra)
    assert manifest_mod.config_problems(repo.config) == ["agent actor 'claude-opus' has no model"]
    with pytest.raises(manifest_mod.ConfigError) as raised:
        manifest_mod.validate_config(repo.config)
    assert raised.value.code == "E_CONFIG"
    assert "E_CONFIG" in _codes(repo)


@pytest.mark.req("E_CONFIG")
def test_a_person_with_a_model_is_a_config_error(tmp_path: Path) -> None:
    extra = _AGENT_ACTOR.replace('kind = "agent"\n', "") + _AI_ON
    repo = _repo(tmp_path, extra)
    assert manifest_mod.config_problems(repo.config) == [
        "'claude-opus' is a person, so it cannot have a model"
    ]
    assert "E_CONFIG" in _codes(repo)


@pytest.mark.req("E_CONFIG")
def test_a_person_marked_human_with_a_model_is_also_refused(tmp_path: Path) -> None:
    extra = _AGENT_ACTOR.replace('kind = "agent"', 'kind = "human"') + _AI_ON
    assert manifest_mod.config_problems(_repo(tmp_path, extra).config)


@pytest.mark.req("E_CONFIG")
@pytest.mark.parametrize("mode", ["suggest", "count"])
def test_a_policy_without_enabling_is_a_config_error(tmp_path: Path, mode: str) -> None:
    for header in ("", "[ai]\nenabled = false\n"):
        repo = _repo(tmp_path, f'\n{header}\n[ai.policy]\nscreening = "{mode}"\n')
        problems = manifest_mod.config_problems(repo.config)
        assert len(problems) == 1
        assert "not enabled" in problems[0]
        assert "E_CONFIG" in _codes(repo)


def test_a_policy_that_leaves_everything_off_needs_no_enabling(tmp_path: Path) -> None:
    repo = _repo(tmp_path, '\n[ai.policy]\nscreening = "off"\n')
    assert manifest_mod.config_problems(repo.config) == []


@pytest.mark.req("E_CONFIG")
def test_an_agent_as_lead_is_a_config_error(tmp_path: Path) -> None:
    extra = _AGENT_ACTOR.replace('role = "screener"', 'role = "lead"') + _AI_ON
    repo = _repo(tmp_path, extra)
    assert manifest_mod.config_problems(repo.config) == [
        "agent actor 'claude-opus' cannot hold the role 'lead'"
    ]
    assert "E_CONFIG" in _codes(repo)


def test_two_active_agents_for_one_model_are_a_config_error(tmp_path: Path) -> None:
    second = _AGENT_ACTOR.replace('handle = "claude-opus"', 'handle = "opus-two"').replace(
        "Claude Opus", "Opus Two"
    )
    repo = _repo(tmp_path, _AGENT_ACTOR + second + _AI_ON)
    (problem,) = manifest_mod.config_problems(repo.config)
    assert "registered for more than one active agent" in problem
    assert "claude-opus, opus-two" in problem


def test_a_deactivated_agent_does_not_clash_with_its_replacement(tmp_path: Path) -> None:
    old = _AGENT_ACTOR.replace('role = "screener"', 'role = "inactive"')
    new = _AGENT_ACTOR.replace('handle = "claude-opus"', 'handle = "opus-two"')
    assert manifest_mod.config_problems(_repo(tmp_path, old + new + _AI_ON).config) == []


def test_ai_enabled_in_a_format_that_does_not_permit_it_is_a_config_error(tmp_path: Path) -> None:
    repo = _repo(tmp_path, _AI_ON, version=1)
    assert (
        manifest_mod.config_problems(repo.config) == []
    )  # a rule about two files, not the manifest
    issues = verify_repository(repo).issues
    assert any(i.code == "E_CONFIG" and "format 1" in i.message for i in issues)


# ------------------------------------------------------------------- E_SCHEMA, per value


@pytest.mark.parametrize(
    "extra",
    [
        '\n[[actors]]\nhandle = "r"\nname = "R"\nrole = "screener"\nkind = "robot"\n',
        '\n[ai]\nenabled = "yes"\n',
        '\n[ai]\nenabled = true\nshow_suggestions = "sometimes"\n',
        "\n[ai]\nenabled = true\nmystery = 1\n",
        '\n[ai]\nenabled = true\n[ai.policy]\npoetry = "count"\n',
        '\n[ai]\nenabled = true\n[ai.policy]\nscreening = "always"\n',
    ],
)
def test_a_value_of_the_wrong_kind_is_a_schema_error(extra: str, tmp_path: Path) -> None:
    repo = _repo(tmp_path, extra)
    with pytest.raises(SchemaValidationError):
        validate("manifest", repo.config)
    assert "E_SCHEMA" in _codes(repo)


# ---------------------------------------------------------------- agent events in verify


def _agent_key(**overrides: object) -> dict[str, object]:
    key: dict[str, object] = {
        "model": MODEL,
        "client": {"name": "claude-code", "version": "2.1.3"},
        "invoked_by": "sam",
    }
    key.update(overrides)
    return key


def _note(repo: Repo, actor: str, *, agent: dict[str, object] | None = None) -> None:
    path = repo.path("events", "note", f"{actor}.ndjson")
    events_mod.append_event(
        path,
        events_mod.build_envelope(
            ev="note",
            actor=actor,
            seq=events_mod.next_seq(path),
            body={"subject": "s", "text": "t"},
            prev=events_mod.last_digest(path),
            agent=agent,
        ),
    )


def _issues(repo: Repo) -> list[tuple[str, str]]:
    return [(i.code, i.message) for i in verify_repository(repo, fast=True).issues]


@pytest.mark.req("E_AGENT_ATTRIBUTION")
def test_an_attributed_agent_event_in_an_enabled_review_is_valid(tmp_path: Path) -> None:
    repo = _repo(tmp_path, _AGENT_ACTOR + _AI_ON)
    _note(repo, AGENT, agent=_agent_key())
    _note(repo, "ethan")
    assert _issues(repo) == []
    assert _codes(repo) == []  # the hash chain covers the agent key too


@pytest.mark.req("E_AGENT_ATTRIBUTION")
def test_an_agent_key_in_format_1_is_invalid(tmp_path: Path) -> None:
    repo = _repo(tmp_path, _AGENT_ACTOR + _AI_ON, version=1)
    _note(repo, AGENT, agent=_agent_key())
    problems = [m for c, m in _issues(repo) if c == "E_AGENT_ATTRIBUTION"]
    assert len(problems) == 1
    assert "format 1" in problems[0]


@pytest.mark.req("E_AGENT_ATTRIBUTION")
@pytest.mark.parametrize("ai", ["", "\n[ai]\nenabled = false\n"])
def test_an_agent_key_where_ai_is_not_enabled_is_invalid(tmp_path: Path, ai: str) -> None:
    repo = _repo(tmp_path, _AGENT_ACTOR + ai)
    _note(repo, AGENT, agent=_agent_key())
    problems = [m for c, m in _issues(repo) if c == "E_AGENT_ATTRIBUTION"]
    assert len(problems) == 1
    assert "not enabled" in problems[0]


@pytest.mark.req("E_AGENT_ATTRIBUTION")
def test_an_agent_key_on_a_persons_event_is_invalid(tmp_path: Path) -> None:
    repo = _repo(tmp_path, _AGENT_ACTOR + _AI_ON)
    _note(repo, "sam", agent=_agent_key())
    problems = [m for c, m in _issues(repo) if c == "E_AGENT_ATTRIBUTION"]
    assert any("'sam' is not a registered AI agent" in m for m in problems)


@pytest.mark.req("E_AGENT_ATTRIBUTION")
def test_an_agent_key_on_an_unregistered_actors_event_is_invalid(tmp_path: Path) -> None:
    repo = _repo(tmp_path, _AI_ON)
    _note(repo, "ghost", agent=_agent_key())
    assert any("'ghost' is not a registered AI agent" in m for _c, m in _issues(repo))


@pytest.mark.req("E_AGENT_ATTRIBUTION")
def test_a_model_other_than_the_registered_one_is_invalid(tmp_path: Path) -> None:
    repo = _repo(tmp_path, _AGENT_ACTOR + _AI_ON)
    _note(repo, AGENT, agent=_agent_key(model="claude-opus-5-6"))
    problems = [m for c, m in _issues(repo) if c == "E_AGENT_ATTRIBUTION"]
    assert len(problems) == 1
    assert "reports the model 'claude-opus-5-6'" in problems[0]
    assert f"registered for {MODEL!r}" in problems[0]


@pytest.mark.req("E_AGENT_ATTRIBUTION")
@pytest.mark.parametrize("invoker", ["ghost", AGENT])
def test_an_invoker_who_is_not_a_registered_person_is_invalid(tmp_path: Path, invoker: str) -> None:
    repo = _repo(tmp_path, _AGENT_ACTOR + _AI_ON)
    _note(repo, AGENT, agent=_agent_key(invoked_by=invoker))
    assert any(
        f"invoked by {invoker!r}, who is not a registered person" in m for _c, m in _issues(repo)
    )


def test_an_invoker_who_has_since_been_deactivated_does_not_invalidate_history(
    tmp_path: Path,
) -> None:
    extra = _AGENT_ACTOR + _AI_ON
    repo = _repo(tmp_path, extra)
    _note(repo, AGENT, agent=_agent_key(invoked_by="sam"))
    text = (tmp_path / "strata.toml").read_text(encoding="utf-8")
    (tmp_path / "strata.toml").write_text(
        text.replace('name = "Sam"\nrole = "screener"', 'name = "Sam"\nrole = "inactive"'),
        encoding="utf-8",
    )
    reopened = Repo(root=tmp_path, config=tomllib.loads((tmp_path / "strata.toml").read_text()))
    assert _issues(reopened) == []


@pytest.mark.req("E_AGENT_ATTRIBUTION")
def test_an_event_under_an_agents_handle_without_the_key_is_invalid(tmp_path: Path) -> None:
    repo = _repo(tmp_path, _AGENT_ACTOR + _AI_ON)
    _note(repo, AGENT)
    assert any("carries no agent key" in m for _c, m in _issues(repo))


def test_a_malformed_agent_key_is_the_schemas_to_report(tmp_path: Path) -> None:
    repo = _repo(tmp_path, _AGENT_ACTOR + _AI_ON)
    _note(repo, AGENT, agent={"model": MODEL})  # no invoked_by
    codes = [c for c, _m in _issues(repo)]
    assert "E_SCHEMA" in codes


def test_an_agent_key_that_is_not_an_object_is_the_schemas_to_report(tmp_path: Path) -> None:
    repo = _repo(tmp_path, _AGENT_ACTOR + _AI_ON)
    path = repo.path("events", "note", f"{AGENT}.ndjson")
    envelope = events_mod.build_envelope(
        ev="note", actor=AGENT, seq=1, body={"subject": "s", "text": "t"}
    )
    envelope["agent"] = "claude"
    path.parent.mkdir(parents=True)
    path.write_text(
        events_mod.serialise_envelope(envelope) + "\n",
        encoding="utf-8",  # type: ignore[attr-defined]
    )
    assert [c for c, _m in _issues(repo)] == ["E_SCHEMA"]


def test_tampering_with_the_agent_key_breaks_the_chain(tmp_path: Path) -> None:
    repo = _repo(tmp_path, _AGENT_ACTOR + _AI_ON)
    _note(repo, AGENT, agent=_agent_key())
    path = repo.path("events", "note", f"{AGENT}.ndjson")
    path.write_text(path.read_text().replace('"invoked_by":"sam"', '"invoked_by":"ethan"'))
    assert "E_CHAIN" in _codes(repo)


# --------------------------------------------------- W_UNASSIGNED_OPINION (the fold fix)


def test_verify_warns_about_a_record_an_unassigned_person_used_to_help_resolve(
    tmp_path: Path,
) -> None:
    """`rita` was never assigned, but under the old fold her opinion plus `ethan`'s resolved the
    record that `sam` had not yet seen."""
    repo = ai_review(tmp_path, people=("sam", "rita"))
    toml = (repo.root / "strata.toml").read_text(encoding="utf-8")
    (repo.root / "strata.toml").write_text(
        toml + '\n[screening.assignment]\ntitle-abstract = ["ethan", "sam"]\n', encoding="utf-8"
    )
    repo = open_repo(repo.root)
    ids = add_records(repo, 2)
    decide(repo, "title-abstract", ids[:1], actors=("ethan", "rita"))  # sam never decided
    decide(repo, "title-abstract", ids[1:], actors=("ethan", "sam"))  # an ordinary record
    report = verify_repository(open_repo(repo.root))
    warnings = [i for i in report.issues if i.code == "W_UNASSIGNED_OPINION"]
    assert len(warnings) == 1
    assert warnings[0].severity == "warning"
    assert "1 record(s) at title-abstract" in warnings[0].message
    assert ids[0] in warnings[0].message
    assert report.ok  # a warning does not fail verification


def test_verify_does_not_warn_when_the_unassigned_opinion_changed_nothing(tmp_path: Path) -> None:
    repo = ai_review(tmp_path, people=("sam", "rita"))
    toml = (repo.root / "strata.toml").read_text(encoding="utf-8")
    (repo.root / "strata.toml").write_text(
        toml + '\n[screening.assignment]\ntitle-abstract = ["ethan", "sam"]\n', encoding="utf-8"
    )
    repo = open_repo(repo.root)
    ids = add_records(repo, 1)
    decide(repo, "title-abstract", ids, actors=("ethan", "sam", "rita"))
    assert not [
        i
        for i in verify_repository(open_repo(repo.root)).issues
        if i.code == "W_UNASSIGNED_OPINION"
    ]


def test_verify_does_not_warn_about_an_unassigned_agent(tmp_path: Path) -> None:
    """An unassigned agent's opinion is expected to be ignored, so it is not news."""
    repo = ai_review(tmp_path, policy={"screening": "count"})
    toml = (repo.root / "strata.toml").read_text(encoding="utf-8")
    (repo.root / "strata.toml").write_text(
        toml + '\n[screening.assignment]\ntitle-abstract = ["ethan", "sam"]\n', encoding="utf-8"
    )
    repo = open_repo(repo.root)
    ids = add_records(repo, 1)
    decide(repo, "title-abstract", ids, actors=("ethan",))
    # The agent's own file, written as the MCP layer would: the agent key rides along.
    with events_mod.agent_scope(
        AGENT, agents_mod.AgentContext(actor=AGENT, model=MODEL, invoked_by="sam").envelope_value()
    ):
        record_screen_decision(
            repo, stage="title-abstract", record_id=ids[0], decision="include", actor=AGENT
        )
    pool_mod.regenerate_all(open_repo(repo.root))  # as the commands leave a review
    report = verify_repository(open_repo(repo.root))
    assert not [i for i in report.issues if i.code == "W_UNASSIGNED_OPINION"]
    assert [i.code for i in report.issues if i.severity == "error"] == []
