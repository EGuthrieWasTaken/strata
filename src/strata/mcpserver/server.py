"""The local, stdio MCP server (openspec:mcp-server).

A fourth thin presentation layer alongside the CLI (`strata.cli.main`) and
the web UI (`strata.web.routes`), calling directly into existing
`core`/`protocol` functions rather than adding any new domain logic -- the
same relationship `web.routes` already has to the logic behind `strata
screen`. Runs over stdio, spawned locally by an MCP-aware client against a
local clone, exactly like the CLI does today: no new infrastructure.

**Scope is deliberately read/analysis/preview only**: `status`, `why`,
`log`, `records` (the `--filter` language), `criteria_diff`, and the
criteria editor's own non-mutating impact preview
(`preview_criterion_change_impact`). Tools that record a screening or
criteria decision are deliberately **not** exposed here -- `strata`'s
entire premise is that a screening decision is an accountable human
judgement call, and a tool letting an agent record one unsupervised would
undermine the provenance chain the rest of the tool exists to keep
honest. No method on `RepoTools` below mutates the repository; there is
nothing in this module a future write-capable tool could layer onto
without first deciding how a drafted decision gets to a human for review,
which is explicitly out of scope for this milestone.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from strata.core import filters as filters_mod
from strata.core import logcmd as logcmd_mod
from strata.core import provenance as provenance_mod
from strata.core import records as records_mod
from strata.core import status as status_mod
from strata.core.repo import Repo, open_repo
from strata.protocol import criteria as criteria_mod
from strata.protocol import rescreen as rescreen_mod

_INSTRUCTIONS = (
    "Read-only tools over a local strata systematic-review repository. None of "
    "these tools write anything: a screening or criteria decision is a human "
    "reviewer's accountable judgement call, recorded only through `strata "
    "screen`/`strata criteria`/`strata adjudicate` or the web UI, never by an "
    "agent acting unsupervised."
)


class RepoTools:
    """The marshalling layer between MCP tool calls and `core`/`protocol`
    functions, bound to one repository root for the server process's
    lifetime.

    Every method opens the repository fresh on each call (matching
    `strata.web.app.AppState.open_repo`'s own contract: a human may edit the
    repository through the CLI or web UI between two MCP calls, and every
    read should reflect the current working tree, not a snapshot from
    server startup). Kept independent of the `mcp` package so it is
    unit-testable without going through MCP tool registration or the stdio
    transport at all, the same reasoning `web.server` is kept separate from
    `web.app` for.
    """

    def __init__(self, repo_root: Path) -> None:
        self._repo_root = repo_root

    def _open(self) -> Repo:
        return open_repo(self._repo_root)

    def status(self) -> dict[str, Any]:
        """Project dashboard: identity, actor/commit/record counts, criteria
        version, and per-stage screening status -- the data behind `strata
        status`."""
        return dataclasses.asdict(status_mod.compute_status(self._open()))

    def why(self, record_id: str) -> list[dict[str, Any]]:
        """Full provenance for one record: search, import, amendments, and
        dedup history -- the data behind `strata why <record_id>`.
        `record_id` may be any unambiguous id prefix, as in git."""
        repo = self._open()
        try:
            resolved_id = records_mod.resolve_id_prefix(repo, record_id)
        except (records_mod.RecordNotFoundError, records_mod.AmbiguousRecordIdError) as exc:
            raise ToolError(str(exc)) from exc
        entries = provenance_mod.build_provenance(repo, resolved_id)
        return [{"kind": e.kind, "ts": e.ts, "actor": e.actor, "detail": e.detail} for e in entries]

    def log(
        self,
        criteria: bool = False,
        stage: str | None = None,
        actor: str | None = None,
    ) -> list[dict[str, Any]]:
        """Domain-level commit history read from `Strata-` commit trailers,
        not raw commit messages -- the data behind `strata log`."""
        commits = logcmd_mod.domain_log(
            self._open(), criteria_only=criteria, stage=stage, actor=actor
        )
        return [{"sha": c.sha, "subject": c.subject, "trailers": c.trailers} for c in commits]

    def records(
        self,
        filter_expr: str | None = None,
        all_records: bool = False,
    ) -> list[dict[str, Any]]:
        """List bibliographic records, optionally narrowed by the `--filter`
        expression language (openspec:filter-language) -- the data behind
        `strata records list`. Duplicates absorbed by deduplication are
        excluded unless `all_records` is set."""
        repo = self._open()
        result = records_mod.read_records(repo)
        if not all_records:
            result = [r for r in result if r.get("strata", {}).get("canonical", True)]
        if filter_expr:
            try:
                ast = filters_mod.parse(filter_expr)
            except filters_mod.FilterSyntaxError as exc:
                raise ToolError(f"invalid filter: {exc}") from exc
            matched = []
            for record in result:
                try:
                    if filters_mod.evaluate(ast, records_mod.record_field_resolver(record)):
                        matched.append(record)
                except filters_mod.FilterEvaluationError as exc:
                    raise ToolError(f"filter failed on record {record['id']}: {exc}") from exc
            result = matched
        return result

    def criteria_diff(self, v1: int, v2: int) -> list[dict[str, Any]]:
        """What changed between two criteria versions -- the data behind
        `strata criteria diff <v1> <v2>`."""
        try:
            return criteria_mod.diff_versions(self._open(), v1, v2)
        except criteria_mod.CriteriaError as exc:
            raise ToolError(str(exc)) from exc

    def preview_criterion_change_impact(
        self,
        criterion_id: str,
        direction: str,
        origin: str = "edited",
    ) -> list[dict[str, Any]]:
        """Non-mutating preview of what changing one criterion this way
        would stale, without writing anything -- the same computation
        behind the web criteria editor's live impact panel
        (openspec:web-ui#criteria-editor-impact-preview). `direction` is one of `tightened`,
        `loosened`, `both`, or `editorial`; pass `origin="retired"` to
        preview a retirement instead of an edit (direction is then
        ignored, matching `strata criteria retire`'s own behaviour)."""
        try:
            stale = rescreen_mod.preview_criterion_change_impact(
                self._open(),
                criterion_id=criterion_id,
                direction=direction,
                origin=origin,
            )
        except rescreen_mod.RescreenError as exc:
            raise ToolError(str(exc)) from exc
        return [dataclasses.asdict(s) for s in stale]


def create_mcp_server(*, repo_root: Path) -> MCPServer:
    """Build the stdio MCP server for the repository at `repo_root`.

    Every tool is registered straight off a bound `RepoTools` method, so
    the tool's parameter schema is exactly that method's signature (`self`
    excluded, as for any bound method) and its description is exactly that
    method's docstring -- no separate schema to keep in sync by hand.
    """
    mcp: MCPServer[None] = MCPServer("strata", instructions=_INSTRUCTIONS)
    tools = RepoTools(repo_root)

    mcp.tool()(tools.status)
    mcp.tool()(tools.why)
    mcp.tool()(tools.log)
    mcp.tool()(tools.records)
    mcp.tool()(tools.criteria_diff)
    mcp.tool()(tools.preview_criterion_change_impact)

    return mcp
