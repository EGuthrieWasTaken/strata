"""Requirement-traceability report: docs/spec/14-testing.md §10.5.

Collects every `@pytest.mark.req(...)` marker across the whole test suite
and reports which of the specification's identified requirements -- the
property invariants P1-P13 (§2), the end-to-end scenarios E2E-01-E2E-12
(§5), and the `E_*` cross-schema validation error codes
(docs/spec/03-schemas.md §10) -- have no test naming them.

Run: uv run python scripts/traceability_report.py
Writes `build/traceability-report.md` (a CI build artefact, per §10.5's own
wording -- not committed, since unlike the dedup benchmark's result this
changes with every test added and would otherwise go stale in the repo) and
exits non-zero once every requirement below is covered: "once every current
requirement is covered, an uncovered requirement becomes a gate failure
rather than a warning" -- until then, a nonzero exit here is advisory
(`.github/workflows/ci.yml`'s `traceability` job does not fail the build on
it, only uploads the report).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
REPORT_PATH = REPO_ROOT / "build" / "traceability-report.md"

# docs/spec/14-testing.md §2.
PROPERTY_INVARIANTS = [f"P{i}" for i in range(1, 14)]
# docs/spec/14-testing.md §5 / docs/spec/15-roadmap.md's M0 acceptance bar.
E2E_SCENARIOS = [f"E2E-{i:02d}" for i in range(1, 13)]
# docs/spec/03-schemas.md §10's cross-schema validation table, in that order.
ERROR_CODES = [
    "E_SCHEMA",
    "E_DANGLING_REF",
    "E_ALIAS_CYCLE",
    "E_CHAIN",
    "E_DERIVED_DRIFT",
    "E_CRITERION_REUSE",
    "E_EXCLUSION_NO_CRITERION",
    "E_CRITERION_STAGE",
    "E_ORPHAN_EXTRACTION",
    "E_MISSING_EXTRACTION",
    "E_COUNT_RECONCILE",
    "E_UNIT",
    "E_EFFECT_INPUTS",
]
ALL_REQUIREMENTS = [*PROPERTY_INVARIANTS, *E2E_SCENARIOS, *ERROR_CODES]


class _MarkerCollector:
    """A pytest plugin, registered ad hoc for one `--collect-only` run, that
    records every `@pytest.mark.req(...)` id and which test(s) declared it."""

    def __init__(self) -> None:
        self.covered: dict[str, list[str]] = {}

    def pytest_collection_modifyitems(self, items: list[pytest.Item]) -> None:
        for item in items:
            marker = item.get_closest_marker("req")
            if marker is None:
                continue
            for req_id in marker.args:
                self.covered.setdefault(str(req_id), []).append(item.nodeid)


def collect_coverage() -> dict[str, list[str]]:
    collector = _MarkerCollector()
    exit_code = pytest.main(["--collect-only", "-q", str(REPO_ROOT / "tests")], plugins=[collector])
    if exit_code not in (pytest.ExitCode.OK, pytest.ExitCode.NO_TESTS_COLLECTED):
        raise SystemExit(f"pytest collection failed (exit code {int(exit_code)})")
    return collector.covered


def render_report(covered: dict[str, list[str]]) -> tuple[str, bool]:
    uncovered = [r for r in ALL_REQUIREMENTS if r not in covered]
    unrecognised = sorted(r for r in covered if r not in ALL_REQUIREMENTS)
    all_covered = not uncovered

    lines = [
        "# Requirement traceability report",
        "",
        "docs/spec/14-testing.md §10.5: every identified requirement (property",
        "invariants, end-to-end scenarios, cross-schema error codes) should have",
        "at least one test that names it via `@pytest.mark.req(...)`.",
        "",
        f"**{len(covered) - len(unrecognised)}/{len(ALL_REQUIREMENTS)} covered.**",
        "",
    ]

    def _section(title: str, ids: list[str]) -> None:
        lines.append(f"## {title}")
        lines.append("")
        lines.append("| Requirement | Status | Tests |")
        lines.append("|---|---|---|")
        for req_id in ids:
            tests = covered.get(req_id)
            status = "covered" if tests else "**UNCOVERED**"
            test_list = ", ".join(f"`{t}`" for t in tests) if tests else ""
            lines.append(f"| {req_id} | {status} | {test_list} |")
        lines.append("")

    _section("Property invariants (P1-P13)", PROPERTY_INVARIANTS)
    _section("End-to-end scenarios (E2E-01-E2E-12)", E2E_SCENARIOS)
    _section("Cross-schema error codes (E_*)", ERROR_CODES)

    if unrecognised:
        lines.append("## Unrecognised ids")
        lines.append("")
        lines.append(
            "Tests reference these `@pytest.mark.req(...)` ids, which this script "
            "doesn't recognise -- likely a typo, or a new requirement added to the "
            "spec that needs adding to `scripts/traceability_report.py` too:"
        )
        lines.append("")
        for req_id in unrecognised:
            lines.append(f"- `{req_id}`: {', '.join(covered[req_id])}")
        lines.append("")

    if uncovered:
        lines.append(f"**Uncovered:** {', '.join(uncovered)}")
    else:
        lines.append("**Every identified requirement is covered.**")

    return "\n".join(lines) + "\n", all_covered


def main() -> None:
    covered = collect_coverage()
    report, all_covered = render_report(covered)
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(report, encoding="utf-8")
    print(report)
    if not all_covered:
        sys.exit(1)


if __name__ == "__main__":
    main()
