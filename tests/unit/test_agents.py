"""Policy, registered models, invokers and the refusals of `core/agents.py`:
openspec:ai-participation."""

from __future__ import annotations

from pathlib import Path

import pytest
import tomlkit

from strata.core import agents as agents_mod
from strata.core import manifest as manifest_mod
from strata.core import operations as ops_mod
from strata.core.actor import add_actor
from strata.core.agents import AgentRefused
from strata.core.repo import open_repo
from tests.unit._m3 import init_review
from tests.unit._m6 import AGENT, MODEL, WHY, ai_review


def _authorise(repo, kind="screening", *, model=MODEL, invoked_by="sam", **extra):  # type: ignore[no-untyped-def]
    return agents_mod.authorise(repo, kind=kind, model=model, invoked_by=invoked_by, **extra)


# ---------------------------------------------------------------------------------- the policy


def test_a_review_that_never_enabled_ai_has_every_kind_off(tmp_path: Path) -> None:
    repo = init_review(tmp_path)
    assert not agents_mod.is_enabled(repo)
    assert agents_mod.policy(repo) == dict.fromkeys(agents_mod.KINDS_OF_WORK, "off")
    assert agents_mod.mode_for(repo, "screening") == "off"


def test_enabling_leaves_every_kind_off(tmp_path: Path) -> None:
    repo = ai_review(tmp_path)
    assert agents_mod.is_enabled(repo)
    assert set(agents_mod.policy(repo).values()) == {"off"}
    assert list(agents_mod.policy(repo)) == list(agents_mod.KINDS_OF_WORK)
    assert agents_mod.show_suggestions(repo) == "after-own-decision"


def test_a_kind_takes_the_mode_it_was_set_to(tmp_path: Path) -> None:
    repo = ai_review(tmp_path, policy={"screening": "suggest", "retrieval": "count"})
    assert agents_mod.mode_for(repo, "screening") == "suggest"
    assert agents_mod.mode_for(repo, "retrieval") == "count"
    assert agents_mod.mode_for(repo, "extraction") == "off"


def test_a_hand_edited_policy_is_not_in_force_until_ai_is_enabled(tmp_path: Path) -> None:
    repo = init_review(tmp_path)
    toml = (repo.root / "strata.toml").read_text(encoding="utf-8")
    (repo.root / "strata.toml").write_text(
        toml + '\n[ai.policy]\nscreening = "count"\n', encoding="utf-8"
    )
    assert agents_mod.mode_for(open_repo(repo.root), "screening") == "off"


def test_enabled_in_the_manifest_is_not_enough_in_format_1(tmp_path: Path) -> None:
    repo = init_review(tmp_path)
    toml = (repo.root / "strata.toml").read_text(encoding="utf-8")
    (repo.root / "strata.toml").write_text(toml + "\n[ai]\nenabled = true\n", encoding="utf-8")
    assert not agents_mod.is_enabled(open_repo(repo.root))


def test_an_unknown_kind_is_a_value_error_naming_the_kinds(tmp_path: Path) -> None:
    repo = ai_review(tmp_path)
    with pytest.raises(ValueError, match="screening, extraction, risk-of-bias"):
        agents_mod.mode_for(repo, "poetry")


def test_show_suggestions_follows_the_manifest(tmp_path: Path) -> None:
    repo = ai_review(tmp_path)
    toml = (repo.root / "strata.toml").read_text(encoding="utf-8")
    (repo.root / "strata.toml").write_text(
        toml.replace("[ai]\nenabled = true", '[ai]\nenabled = true\nshow_suggestions = "always"'),
        encoding="utf-8",
    )
    assert agents_mod.show_suggestions(open_repo(repo.root)) == "always"


# --------------------------------------------------------------------------------- the actors


def test_agents_and_people_are_told_apart(tmp_path: Path) -> None:
    repo = ai_review(tmp_path)
    assert agents_mod.is_agent(repo, AGENT)
    assert not agents_mod.is_agent(repo, "sam")
    assert agents_mod.agent_handles(repo) == frozenset({AGENT})
    assert [a["handle"] for a in agents_mod.human_actors(repo)] == ["ethan", "sam"]
    assert agents_mod.accepted_models(repo) == [MODEL]


