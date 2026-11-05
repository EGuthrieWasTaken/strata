# ruff: noqa: E501
"""AI participation from enabling to revoking, checked at every step:
openspec:ai-participation (the whole capability) and openspec:ai-suggestions.

A lead enables AI, registers a model and assigns it; it suggests and a person adopts; it counts as a
second reviewer, produces a conflict and an agreement; a person adjudicates; the lead revokes it. At
each step the counts, the agreement pairs, the commit trailers, the stale queue and the Methods text
say what the record holds, and `strata verify` agrees.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from mcp import Client
from mcp.types import Implementation
from typer.testing import CliRunner

from strata import gitio
from strata.cli.main import app
from strata.core import events as events_mod
from strata.core import ledger as ledger_mod
from strata.core import operations as ops_mod
from strata.core.repo import Repo, open_repo
from strata.mcpserver.server import READ_TOOLS, create_mcp_server
from strata.protocol import adjudication as adjudication_mod
from strata.protocol import criteria as criteria_mod
from strata.protocol import irr as irr_mod
from strata.protocol import pool as pool_mod
from strata.protocol import rescreen as rescreen_mod
from strata.protocol import screening as screening_mod
from strata.protocol import suggestions as sugg
from strata.report import counts as counts_mod
from strata.report import facts as facts_mod
from strata.report import sections
from tests.unit._m3 import add_records

runner = CliRunner()
STAGE = "title-abstract"
MODEL = "claude-opus-5-5"
AGENT = "claude-opus"
WHY = "Following the protocol agreed with the team."


def _cli(root: Path, *args: str, why: str | None = WHY) -> str:
    prefix = ["-C", str(root)] + (["--why", why] if why else [])
    result = runner.invoke(app, [*prefix, *args])
    assert result.exit_code == 0, result.output
    return " ".join(result.output.split())


def _agent(root: Path, tool: str, **args: Any) -> dict[str, Any]:
    server = create_mcp_server(repo_root=root, invoker="sam")

    async def run() -> Any:
        info = Implementation(name="claude-code", version="2.1.3")
        async with Client(server, client_info=info) as session:
            return await session.call_tool(
                tool,
                {"model": MODEL, "rationale": "Meets the population and outcome criteria.", **args},
            )

    result = asyncio.run(run())
    assert not result.is_error, " ".join(getattr(p, "text", "") for p in result.content)
    return dict(result.structured_content or {})


def _refused_text(root: Path, tool: str, **args: Any) -> str:
    server = create_mcp_server(repo_root=root, invoker="sam")

    async def run() -> Any:
        async with Client(server) as session:
            return await session.call_tool(
                tool,
                {"model": MODEL, "rationale": "Meets the population and outcome criteria.", **args},
            )

    result = asyncio.run(run())
    assert result.is_error
    return " ".join(getattr(p, "text", "") for p in result.content)


def _counts(repo: Repo) -> dict[str, Any]:
    return counts_mod.compute(repo).to_dict()["totals"]


def _verify(root: Path) -> None:
    assert "ok" in _cli(root, "verify", why=None)


def _methods(repo: Repo) -> str:
    return sections.methods(facts_mod.collect(open_repo(repo.root)))


def _pairs(repo: Repo) -> dict[tuple[str, str], bool]:
    return {
        (p.actor_a, p.actor_b): p.involves_agent for p in irr_mod.compute_stage_irr(repo, STAGE)
    }


def test_from_enabling_to_revoking(tmp_path: Path) -> None:
    root = tmp_path / "review"
    _cli(
        root.parent,
        "init",
        str(root),
        "--title",
        "Spacing",
        "--actor",
        "ethan",
        "--actor-name",
        "Ethan",
        why=None,
    )
    _cli(root, "actor", "add", "sam", "Sam", "--role", "screener")
    repo = open_repo(root)
    criteria_mod.add_criterion(
        repo, kind="exclusion", label="Not empirical", definition="Not an empirical study.",
        applies_at=[STAGE, "full-text"], actor="ethan", rationale="Establishing the protocol.",
    )  # fmt: skip
    ids = add_records(open_repo(root), 5)
    repo = open_repo(root)
    _verify(root)

    # 1. A review that has not enabled AI: reads only, and the Methods text says what it always said.
    server = create_mcp_server(repo_root=root, invoker="sam")

    async def tool_names() -> set[str]:
        async with Client(server) as session:
            return {t.name for t in (await session.list_tools()).tools}

    assert asyncio.run(tool_names()) == set(READ_TOOLS)
    assert "no records were removed by other automation tools." in _methods(repo)

    # 2. Enable AI, register the model, set the policy, assign it.
    _cli(root, "ai", "enable")
    _cli(
        root,
        "actor",
        "add",
        AGENT,
        "Claude Opus",
        "--kind",
        "agent",
        "--model",
        MODEL,
        "--role",
        "screener",
    )
    _cli(root, "ai", "policy", "screening", "suggest")
    _cli(root, "assign", STAGE, "--actors", f"ethan,{AGENT}", "--by", "ethan")
    _verify(root)
    repo = open_repo(root)
    assert repo.schema_version == 2
    assert "AI participation is on (screening: suggest)" in _cli(root, "status", why=None)
    assert not ledger_mod.compute_ledger(repo).used
    assert "AI" not in _methods(repo)  # registered, enabled and idle: nothing to disclose

    # 3. It suggests; nothing in the review moves.
    before = {"counts": _counts(repo), "derived": (root / "derived" / "counts.json").read_bytes()}
    result = _agent(root, "screen_record", stage=STAGE, record=ids[0], decision="include")
    assert result["recorded"] == "suggestion"
    repo = open_repo(root)
    pool_mod.regenerate_all(repo)
    assert _counts(repo) == before["counts"]
    assert (root / "derived" / "counts.json").read_bytes() == before["derived"]
    methods = _methods(repo)
    assert (
        "in suggest mode made 1 screening suggestion, of which 0 adopted and 0 rejected by a person, 1 not acted on"
        in methods
    )
    assert "a person reviewed every suggestion before any took effect" in methods
    assert "by two reviewers (ethan and sam) working independently" in methods

    # 4. A person decides, then adopts: the decision is theirs, linked to the idea.
    screening_mod.record_screen_decision(
        repo, stage=STAGE, record_id=ids[0], decision="include", actor="ethan"
    )
    pool_mod.regenerate_all(repo)
    (pending,) = sugg.pending(open_repo(root))
    _cli(
        root,
        "suggestions",
        "adopt",
        pending.id,
        "--by",
        "ethan",
        why="Agree: it reports a recall outcome.",
    )
    repo = open_repo(root)
    adopted = sugg.get_suggestion(repo, pending.id)
    assert adopted.status == "adopted" and len(adopted.result) == 1
    message = gitio.commit_message(root, "HEAD")
    assert f"Strata-Suggestion: {pending.id}" in message and "Strata-Agent" not in message
    assert "of which 1 adopted and 0 rejected by a person" in _methods(repo)
    _verify(root)

    # 5. Count mode: the assigned model is a second reviewer.
    _cli(root, "ai", "policy", "screening", "count")
    for record in ids[1:3]:
        _agent(root, "screen_record", stage=STAGE, record=record, decision="include")
    commit = gitio.run(["log", "-1", "--format=%an|%ae|%cn"], cwd=root).stdout.strip().split("|")
    assert commit[0] == f"{AGENT} (via sam)" and commit[1] == f"{AGENT}@agents.invalid"
    assert commit[2] != commit[0]
    last = gitio.commit_message(root, "HEAD")
    for trailer in (f"Strata-Agent: {AGENT}", "Strata-Invoked-By: sam", "Strata-Via: mcp"):
        assert trailer in last
    agent_events = [
        e
        for path in repo.path("events", "screen").glob(f"{STAGE}.{AGENT}.ndjson")
        for e in events_mod.read_events(path)
    ]
    assert len(agent_events) == 2 and all(e["agent"]["model"] == MODEL for e in agent_events)

    # 6. One agreement, one conflict.
    repo = open_repo(root)
    screening_mod.record_screen_decision(
        repo, stage=STAGE, record_id=ids[1], decision="include", actor="ethan"
    )
    screening_mod.record_screen_decision(
        repo, stage=STAGE, record_id=ids[2], decision="exclude", actor="ethan", cited=["EXC-01"]
    )
    pool_mod.regenerate_all(repo)
    ops_mod.commit_domain_work(
        repo, op="screen", scope=STAGE, summary="screened 2 records", actor="ethan", rationale=WHY
    )
    repo = open_repo(root)
    assert screening_mod.resolve_record_state(repo, STAGE, ids[1]).status == "include"
    assert screening_mod.resolve_record_state(repo, STAGE, ids[2]).status == "conflict"
    assert _counts(repo) == _counts(open_repo(root))  # the counts still close with an AI opinion in
    pairs = _pairs(repo)
    assert pairs[(AGENT, "ethan")] is True  # the pair that involves the model is labelled
    irr_json = json.loads((root / "derived" / "irr.json").read_text())
    assert [
        p.get("involves_agent") for p in irr_json[STAGE] if AGENT in (p["actor_a"], p["actor_b"])
    ] == [True]
    methods = _methods(repo)
    assert (
        "by two people (ethan and sam) and one AI model (claude-opus-5-5) working independently"
        in methods
    )
    assert "2 of them as a reviewer whose opinion counted toward a record's resolution" in methods
    assert f"Agreement between {AGENT} (an AI model) and ethan" in methods
    _verify(root)

    # 7. A person adjudicates the conflict.
    adjudication_mod.record_adjudication(
        repo,
        stage=STAGE,
        record_id=ids[2],
        decision="exclude",
        actor="ethan",
        rationale="Not an empirical study.",
        cited=["EXC-01"],
    )
    pool_mod.regenerate_all(repo)
    ops_mod.commit_domain_work(
        repo,
        op="adjudicate",
        scope=STAGE,
        summary="adjudicated 1 conflict(s)",
        actor="ethan",
        rationale=WHY,
    )
    repo = open_repo(root)
    assert screening_mod.resolve_record_state(repo, STAGE, ids[2]).status == "exclude"
    screening_ledger = ledger_mod.compute_ledger(repo).agents[0].kinds["screening"]
    assert (screening_ledger.counted, screening_ledger.changed_by_people) == (2, 1)
    assert "later changed by a person" in _methods(repo)
    report = _cli(root, "ai", "report", why=None)
    assert "counted 2 (2 as a reviewer, 1 later changed by a person)" in report

    # 8. The lead revokes it: the decision that still counted waits for people.
    assert rescreen_mod.compute_stale_records(repo) == []
    out = _cli(
        root, "ai", "revoke", AGENT, "--by", "ethan", why="We no longer want AI in this review."
    )
    assert "1 decision(s) now wait in the stale queue" in out
    repo = open_repo(root)
    stale = rescreen_mod.compute_stale_records(repo)
    assert [(s.record_id, s.stage, s.reason) for s in stale] == [(ids[1], STAGE, "agent-revoked")]
    assert "agent-revoked" in (root / "derived" / "stale.tsv").read_text()
    assert next(a for a in repo.config["actors"] if a["handle"] == AGENT)["role"] == "inactive"
    assert len(agent_events) == len(  # its history is untouched
        events_mod.read_events(repo.path("events", "screen", f"{STAGE}.{AGENT}.ndjson"))
    )
    assert "Strata-Op: ai-revoke" in gitio.commit_message(root, "HEAD")
    assert "deactivated" in _refused_text(
        root, "screen_record", stage=STAGE, record=ids[3], decision="include"
    )
    final = _methods(repo)
    assert (
        "claude-opus-5-5" in final and "[revoked]" not in final
    )  # still disclosed: it did take part
    assert "[revoked]" in _cli(root, "ai", "report", why=None)
    _verify(root)
