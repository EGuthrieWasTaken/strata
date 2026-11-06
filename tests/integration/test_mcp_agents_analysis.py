"""An analysis an agent ran is disclosed in the Synthesis part of the Methods:
openspec:ai-participation#disclosure-in-generated-text."""

from __future__ import annotations

from pathlib import Path

from strata import gitio
from strata.core import operations as ops_mod
from strata.core.actor import add_actor
from strata.core.repo import open_repo
from strata.report import facts as facts_mod
from strata.report import sections
from tests.integration.test_mcp_agents import WHY, _policy, _write
from tests.unit._m5 import full_review
from tests.unit._m6 import AGENT, MODEL


def test_an_analysis_the_agent_ran_is_named_in_the_synthesis_methods(tmp_path: Path) -> None:
    repo, _ = full_review(tmp_path)
    gitio.add_all(repo.root)
    gitio.commit(repo.root, "test: fixture\n\nStrata-Op: test\nStrata-Actor: ethan")
    ops_mod.enable_ai(repo, rationale=WHY)
    repo = open_repo(repo.root)
    add_actor(repo, handle=AGENT, name="Claude Opus", role="screener", kind="agent", model=MODEL)
    repo = _policy(open_repo(repo.root), analysis="count")

    before = sections.methods(facts_mod.collect(repo))
    assert "### Synthesis" in before and "AI model" not in before.split("### Synthesis")[1]

    ran = _write(repo, "run_analysis", analysis="primary")
    assert ran["recorded"] == "work"

    methods = sections.methods(facts_mod.collect(open_repo(repo.root)))
    synthesis = methods.split("### Synthesis")[1]
    assert MODEL in synthesis and "analysis" in synthesis
