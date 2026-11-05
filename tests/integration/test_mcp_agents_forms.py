"""The extraction and risk-of-bias write tools, and checklist items 9 and 11 for a review an agent
took part in: openspec:mcp-server#write-tools, openspec:ai-participation#disclosure-in-generated-text."""

# ruff: noqa: E501
from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from strata.core import operations as ops_mod
from strata.core.actor import add_actor
from strata.core.canon import dump_yaml_str
from strata.core.repo import Repo, open_repo
from strata.extract import records as extraction_records
from strata.extract import rob as rob_mod
from strata.protocol import studies as studies_mod
from strata.report import checklist, sections
from strata.report import facts as facts_mod
from tests.integration.test_mcp_agents import (
    WHY,
    _agent_events,
    _call,
    _has_events,
    _policy,
    _server,
    _write,
)
from tests.unit._m5 import finished_review
from tests.unit._m6 import AGENT, MODEL
from tests.unit.test_extract_records import FORM


@pytest.fixture(scope="module")
def template(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, list[str]]:
    repo, _ = finished_review(tmp_path_factory.mktemp("template"))
    repo.path("extraction").mkdir(exist_ok=True)
    repo.path("extraction", "schema.yaml").write_text(dump_yaml_str(FORM), encoding="utf-8")
    rob_mod.init_instrument(repo, "rob2")
    ops_mod.enable_ai(repo, rationale=WHY)
    repo = open_repo(repo.root)
    add_actor(repo, handle=AGENT, name="Claude Opus", role="extractor", kind="agent", model=MODEL)
    for kind in ("extraction", "risk-of-bias"):
        ops_mod.set_ai_policy(open_repo(repo.root), kind=kind, mode="suggest", rationale=WHY)
    return repo.root, sorted(studies_mod.study_map(open_repo(repo.root)).members)


@pytest.fixture
def world(template: tuple[Path, list[str]], tmp_path: Path) -> tuple[Repo, list[str]]:
    source, studies = template
    target = tmp_path / "review"
    shutil.copytree(source, target)
    return open_repo(target), studies


def test_the_forms_are_read_with_the_included_studies(world: tuple[Repo, list[str]]) -> None:
    repo, studies = world
    server = _server(repo)
    extraction = _call(server, "extraction_form").data
    assert extraction["available"] is True  # type: ignore[index]
    assert [f["name"] for f in extraction["schema"]["fields"]][:2] == ["n_total", "design"]  # type: ignore[index]
    assert extraction["studies"] == studies  # type: ignore[index]
    instrument = _call(server, "risk_of_bias_form").data
    assert instrument["available"] is True  # type: ignore[index]
    assert {d["id"] for d in instrument["instrument"]["domains"]} >= {"D1", "D2"}  # type: ignore[index]
    assert instrument["studies"] == studies  # type: ignore[index]


def test_extraction_in_suggest_mode_is_a_suggestion_and_writes_no_coding_file(
    world: tuple[Repo, list[str]],
) -> None:
    repo, studies = world
    result = _write(repo, "set_extraction_field", study=studies[0], field="n_total", value="64")
    assert (result["mode"], result["recorded"]) == ("suggest", "suggestion")
    assert not _has_events(repo, "extract")
    assert not list(repo.path("extraction").glob(f"**/{studies[0]}*"))


def test_extraction_in_count_mode_is_the_agents_own_event_and_file(
    world: tuple[Repo, list[str]],
) -> None:
    repo, studies = world
    repo = _policy(repo, extraction="count")
    result = _write(
        repo, "set_extraction_field", study=studies[0], field="n_total", value="64", source="p. 3"
    )
    assert (result["mode"], result["recorded"]) == ("count", "event")
    (event,) = _agent_events(repo, "extract")
    assert event["actor"] == AGENT and event["agent"]["model"] == MODEL
    assert event["body"]["study"] == studies[0] and event["body"]["fields_changed"] == ["n_total"]
    record = extraction_records.read_record(
        extraction_records.working_path(repo, AGENT, studies[0])
    )
    assert record is not None and record["fields"]["n_total"]["value"] == 64
    assert record["fields"]["n_total"]["source"] == "p. 3"