def test_a_deactivated_agent_is_still_an_agent_but_accepts_no_model(tmp_path: Path) -> None:
    repo = ai_review(tmp_path)
    doc = manifest_mod.load_manifest_doc(repo.root)
    manifest_mod.find_actor(doc, AGENT)["role"] = "inactive"  # type: ignore[index]
    manifest_mod.write_manifest(repo.root, doc)
    repo = open_repo(repo.root)
    assert agents_mod.is_agent(repo, AGENT)
    assert agents_mod.accepted_models(repo) == []
    assert agents_mod.agent_actors(repo, active_only=True) == []


# ------------------------------------------------------------------------------- the invoker


def test_the_only_active_person_invokes_when_none_is_named(tmp_path: Path) -> None:
    repo = ai_review(tmp_path, people=())
    assert agents_mod.resolve_invoker(repo) == agents_mod.Invoker("ethan")


def test_several_people_need_to_be_told_who(tmp_path: Path) -> None:
    repo = ai_review(tmp_path, people=("sam",))
    invoker = agents_mod.resolve_invoker(repo)
    assert invoker.handle is None
    assert invoker.problem is not None
    assert "ethan, sam" in invoker.problem
    assert "strata mcp --as HANDLE" in invoker.problem


def test_an_observer_is_not_counted_among_the_people_who_can_invoke(tmp_path: Path) -> None:
    repo = init_review(tmp_path, actors=())
    ops_mod.enable_ai(repo, rationale=WHY)
    repo = open_repo(repo.root)
    add_actor(repo, handle="olive", name="Olive", role="observer")
    assert agents_mod.resolve_invoker(open_repo(repo.root)) == agents_mod.Invoker("ethan")


@pytest.mark.parametrize(
    ("named", "needle"),
    [
        ("nobody", "not an actor of this review"),
        (AGENT, "is an AI agent"),
        ("olive", "observer"),
        ("dora", "deactivated"),
    ],
)
def test_a_named_invoker_must_be_an_active_non_observer_person(
    tmp_path: Path, named: str, needle: str
) -> None:
    repo = ai_review(tmp_path)
    add_actor(repo, handle="olive", name="Olive", role="observer")
    add_actor(repo, handle="dora", name="Dora", role="inactive")
    invoker = agents_mod.resolve_invoker(open_repo(repo.root), named)
    assert invoker.handle is None
    assert needle in str(invoker.problem)


def test_a_named_person_is_the_invoker(tmp_path: Path) -> None:
    assert agents_mod.resolve_invoker(ai_review(tmp_path), "sam").handle == "sam"


# ----------------------------------------------------------------------------- the context


def test_the_context_builds_the_agent_key() -> None:
    context = agents_mod.AgentContext(
        actor=AGENT,
        model=MODEL,
        invoked_by="ada",
        client_name="claude-code",
        client_version="2.1.3",
    )
    assert context.envelope_value() == {
        "model": MODEL,
        "client": {"name": "claude-code", "version": "2.1.3"},
        "invoked_by": "ada",
    }


def test_a_client_that_gave_nothing_leaves_the_client_out() -> None:
    context = agents_mod.AgentContext(actor=AGENT, model=MODEL, invoked_by="ada")
    assert context.envelope_value() == {"model": MODEL, "invoked_by": "ada"}


def test_a_client_that_gave_only_a_name_records_only_that() -> None:
    context = agents_mod.AgentContext(actor=AGENT, model=MODEL, invoked_by="ada", client_name="x")
    assert context.envelope_value()["client"] == {"name": "x"}


# --------------------------------------------------------------------------- authorisation


def test_a_registered_model_in_a_mode_that_is_on_is_authorised(tmp_path: Path) -> None:
    repo = ai_review(tmp_path, policy={"screening": "suggest"})
    authorised = _authorise(repo, client_name="claude-code", client_version="2.1.3")
    assert authorised.mode == "suggest"
    assert authorised.context == agents_mod.AgentContext(
        actor=AGENT,
        model=MODEL,
        invoked_by="sam",
        client_name="claude-code",
        client_version="2.1.3",
    )


def test_a_change_of_policy_takes_effect_on_the_next_call(tmp_path: Path) -> None:
    repo = ai_review(tmp_path, policy={"screening": "suggest"})
    assert _authorise(repo).mode == "suggest"
    ops_mod.set_ai_policy(repo, kind="screening", mode="count", rationale=WHY)
    assert _authorise(open_repo(repo.root)).mode == "count"
    ops_mod.set_ai_policy(open_repo(repo.root), kind="screening", mode="off", rationale=WHY)
    with pytest.raises(AgentRefused) as refused:
        _authorise(open_repo(repo.root))
    assert refused.value.code == agents_mod.REFUSED_POLICY_OFF


