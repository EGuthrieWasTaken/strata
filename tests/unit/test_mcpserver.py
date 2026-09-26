"""Unit tests for `strata.mcpserver.server` (openspec:mcp-server).

Exercises `RepoTools` directly -- the marshalling layer -- without going
through MCP tool registration or the stdio transport at all, the same
"drive the logic, not the protocol" split `tests/unit/test_web_server.py`
uses for `strata.web.server`. The one test that does touch tool
registration (`test_create_mcp_server_registers_exactly_the_scoped_tools`)
confirms the *scope* boundary the roadmap's M2.1 acceptance bullet names:
no MCP tool here can commit a screening or criteria decision.
`tests/integration/test_cli_mcp.py` covers the real stdio subprocess this
file cannot reach in-process.
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
from pathlib import Path

import pytest

from strata.core import manifest as manifest_mod
from strata.core.actor import add_actor
from strata.core.events import append_new_event
from strata.core.init import init_repository
from strata.core.repo import open_repo
from strata.core.status import compute_status
from strata.mcpserver.server import RepoTools, create_mcp_server
from strata.protocol.criteria import add_criterion, read_criteria_doc
from strata.protocol.rescreen import preview_criterion_change_impact
from strata.protocol.screening import record_screen_decision


def _init(tmp_path: Path) -> Path:
    root = tmp_path / "review"
    init_repository(root, title="MCP Test Review", actor_handle="ethan", actor_name="Ethan")
    return root


def _init_single(tmp_path: Path, stages: tuple[str, ...] = ("title-abstract", "full-text")) -> Path:
    """A repo where ethan alone resolves every stage -- the simplest way to
    get a *resolved* decision without a second reviewer, matching
    `tests/unit/test_rescreen.py`'s own helper of the same name."""
    root = _init(tmp_path)
    doc = manifest_mod.load_manifest_doc(root)
    manifest_mod.set_value(doc, "screening.assignment", {s: ["ethan"] for s in stages})
    manifest_mod.write_manifest(root, doc)
    return root


def _add_records(repo, ids: list[str], **overrides) -> None:  # type: ignore[no-untyped-def]
    records_path = repo.path("records", "records.ndjson")
    records_path.parent.mkdir(parents=True, exist_ok=True)
    lines = []
    for rid in ids:
        record = {
            "id": rid,
            "type": "article-journal",
            "title": f"Title for {rid}",
            "strata": {"canonical_key": f"sig:{rid}", "canonical": True, "sources": []},
        }
        record.update(overrides)
        lines.append(json.dumps(record))
    records_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


# --------------------------------------------------------------------- status


def test_status_matches_compute_status(tmp_path: Path) -> None:
    root = _init(tmp_path)
    repo = open_repo(root)
    _add_records(repo, ["rec_0000000000000001"])
    tools = RepoTools(root)
    assert tools.status() == dataclasses.asdict(compute_status(open_repo(root)))


# ------------------------------------------------------------------------ why


def test_why_empty_for_untouched_record(tmp_path: Path) -> None:
    root = _init(tmp_path)
    repo = open_repo(root)
    _add_records(repo, ["rec_0000000000000001"])
    assert RepoTools(root).why("rec_0000000000000001") == []


def test_why_resolves_an_unambiguous_id_prefix(tmp_path: Path) -> None:
    root = _init(tmp_path)
    repo = open_repo(root)
    _add_records(repo, ["rec_0000000000000001"])
    events_path = repo.path("events", "import", "ethan.ndjson")
    append_new_event(
        events_path,
        ev="record-add",
        actor="ethan",
        body={
            "record": "rec_0000000000000001",
            "import_id": "imp_x",
            "raw_row_digest": "sha256:x",
        },
    )
    entries = RepoTools(root).why("rec_00000000000000")
    assert [e["kind"] for e in entries] == ["record-add"]
    assert entries[0]["actor"] == "ethan"
    assert entries[0]["detail"]["import_id"] == "imp_x"


