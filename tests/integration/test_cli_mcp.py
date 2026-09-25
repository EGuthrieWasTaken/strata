"""`strata mcp`: docs/spec/15-roadmap.md, M2.1.

Like `strata serve` (`tests/integration/test_cli_serve.py`), the stdio MCP
server cannot be driven with `typer.testing.CliRunner` (in-process,
synchronous) since it blocks reading from stdin for the lifetime of the
process. This drives a real subprocess with the MCP Python SDK's own
client transport (`mcp.client.stdio.stdio_client`), so it exercises the
actual CLI wiring end to end: process spawn, the stdio JSON-RPC handshake,
a real tool call, and a clean shutdown -- the parts
`tests/unit/test_mcpserver.py`'s in-process `RepoTools` tests cannot
reach. No `pytest-asyncio` dependency needed: each test is an ordinary
synchronous test function that drives its own `asyncio.run(...)`, the same
pattern `test_cli_serve.py`'s subprocess tests use for `strata serve`.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp_types import CallToolResult
from typer.testing import CliRunner

from strata.cli.main import EXIT_OK, app

runner = CliRunner()


def _init(tmp_path: Path) -> Path:
    root = tmp_path / "review"
    result = runner.invoke(
        app,
        ["init", str(root), "--title", "MCP CLI Test", "--actor", "ethan", "--actor-name", "Ethan"],
    )
    assert result.exit_code == EXIT_OK, result.output
    return root


def _server_params(root: Path) -> StdioServerParameters:
    return StdioServerParameters(
        command=sys.executable,
        args=["-m", "strata.cli.main", "-C", str(root), "mcp"],
    )


async def _call(root: Path, name: str, arguments: dict[str, object]) -> CallToolResult:
    async with (
        stdio_client(_server_params(root)) as (read, write),
        ClientSession(read, write) as session,
    ):
        await session.initialize()
        return await session.call_tool(name, arguments)


def test_mcp_lists_the_scoped_read_only_tools(tmp_path: Path) -> None:
    root = _init(tmp_path)

    async def run() -> set[str]:
        async with (
            stdio_client(_server_params(root)) as (read, write),
            ClientSession(read, write) as session,
        ):
            await session.initialize()
            tools = await session.list_tools()
            return {t.name for t in tools.tools}

    names = asyncio.run(run())
    assert names == {
        "status",
        "why",
        "log",
        "records",
        "criteria_diff",
        "preview_criterion_change_impact",
    }


def test_mcp_status_tool_reflects_the_real_repository(tmp_path: Path) -> None:
    root = _init(tmp_path)
    result = asyncio.run(_call(root, "status", {}))
    assert result.is_error is not True
    assert result.structured_content is not None
    assert result.structured_content["title"] == "MCP CLI Test"
    assert result.structured_content["actor_count"] == 1


def test_mcp_unknown_record_reports_a_tool_error_not_a_crash(tmp_path: Path) -> None:
    """An anticipated failure (`ToolError`, docs/spec/15-roadmap.md M2.1's
    "no domain logic beyond argument marshalling" still needs *some* error
    reporting) comes back as `is_error=True` with a readable message, not
    a raised exception that tears down the session -- confirmed by making
    a second, successful call over the same still-open session afterward."""
    root = _init(tmp_path)

    async def run() -> tuple[CallToolResult, CallToolResult]:
        async with (
            stdio_client(_server_params(root)) as (read, write),
            ClientSession(read, write) as session,
        ):
            await session.initialize()
            failure = await session.call_tool("why", {"record_id": "zzz"})
            success = await session.call_tool("status", {})
            return failure, success

    failure, success = asyncio.run(run())
    assert failure.is_error is True
    assert "no record id starts with" in failure.content[0].text  # type: ignore[union-attr]
    assert success.is_error is not True
