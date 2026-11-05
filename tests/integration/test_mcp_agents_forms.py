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
from tests.unit._m5 import canonical_ids, finished_review
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


# ------------------------------------------------ the remaining families, in each mode


def test_grouping_and_splitting_studies_obey_the_modes(world: tuple[Repo, list[str]]) -> None:
    repo, _ = world
    reports = studies_mod.included_reports(repo)
    free = [r for r in reports if len(studies_mod.study_map(repo).studies_of[r]) == 1]
    repo = _policy(repo, studies="suggest")
    suggested = _write(repo, "group_reports", reports=free[:2])
    assert suggested["recorded"] == "suggestion" and not _agent_events(repo, "study")
    repo = _policy(repo, studies="count")
    grouped = _write(repo, "group_reports", reports=free[:2])
    assert grouped["recorded"] == "event"
    (group_event,) = _agent_events(repo, "study")
    assert group_event["agent"]["model"] == MODEL and group_event["body"]["reports"] == sorted(
        free[:2]
    )
    split = _write(repo, "split_report", report=free[-1], parts=2)
    assert split["recorded"] == "event"
    split_event = [e for e in _agent_events(repo, "study") if e["ev"] == "study-split"][0]
    assert len(split_event["body"]["studies"]) == 2


def test_a_study_operation_the_real_one_would_refuse_is_refused(
    world: tuple[Repo, list[str]],
) -> None:
    repo, _ = world
    repo = _policy(repo, studies="count")
    one = _call(
        _server(repo),
        "split_report",
        {"model": MODEL, "rationale": WHY, "report": "rpt_0000000000000000", "parts": 2},
    )
    assert one.is_error and "not an included report" in one.text
    few = _call(
        _server(repo),
        "group_reports",
        {"model": MODEL, "rationale": WHY, "reports": ["rpt_0000000000000000"]},
    )
    assert few.is_error and "not included reports" in few.text
    assert not _agent_events(repo, "study")


def test_adding_and_retiring_a_criterion_in_count_mode(world: tuple[Repo, list[str]]) -> None:
    from strata.protocol import criteria as criteria_mod

    repo, _ = world
    repo = _policy(repo, criteria="count")
    before = int(criteria_mod.read_criteria_doc(repo)["version"])
    added = _write(
        repo,
        "add_criterion",
        kind="exclusion",
        label="Animal study",
        definition="Not on people.",
        applies_at=["title-abstract"],
    )
    assert added["recorded"] == "event" and added["preview"]["stale_decisions"] >= 0
    repo = open_repo(repo.root)
    assert int(criteria_mod.read_criteria_doc(repo)["version"]) == before + 1
    new_id = max(c["id"] for c in criteria_mod.list_criteria(repo) if c["label"] == "Animal study")
    retired = _write(repo, "retire_criterion", criterion=new_id)
    assert retired["recorded"] == "event"
    assert criteria_mod.get_criterion(open_repo(repo.root), new_id)["status"] == "retired"
    changes = [e for e in _agent_events(repo, "criteria") if e["ev"] == "criteria-change"]
    assert len(changes) == 2 and all(e["agent"]["model"] == MODEL for e in changes)


def test_deduplication_decisions_in_count_mode(world: tuple[Repo, list[str]]) -> None:
    repo, _ = world
    repo = _policy(repo, dedup="count")
    first, second, third = canonical_ids(repo)[:3]
    kept = _write(repo, "decide_duplicate", a=first, b=second, decision="distinct")
    assert kept["recorded"] == "event"
    (distinct,) = _agent_events(repo, "dedup")
    assert distinct["ev"] == "dedup-distinct" and distinct["agent"]["invoked_by"] == "sam"
    again = _call(
        _server(repo),
        "decide_duplicate",
        {"model": MODEL, "rationale": WHY, "a": first, "b": second, "decision": "merge"},
    )
    assert again.is_error and "already been judged" in again.text
    merged = _write(repo, "decide_duplicate", a=second, b=third, decision="merge")
    assert merged["recorded"] == "event"
    assert {e["ev"] for e in _agent_events(repo, "dedup")} == {"dedup-distinct", "dedup-merge"}


def test_a_duplicate_decision_about_nothing_is_refused_for_the_real_reason(
    world: tuple[Repo, list[str]],
) -> None:
    repo, _ = world
    repo = _policy(repo, dedup="count")
    only = canonical_ids(repo)[0]
    server = _server(repo)
    for args, needle in (
        ({"a": only, "b": only, "decision": "merge"}, "itself"),
        ({"a": only, "b": "rec_0000000000000000", "decision": "merge"}, "no record"),
        ({"a": only, "b": canonical_ids(repo)[1], "decision": "maybe"}, "'merge' or 'distinct'"),
    ):
        reply = _call(server, "decide_duplicate", {"model": MODEL, "rationale": WHY, **args})
        assert reply.is_error and needle in reply.text
    assert not _has_events(repo, "dedup")


def test_recording_a_search_in_count_mode_commits_it_as_the_agents_work(
    world: tuple[Repo, list[str]],
) -> None:
    from strata import gitio

    repo, _ = world
    repo = _policy(repo, search_import="count")
    result = _write(
        repo, "record_search", database="PsycINFO", platform="EBSCO", executed="2026-01-05",
        query="spaced practice AND recall",
    )  # fmt: skip
    assert result["recorded"] == "work" and result["committed"] is True
    assert list(repo.path("protocol", "searches").glob("*psycinfo*.yaml"))
    message = gitio.commit_message(repo.root, "HEAD")
    assert "Strata-Op: search-add" in message and f"Strata-Agent: {AGENT}" in message
    duplicate = _call(
        _server(repo),
        "record_search",
        {
            "model": MODEL,
            "rationale": WHY,
            "database": "PsycINFO",
            "platform": "EBSCO",
            "executed": "2026-01-05",
            "search_id": result_id(repo),
        },
    )
    assert duplicate.is_error and "already exists" in duplicate.text


def result_id(repo: Repo) -> str:
    return sorted(p.stem for p in repo.path("protocol", "searches").glob("*psycinfo*.yaml"))[0]


def test_the_diagram_tool_refuses_a_format_or_layout_it_cannot_draw(
    world: tuple[Repo, list[str]],
) -> None:
    repo, _ = world
    repo = _policy(repo, analysis="count")
    server = _server(repo)
    bad_format = _call(server, "draw_prisma", {"model": MODEL, "rationale": WHY, "format": "gif"})
    assert bad_format.is_error and "format must be one of" in bad_format.text
    bad_columns = _call(
        server, "draw_prisma", {"model": MODEL, "rationale": WHY, "columns": "three"}
    )
    assert bad_columns.is_error and "columns must be one of" in bad_columns.text
    assert not (repo.root / "reports" / "prisma.svg").exists()


def test_a_note_and_a_correction_need_something_real_to_say(world: tuple[Repo, list[str]]) -> None:
    repo, _ = world
    repo = _policy(repo, records="count")
    record = canonical_ids(repo)[0]
    server = _server(repo)
    empty = _call(
        server, "add_note", {"model": MODEL, "rationale": WHY, "record": record, "text": "   "}
    )
    assert empty.is_error and "needs some text" in empty.text
    nobody = _call(
        server,
        "add_note",
        {"model": MODEL, "rationale": WHY, "record": "rec_0000000000000000", "text": "x"},
    )
    assert nobody.is_error and "no record" in nobody.text
    assert not _has_events(repo, "note")