def test_refused_when_ai_is_not_enabled(tmp_path: Path) -> None:
    repo = init_review(tmp_path)
    with pytest.raises(AgentRefused, match=r"not enabled.*`strata ai enable`") as refused:
        _authorise(repo, invoked_by="ethan")
    assert refused.value.code == agents_mod.REFUSED_NOT_ENABLED


def test_refused_when_the_kind_is_off_and_the_message_names_the_policy(tmp_path: Path) -> None:
    repo = ai_review(tmp_path, policy={"screening": "suggest"})
    with pytest.raises(AgentRefused) as refused:
        _authorise(repo, "extraction")
    assert refused.value.code == agents_mod.REFUSED_POLICY_OFF
    message = str(refused.value)
    assert "'extraction'" in message
    assert "[ai.policy] extraction" in message
    assert "strata ai policy extraction suggest" in message


def test_refused_when_no_model_is_reported(tmp_path: Path) -> None:
    repo = ai_review(tmp_path, policy={"screening": "suggest"})
    for missing in (None, "", "   "):
        with pytest.raises(AgentRefused) as refused:
            _authorise(repo, model=missing)
        assert refused.value.code == agents_mod.REFUSED_NO_MODEL


def test_refused_for_an_unregistered_model_and_the_message_tells_a_lead_how_to_accept_it(
    tmp_path: Path,
) -> None:
    repo = ai_review(tmp_path, policy={"screening": "suggest"})
    with pytest.raises(AgentRefused) as refused:
        _authorise(repo, model="claude-opus-5-6")
    assert refused.value.code == agents_mod.REFUSED_UNKNOWN_MODEL
    message = str(refused.value)
    assert "'claude-opus-5-6' is not one this review accepts" in message
    assert f"accepts: {MODEL}" in message
    assert "strata actor add NAME --kind agent --model claude-opus-5-6" in message


def test_a_model_name_must_match_exactly_not_by_prefix_or_case(tmp_path: Path) -> None:
    repo = ai_review(tmp_path, policy={"screening": "suggest"})
    for near in (MODEL.upper(), MODEL + "-latest", MODEL[:-1], f" {MODEL}x"):
        with pytest.raises(AgentRefused) as refused:
            _authorise(repo, model=near)
        assert refused.value.code == agents_mod.REFUSED_UNKNOWN_MODEL


def test_an_unregistered_model_in_a_review_that_accepts_none_says_so(tmp_path: Path) -> None:
    repo = ai_review(tmp_path, agents={}, policy={"screening": "suggest"})
    with pytest.raises(AgentRefused, match="accepts no model yet"):
        _authorise(repo)


def test_refused_for_a_deactivated_agent(tmp_path: Path) -> None:
    repo = ai_review(tmp_path, policy={"screening": "suggest"})
    doc = manifest_mod.load_manifest_doc(repo.root)
    manifest_mod.find_actor(doc, AGENT)["role"] = "inactive"  # type: ignore[index]
    manifest_mod.write_manifest(repo.root, doc)
    with pytest.raises(AgentRefused, match=f"{AGENT!r}.*deactivated") as refused:
        _authorise(open_repo(repo.root))
    assert refused.value.code == agents_mod.REFUSED_DEACTIVATED


def test_the_active_agent_is_used_when_an_earlier_one_for_the_model_was_deactivated(
    tmp_path: Path,
) -> None:
    repo = ai_review(tmp_path, policy={"screening": "suggest"})
    doc = manifest_mod.load_manifest_doc(repo.root)
    manifest_mod.find_actor(doc, AGENT)["role"] = "inactive"  # type: ignore[index]
    manifest_mod.write_manifest(repo.root, doc)
    repo = open_repo(repo.root)
    add_actor(repo, handle="opus-two", name="Opus Two", kind="agent", model=MODEL)
    assert _authorise(open_repo(repo.root)).context.actor == "opus-two"


def test_refused_when_no_person_is_named(tmp_path: Path) -> None:
    repo = ai_review(tmp_path, policy={"screening": "suggest"})
    for missing in (None, ""):
        with pytest.raises(AgentRefused, match="strata mcp --as HANDLE") as refused:
            _authorise(repo, invoked_by=missing)
        assert refused.value.code == agents_mod.REFUSED_NO_INVOKER