def test_why_unknown_id_prefix_raises_a_clear_error(tmp_path: Path) -> None:
    root = _init(tmp_path)
    with pytest.raises(Exception, match="no record id starts with"):
        RepoTools(root).why("zzz")


def test_why_ambiguous_id_prefix_raises_a_clear_error(tmp_path: Path) -> None:
    root = _init(tmp_path)
    repo = open_repo(root)
    _add_records(repo, ["rec_0000000000000001", "rec_0000000000000002"])
    with pytest.raises(Exception, match="ambiguous|matches"):
        RepoTools(root).why("rec_00000000000000")


# ------------------------------------------------------------------------ log


def test_log_returns_domain_commits_with_trailers(tmp_path: Path) -> None:
    root = _init(tmp_path)
    entries = RepoTools(root).log()
    assert len(entries) == 1
    assert entries[0]["trailers"]["Op"] == "init"
    assert entries[0]["trailers"]["Actor"] == "ethan"
    assert "sha" in entries[0] and "subject" in entries[0]


def test_log_filters_by_actor(tmp_path: Path) -> None:
    root = _init(tmp_path)
    repo = open_repo(root)
    add_actor(repo, handle="sam", name="Sam", role="screener")
    tools = RepoTools(root)
    assert all(e["trailers"].get("Actor") == "ethan" for e in tools.log(actor="ethan"))
    assert tools.log(actor="nobody") == []


# -------------------------------------------------------------------- records


