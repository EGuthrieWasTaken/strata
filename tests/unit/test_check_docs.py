"""Unit tests for scripts/check_docs.py: openspec:ci-gate#specification-integrity-checks."""

from __future__ import annotations

from pathlib import Path

import pytest
from scripts import check_docs

SPEC = """# staleness Specification

## Purpose

Decides which screening decisions a criteria change invalidates.

Rationale and worked examples: [design.md](design.md).

## Requirements

### Requirement: The staleness rules

The engine MUST mark exactly the decisions the rules select.

#### Scenario: Criterion added

- **WHEN** a criterion is added
- **THEN** inclusions go stale
"""

# Deliberately unresolvable references are built by concatenation so the
# real check over this repository does not flag this file.
REF = "openspec" + ":"

README = """# OpenSpec

| Capability | Covers |
|---|---|
| [staleness](specs/staleness/spec.md) | The flagship |
"""


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A minimal, fully valid repository layout."""
    cap = tmp_path / "openspec" / "specs" / "staleness"
    cap.mkdir(parents=True)
    (cap / "spec.md").write_text(SPEC, encoding="utf-8")
    (cap / "design.md").write_text(
        "# Design\n\nSee [the rules](spec.md#requirement-the-staleness-rules).\n",
        encoding="utf-8",
    )
    (tmp_path / "openspec" / "README.md").write_text(README, encoding="utf-8")
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "roadmap.md").write_text(
        "# Roadmap\n\n```yaml\nmilestone: M5.1\n```\n", encoding="utf-8"
    )
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "engine.py").write_text(
        "# Implements openspec:staleness#the-staleness-rules and openspec:staleness.\n",
        encoding="utf-8",
    )
    return tmp_path


def test_valid_repository_passes(repo: Path) -> None:
    assert check_docs.run_all(repo) == []


def test_requirement_slug_matches_the_documented_rule() -> None:
    assert check_docs.requirement_slug("The staleness rules") == "the-staleness-rules"
    assert (
        check_docs.requirement_slug("Records, reports, and studies are distinct entities")
        == "records-reports-and-studies-are-distinct-entities"
    )


def test_broken_link_is_reported(repo: Path) -> None:
    (repo / "docs" / "overview.md").write_text("[gone](missing.md)\n", encoding="utf-8")
    errors = check_docs.check_links_and_anchors(repo)
    assert errors == ["docs/overview.md: broken link target 'missing.md'"]


def test_broken_anchor_is_reported(repo: Path) -> None:
    design = repo / "openspec" / "specs" / "staleness" / "design.md"
    design.write_text("[x](spec.md#requirement-renamed-away)\n", encoding="utf-8")
    [error] = check_docs.check_links_and_anchors(repo)
    assert "requirement-renamed-away" in error


def test_links_inside_code_fences_are_ignored(repo: Path) -> None:
    (repo / "docs" / "overview.md").write_text("```\n[m](merge)\n```\n", encoding="utf-8")
    assert check_docs.check_links_and_anchors(repo) == []


def test_invalid_fenced_block_is_reported(repo: Path) -> None:
    (repo / "docs" / "roadmap.md").write_text("```json\n{not json\n```\n", encoding="utf-8")
    [error] = check_docs.check_fenced_blocks(repo)
    assert error.startswith("docs/roadmap.md:1: invalid json block")


def test_capability_without_design_is_reported(repo: Path) -> None:
    (repo / "openspec" / "specs" / "staleness" / "design.md").unlink()
    assert check_docs.check_capability_index(repo) == [
        "openspec/specs/staleness: missing design.md"
    ]


def test_unlisted_and_phantom_capabilities_are_reported(repo: Path) -> None:
    extra = repo / "openspec" / "specs" / "screening"
    extra.mkdir()
    (extra / "spec.md").write_text(SPEC, encoding="utf-8")
    (extra / "design.md").write_text("# Design\n", encoding="utf-8")
    readme = repo / "openspec" / "README.md"
    readme.write_text(README + "| [gone](specs/gone/spec.md) | x |\n", encoding="utf-8")
    assert check_docs.check_capability_index(repo) == [
        "openspec/README.md: capability 'screening' is not listed",
        "openspec/README.md: lists capability 'gone', which does not exist",
    ]


def test_unknown_capability_reference_is_reported(repo: Path) -> None:
    (repo / "src" / "engine.py").write_text(f"# {REF}stalenes\n", encoding="utf-8")
    assert check_docs.check_openspec_references(repo) == [
        f"src/engine.py:1: unknown capability in '{REF}stalenes'"
    ]


def test_unknown_requirement_reference_is_reported(repo: Path) -> None:
    (repo / "src" / "engine.py").write_text(f"# {REF}staleness#the-old-rules\n", encoding="utf-8")
    assert check_docs.check_openspec_references(repo) == [
        f"src/engine.py:1: unknown requirement in '{REF}staleness#the-old-rules'"
    ]


def test_references_resolve_against_change_delta_specs(repo: Path) -> None:
    delta = repo / "openspec" / "changes" / "add-analysis" / "specs" / "effect-sizes"
    delta.mkdir(parents=True)
    (delta / "spec.md").write_text(
        "## ADDED Requirements\n\n### Requirement: Raw mean difference\n", encoding="utf-8"
    )
    (repo / "src" / "engine.py").write_text(
        "# openspec:effect-sizes#raw-mean-difference\n", encoding="utf-8"
    )
    assert check_docs.check_openspec_references(repo) == []


def test_retired_directory_reference_is_reported(repo: Path) -> None:
    retired = check_docs.RETIRED_SPEC_DIR
    (repo / "src" / "engine.py").write_text(f"# see {retired}06.md\n", encoding="utf-8")
    [error] = check_docs.check_no_retired_references(repo)
    assert error.startswith("src/engine.py:1: refers to the retired")


def test_historical_files_are_exempt(repo: Path) -> None:
    retired = check_docs.RETIRED_SPEC_DIR
    (repo / "docs" / "m1-plan.md").write_text(
        f"Cites {retired}05.md and [gone](gone.md) and {REF}nothing.\n", encoding="utf-8"
    )
    (repo / "CHANGELOG.md").write_text(f"Retired {retired}.\n", encoding="utf-8")
    assert check_docs.run_all(repo) == []