def test_an_extraction_value_the_form_rejects_is_refused_for_the_real_reason(
    world: tuple[Repo, list[str]],
) -> None:
    repo, studies = world
    repo = _policy(repo, extraction="count")
    reply = _call(
        _server(repo),
        "set_extraction_field",
        {"model": MODEL, "rationale": WHY, "study": studies[0], "field": "n_total", "value": "0"},
    )
    assert reply.is_error
    assert not _has_events(repo, "extract")
    unknown = _call(
        _server(repo),
        "set_extraction_field",
        {"model": MODEL, "rationale": WHY, "study": studies[0], "field": "nope", "value": "1"},
    )
    assert unknown.is_error and "no field" in unknown.text


def test_risk_of_bias_in_each_mode(world: tuple[Repo, list[str]]) -> None:
    repo, studies = world
    suggested = _write(repo, "record_risk_of_bias", study=studies[0], domain="D1", judgement="low")
    assert suggested["recorded"] == "suggestion" and not _has_events(repo, "rob")
    repo = _policy(repo, risk_of_bias="count")
    counted = _write(
        repo,
        "record_risk_of_bias",
        study=studies[0],
        domain="D1",
        judgement="low",
        support="Randomised.",
    )
    assert counted["recorded"] == "event"
    (event,) = _agent_events(repo, "rob")
    assert event["actor"] == AGENT and event["agent"]["invoked_by"] == "sam"
    assert (event["body"]["domain"], event["body"]["judgement"]) == ("D1", "low")


def test_a_judgement_the_instrument_does_not_allow_is_refused(
    world: tuple[Repo, list[str]],
) -> None:
    repo, studies = world
    repo = _policy(repo, risk_of_bias="count")
    reply = _call(
        _server(repo),
        "record_risk_of_bias",
        {
            "model": MODEL,
            "rationale": WHY,
            "study": studies[0],
            "domain": "D1",
            "judgement": "excellent",
        },
    )
    assert reply.is_error and "judgement must be one of" in reply.text
    assert not _has_events(repo, "rob")


def test_items_9_and_11_say_so_when_the_ai_took_part_in_other_work_only(
    world: tuple[Repo, list[str]],
) -> None:
    repo, studies = world
    _write(
        repo, "set_extraction_field", study=studies[0], field="n_total", value="64"
    )  # suggestion
    # AI took part in extraction (as a suggestion) but not in risk of bias.
    facts = facts_mod.collect(open_repo(repo.root))
    items = {item.id: item.content for item in checklist.build(facts)}
    assert "The AI model claude-opus-5-5" in items["9"]
    assert "in suggest mode made 1 extraction suggestion" in items["9"]
    assert "No AI model took part in the risk-of-bias assessment." in items["11"]
    methods = sections.methods(facts)
    assert "### Data collection" in methods and "### Risk of bias" in methods
    assert "No AI model took part in the risk-of-bias assessment." in methods


def test_items_9_and_11_name_the_model_that_extracted_and_assessed(
    world: tuple[Repo, list[str]],
) -> None:
    repo, studies = world
    repo = _policy(repo, extraction="count", risk_of_bias="count")
    _write(repo, "set_extraction_field", study=studies[0], field="n_total", value="64")
    _write(repo, "record_risk_of_bias", study=studies[0], domain="D1", judgement="low")
    facts = facts_mod.collect(open_repo(repo.root))
    items = {item.id: item.content for item in checklist.build(facts)}
    assert "in count mode 1 data extraction entry took effect as the model's own work" in items["9"]
    assert (
        "in count mode 1 risk-of-bias judgement took effect as the model's own work" in items["11"]
    )
    assert "No automation tools" not in items["9"] + items["11"]
