"""Every mutating command is available to agents or reserved for people, and the test says which:
openspec:ai-participation#operations-an-agent-cannot-perform.

A new mutating command fails this test until someone decides, so it can neither become reachable
by agents, nor silently unreachable, by omission (openspec:ai-participation design D8).
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterable, Iterator

import click
import pytest
from mcp import Client
from typer.main import get_command

from strata.cli.main import app
from strata.core import agent_ops  # noqa: F401  (registers the analysis operations)
from strata.mcpserver.server import READ_TOOLS, WRITE_TOOLS, create_mcp_server
from strata.protocol import suggestions as sugg
from tests.unit._m6 import ai_review

#: A command an agent can perform, and the write tool(s) that perform it.
AGENT_COMMANDS: dict[str, tuple[str, ...]] = {
    "screen": ("screen_record",),
    "rescreen": ("screen_record",),  # a re-screen is a new screening decision
    "adjudicate": ("adjudicate_conflict",),
    "extract": ("set_extraction_field",),
    "rob": ("record_risk_of_bias",),
    "retrieve": ("record_retrieval",),
    "studies": ("group_reports", "split_report"),
    "fix": ("correct_record", "add_note"),
    "dedup": ("decide_duplicate",),
    "search add": ("record_search",),
    "import": ("import_records",),
    "criteria add": ("add_criterion",),
    "criteria edit": ("edit_criterion",),
    "criteria retire": ("retire_criterion",),
    "analyze": ("run_analysis",),
    "prisma": ("draw_prisma",),
}

#: Commands that change who counts, what is allowed, or reach outside the review: for people only.
RESERVED_FOR_PEOPLE = frozenset(
    {
        "ai enable",  # the policy and whether AI takes part at all
        "ai policy",
        "ai revoke",
        "actor add",  # registering, deactivating or re-roling an actor
        "actor deactivate",
        "assign",  # assignment decides who counts
        "config",
        "init",
        "clone",
        "doctor",  # repairing hooks and merge drivers
        "sync",  # synchronising with a remote
        "merge-records",
        "merge-regenerate",
        "migrate",
        "suggestions adopt",  # adopting or rejecting is a person's act
        "suggestions reject",
        "zotero link",  # an external service and its credentials
        "zotero pull",
        "zotero push",
        "export bibliography",  # writes files for people outside the review
        "export effects",
        "export package",
        "export provenance",
        "serve",  # starts the web interface for a person
        "mcp",
    }
)

#: Commands that change nothing in the review (or only regenerate what is derived), so there is
#: nothing for an agent to be given or denied; its reads are the MCP read tools.
READ_ONLY = frozenset(
    {
        "actor list",
        "ai report",
        "audit",
        "ci amendment",
        "ci comment",
        "criteria diff",
        "criteria list",
        "diff",
        "irr",
        "log",
        "records list",
        "records show",
        "search list",
        "status",
        "suggestions list",
        "suggestions show",
        "verify",
        "version",
        "why",
        "zotero open",
        "zotero status",
        "internal hook-commit-msg",
        "internal hook-post-checkout",
        "internal hook-post-merge",
        "internal hook-pre-commit",
    }
)

#: A mutating command no tool covers yet. Each one is a gap in
#: `openspec:mcp-server#write-tools`, named here so it cannot be forgotten.
NOT_YET_AVAILABLE_TO_AGENTS = {
    "report": "generating the Methods, Results and checklist text still lives inside the command",
}


def _leaf_commands(command: click.Command, prefix: str = "") -> Iterator[str]:
    commands = getattr(command, "commands", None)
    if not commands:
        return
    for name, sub in sorted(commands.items()):
        if getattr(sub, "commands", None):
            yield from _leaf_commands(sub, f"{prefix}{name} ")
        else:
            yield f"{prefix}{name}"


def unclassified(commands: Iterable[str]) -> list[str]:
    """Commands that are in none of the lists, or in more than one."""
    categories = (
        set(AGENT_COMMANDS),
        RESERVED_FOR_PEOPLE,
        READ_ONLY,
        set(NOT_YET_AVAILABLE_TO_AGENTS),
    )
    return sorted(c for c in commands if sum(c in category for category in categories) != 1)


def test_every_command_is_classified_exactly_once() -> None:
    commands = list(_leaf_commands(get_command(app)))
    assert unclassified(commands) == []


def test_a_new_mutating_command_fails_until_it_is_classified() -> None:
    commands = [*_leaf_commands(get_command(app)), "teleport records"]
    assert unclassified(commands) == ["teleport records"]


def test_a_command_in_two_lists_is_also_caught(monkeypatch: pytest.MonkeyPatch) -> None:
    assert unclassified(["screen"]) == []
    monkeypatch.setattr(
        "tests.unit.test_reserved_operations.RESERVED_FOR_PEOPLE",
        RESERVED_FOR_PEOPLE | {"screen"},
    )
    assert unclassified(["screen"]) == ["screen"]  # an agent command that is also reserved


def test_the_lists_name_no_command_that_does_not_exist() -> None:
    commands = set(_leaf_commands(get_command(app)))
    listed = (
        set(AGENT_COMMANDS) | RESERVED_FOR_PEOPLE | READ_ONLY | set(NOT_YET_AVAILABLE_TO_AGENTS)
    )
    assert listed - commands == {"ai revoke", "ai report"}  # arrive with the ledger (group 4)


def test_every_write_tool_is_the_tool_for_some_command_and_the_other_way_round() -> None:
    from_commands = {tool for tools in AGENT_COMMANDS.values() for tool in tools}
    assert from_commands == set(WRITE_TOOLS)


def test_every_operation_an_agent_can_propose_is_reached_by_a_write_tool() -> None:
    # tool -> operation: the same names the write tools hand to `agent_ops.act`
    operations = {
        "screen_record": "screen",
        "adjudicate_conflict": "adjudicate",
        "set_extraction_field": "extract-field",
        "record_risk_of_bias": "rob-judgement",
        "record_retrieval": "retrieval",
        "group_reports": "study-group",
        "split_report": "study-split",
        "correct_record": "record-amend",
        "add_note": "note",
        "decide_duplicate": "dedup-decide",
        "record_search": "search-add",
        "import_records": "import",
        "add_criterion": "criteria-add",
        "edit_criterion": "criteria-edit",
        "retire_criterion": "criteria-retire",
        "run_analysis": "analyze",
        "draw_prisma": "prisma",
    }
    assert set(operations) == set(WRITE_TOOLS)
    assert set(operations.values()) == set(sugg.OPS)
    assert agent_ops.WRITERS.keys() == sugg.OPS.keys()


def test_with_every_kind_on_count_no_tool_changes_policy_actors_or_standing(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """Scenario: complete list of tools. Every kind of work set to `count`, and still none of the
    tools performs a reserved operation."""
    repo = ai_review(tmp_path, policy=dict.fromkeys(_KINDS, "count"))
    server = create_mcp_server(repo_root=repo.root, invoker="sam")

    async def run() -> list[str]:
        async with Client(server) as session:
            return [t.name for t in (await session.list_tools()).tools]

    names = asyncio.run(run())
    assert set(names) == set(READ_TOOLS) | set(WRITE_TOOLS)
    reserved_words = (
        "policy",
        "actor",
        "assign",
        "config",
        "init",
        "clone",
        "doctor",
        "sync",
        "merge",
        "migrate",
    )
    offending = [n for n in names if any(w in n for w in reserved_words) and n != "ai_policy"]
    assert offending == []
    for tool in names:  # and no tool takes the arguments that would change standing
        assert "handle" not in tool and "role" not in tool


_KINDS = (
    "screening", "extraction", "risk-of-bias", "retrieval", "studies", "dedup", "records",
    "search-import", "criteria", "adjudication", "analysis",
)  # fmt: skip


#: `ai policy` changes the policy and is reserved; the read tool `ai_policy` only reports it.
_READ_VIEWS_OF_RESERVED = {"ai policy"}


@pytest.mark.parametrize("command", sorted(RESERVED_FOR_PEOPLE - _READ_VIEWS_OF_RESERVED))
def test_no_reserved_command_has_a_tool_named_after_it(command: str) -> None:
    flattened = command.replace(" ", "_").replace("-", "_")
    assert flattened not in WRITE_TOOLS and flattened not in READ_TOOLS


def test_the_policy_tool_only_reads_it(tmp_path) -> None:  # type: ignore[no-untyped-def]
    repo = ai_review(tmp_path)
    server = create_mcp_server(repo_root=repo.root, invoker="sam")

    async def run() -> dict[str, object]:
        async with Client(server) as session:
            return {t.name: t.input_schema for t in (await session.list_tools()).tools}

    schema = asyncio.run(run())["ai_policy"]
    assert schema.get("properties", {}) == {}  # type: ignore[union-attr]
    assert "ai_policy" in READ_TOOLS and "ai_policy" not in WRITE_TOOLS