def test_refused_when_the_invoker_is_an_observer(tmp_path: Path) -> None:
    repo = ai_review(tmp_path, policy={"screening": "suggest"})
    add_actor(repo, handle="olive", name="Olive", role="observer")
    with pytest.raises(AgentRefused, match="observer") as refused:
        _authorise(open_repo(repo.root), invoked_by="olive")
    assert refused.value.code == agents_mod.REFUSED_BAD_INVOKER


def test_refused_when_the_invoker_is_an_agent(tmp_path: Path) -> None:
    repo = ai_review(tmp_path, policy={"screening": "suggest"})
    with pytest.raises(AgentRefused, match="is an AI agent") as refused:
        _authorise(repo, invoked_by=AGENT)
    assert refused.value.code == agents_mod.REFUSED_BAD_INVOKER


def test_asking_for_a_kind_of_work_that_does_not_exist_is_a_programming_error(
    tmp_path: Path,
) -> None:
    with pytest.raises(ValueError, match="unknown kind of work"):
        _authorise(ai_review(tmp_path), "poetry")


# ------------------------------------------------------------------ editing the manifest


def _doc() -> tomlkit.TOMLDocument:
    return tomlkit.parse('schema_version = 2\n\n[project]\ntitle = "T"\n')


def test_enabling_in_a_document_writes_every_kind_off() -> None:
    doc = _doc()
    assert agents_mod.enable_in_doc(doc)
    unwrapped = doc.unwrap()
    assert unwrapped["ai"]["enabled"] is True
    assert unwrapped["ai"]["policy"] == dict.fromkeys(agents_mod.KINDS_OF_WORK, "off")


def test_enabling_what_is_already_enabled_changes_nothing() -> None:
    doc = _doc()
    agents_mod.enable_in_doc(doc)
    before = tomlkit.dumps(doc)
    assert not agents_mod.enable_in_doc(doc)
    assert tomlkit.dumps(doc) == before


def test_enabling_keeps_what_a_lead_wrote_by_hand_before() -> None:
    doc = tomlkit.parse(
        'schema_version = 2\n\n[ai]\nenabled = false\nshow_suggestions = "always"\n\n'
        '[ai.policy]\nscreening = "off"\n'
    )
    assert agents_mod.enable_in_doc(doc)
    ai = doc.unwrap()["ai"]
    assert ai["enabled"] is True
    assert ai["show_suggestions"] == "always"
    assert ai["policy"]["screening"] == "off"
    assert ai["policy"]["analysis"] == "off"


def test_setting_a_policy_reports_the_old_and_new_mode() -> None:
    doc = _doc()
    agents_mod.enable_in_doc(doc)
    assert agents_mod.set_policy_in_doc(doc, "screening", "suggest") == ("off", "suggest")
    assert agents_mod.set_policy_in_doc(doc, "screening", "count") == ("suggest", "count")
    assert doc.unwrap()["ai"]["policy"]["screening"] == "count"


def test_setting_a_policy_in_a_table_that_lacks_one_creates_it() -> None:
    doc = tomlkit.parse("schema_version = 2\n\n[ai]\nenabled = true\n")
    assert agents_mod.set_policy_in_doc(doc, "dedup", "suggest") == ("off", "suggest")
    assert doc.unwrap()["ai"]["policy"] == {"dedup": "suggest"}


def test_setting_a_policy_names_the_valid_kinds_and_modes() -> None:
    doc = _doc()
    agents_mod.enable_in_doc(doc)
    with pytest.raises(ValueError, match="the kinds are screening"):
        agents_mod.set_policy_in_doc(doc, "poetry", "suggest")
    with pytest.raises(ValueError, match="the modes are off, suggest, count"):
        agents_mod.set_policy_in_doc(doc, "screening", "always")


@pytest.mark.parametrize(
    "text", ["schema_version = 2\n", "schema_version = 2\n[ai]\nenabled = false\n"]
)
def test_setting_a_policy_before_enabling_names_the_command(text: str) -> None:
    with pytest.raises(manifest_mod.ConfigError, match="strata ai enable"):
        agents_mod.set_policy_in_doc(tomlkit.parse(text), "screening", "suggest")