def test_records_excludes_absorbed_duplicates_by_default(tmp_path: Path) -> None:
    root = _init(tmp_path)
    repo = open_repo(root)
    records_path = repo.path("records", "records.ndjson")
    records_path.parent.mkdir(parents=True, exist_ok=True)
    records_path.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "id": "rec_0000000000000001",
                        "type": "article-journal",
                        "title": "Canonical",
                        "strata": {"canonical_key": "sig:1", "canonical": True, "sources": []},
                    }
                ),
                json.dumps(
                    {
                        "id": "rec_0000000000000002",
                        "type": "article-journal",
                        "title": "Absorbed",
                        "strata": {"canonical_key": "sig:x", "canonical": False, "sources": []},
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    tools = RepoTools(root)
    ids = {r["id"] for r in tools.records()}
    assert ids == {"rec_0000000000000001"}
    all_ids = {r["id"] for r in tools.records(all_records=True)}
    assert all_ids == {"rec_0000000000000001", "rec_0000000000000002"}


def test_records_filter_expr_narrows_results(tmp_path: Path) -> None:
    root = _init(tmp_path)
    repo = open_repo(root)
    records_path = repo.path("records", "records.ndjson")
    records_path.parent.mkdir(parents=True, exist_ok=True)
    records_path.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "id": "rec_0000000000000001",
                        "type": "article-journal",
                        "title": "Alpha",
                        "strata": {"canonical_key": "sig:1", "canonical": True, "sources": []},
                    }
                ),
                json.dumps(
                    {
                        "id": "rec_0000000000000002",
                        "type": "article-journal",
                        "title": "Beta",
                        "strata": {"canonical_key": "sig:2", "canonical": True, "sources": []},
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    tools = RepoTools(root)
    matched = tools.records(filter_expr="title == 'Alpha'")
    assert [r["id"] for r in matched] == ["rec_0000000000000001"]


def test_records_invalid_filter_syntax_raises_a_clear_error(tmp_path: Path) -> None:
    root = _init(tmp_path)
    with pytest.raises(Exception, match="invalid filter"):
        RepoTools(root).records(filter_expr="not a valid filter (((")


def test_records_filter_evaluation_error_raises_a_clear_error(tmp_path: Path) -> None:
    root = _init(tmp_path)
    repo = open_repo(root)
    _add_records(repo, ["rec_0000000000000001"])
    with pytest.raises(Exception, match="not available yet"):
        RepoTools(root).records(filter_expr="tiab == 'include'")


# -------------------------------------------------------------- criteria_diff


def test_criteria_diff_returns_deltas_between_versions(tmp_path: Path) -> None:
    root = _init(tmp_path)
    repo = open_repo(root)
    add_criterion(
        repo,
        kind="exclusion",
        label="Not empirical",
        definition="Not an original empirical study.",
        applies_at=["title-abstract"],
        actor="ethan",
        rationale="Establishing the initial protocol criteria.",
        criterion_id="EXC-01",
    )
    deltas = RepoTools(root).criteria_diff(0, 1)
    assert len(deltas) == 1
    assert deltas[0]["id"] == "EXC-01"
    assert deltas[0]["origin"] == "added"


def test_criteria_diff_invalid_range_raises_a_clear_error(tmp_path: Path) -> None:
    root = _init(tmp_path)
    with pytest.raises(Exception, match="must be greater than"):
        RepoTools(root).criteria_diff(2, 1)


# ------------------------------------------ preview_criterion_change_impact


def test_preview_matches_the_real_rescreen_preview(tmp_path: Path) -> None:
    root = _init_single(tmp_path)
    repo = open_repo(root)
    _add_records(repo, ["rec_0000000000000001"])
    add_criterion(
        repo,
        kind="exclusion",
        label="Not in English",
        definition="Not in English.",
        applies_at=["title-abstract"],
        actor="ethan",
        rationale="Establishing the initial protocol criteria.",
        criterion_id="EXC-01",
    )
    record_screen_decision(
        repo,
        stage="title-abstract",
        record_id="rec_0000000000000001",
        decision="exclude",
        actor="ethan",
        cited=["EXC-01"],
    )

    via_tools = RepoTools(root).preview_criterion_change_impact(
        criterion_id="EXC-01", direction="loosened"
    )
    via_protocol = preview_criterion_change_impact(
        open_repo(root), criterion_id="EXC-01", direction="loosened"
    )
    assert via_tools == [dataclasses.asdict(s) for s in via_protocol]
    assert len(via_tools) == 1
    assert via_tools[0]["reason"] == "criterion-loosened"


def test_preview_does_not_mutate_criteria_version(tmp_path: Path) -> None:
    root = _init_single(tmp_path)
    repo = open_repo(root)
    _add_records(repo, ["rec_0000000000000001"])
    add_criterion(
        repo,
        kind="exclusion",
        label="Not in English",
        definition="Not in English.",
        applies_at=["title-abstract"],
        actor="ethan",
        rationale="Establishing the initial protocol criteria.",
        criterion_id="EXC-01",
    )
    tools = RepoTools(root)
    tools.preview_criterion_change_impact(criterion_id="EXC-01", direction="loosened")
    tools.preview_criterion_change_impact(criterion_id="EXC-01", direction="tightened")
    assert int(read_criteria_doc(open_repo(root))["version"]) == 1


def test_preview_unknown_criterion_raises_a_clear_error(tmp_path: Path) -> None:
    root = _init(tmp_path)
    with pytest.raises(Exception, match="no criterion"):
        RepoTools(root).preview_criterion_change_impact(criterion_id="EXC-99", direction="loosened")


# ------------------------------------------------------------- create_mcp_server


def test_create_mcp_server_registers_exactly_the_scoped_read_only_tools(tmp_path: Path) -> None:
    """The roadmap's M2.1 acceptance bullet: the MCP server exposes only
    read/analysis/preview tools, and no tool commits a screening or
    criteria decision -- checked here at the registration boundary
    (matching what tool *names* are exposed at all), not just by every
    `RepoTools` method above never calling a mutating `protocol` function."""
    root = _init(tmp_path)
    mcp = create_mcp_server(repo_root=root)
    tools = asyncio.run(mcp.list_tools())
    names = {t.name for t in tools}
    assert names == {
        "status",
        "why",
        "log",
        "records",
        "criteria_diff",
        "preview_criterion_change_impact",
    }
    for banned in ("screen", "assign", "adjudicate", "criteria_add", "criteria_edit", "rescreen"):
        assert banned not in names
