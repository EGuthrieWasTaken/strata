"""A mutating command that needs a rationale and cannot get one stops before it writes anything.

openspec:git-integration#eliciting-the-rationale: the rationale is elicited at commit time, after the
domain operation has written its files, so a refusal there (exit code 7) used to leave the working
tree dirty with nothing committed. Every scenario below is a mutating command run non-interactively
(`CliRunner`'s stdin is not a TTY) without `--why`: it must exit 7 and leave `git status
--porcelain` empty, and, as a control that the command line really is a mutating one, the same
command must then go through once `--why` is given.
"""

# ruff: noqa: E501
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from strata import gitio
from strata.cli.main import EXIT_OK, EXIT_RATIONALE_REFUSED, EXIT_USAGE, app
from strata.core import records as records_mod
from strata.core.repo import Repo
from strata.ingest.pipeline import import_file
from strata.protocol import criteria as criteria_mod
from strata.protocol.screening import record_screen_decision
from tests.integration.test_cli_analyze import _review as analysis_review
from tests.integration.test_cli_dedup import _AUTO_MERGE_A, _AUTO_MERGE_B
from tests.integration.test_cli_m3 import _full_text_review, _sought
from tests.integration.test_cli_m3_extract import S1, _form_repo, _rob_repo, _screened
from tests.integration.test_cli_m3_extract import _dual_repo as dual_extraction_repo
from tests.unit._m3 import add_records, init_review, record, rpt
from tests.unit._m5 import finished_review, write_csl

runner = CliRunner()
WHY = "Recording this for the review record."
NEEDED = "a rationale is required"


@pytest.fixture(autouse=True)
def _skip_hooks(monkeypatch: pytest.MonkeyPatch) -> None:
    """These tests are about the rationale, not the hooks (tests/unit/test_hooks.py): each commit
    would otherwise start two `strata` processes, which dominates a module of this many cases."""
    monkeypatch.setenv("STRATA_SKIP_HOOKS", "1")


@dataclass
class Scenario:
    """A clean, committed repository and the command (after the global options) to run on it."""

    repo: Repo
    args: tuple[str, ...]
    input: str | None = None  # piped stdin, for the commands that prompt


Build = Callable[[Path], Scenario]


def _commit_all(repo: Repo) -> Repo:
    gitio.add_all(repo.root)
    if gitio.is_dirty(repo.root):
        gitio.commit(repo.root, "test: fixture\n\nStrata-Op: test\nStrata-Actor: ethan")
    return repo


def _porcelain(repo: Repo) -> str:
    return gitio.run(["status", "--porcelain"], cwd=repo.root).stdout


def _head(repo: Repo) -> str:
    return gitio.run(["rev-parse", "HEAD"], cwd=repo.root).stdout.strip()


def _run(scenario: Scenario, *options: str, args: tuple[str, ...] | None = None) -> Any:
    return runner.invoke(
        app,
        [*options, "-C", str(scenario.repo.root), *(args or scenario.args)],
        input=scenario.input,
    )


def _set_require_rationale(repo: Repo, value: bool) -> None:
    result = runner.invoke(
        app, ["-C", str(repo.root), "config", "git.require_rationale", str(value).lower()]
    )
    assert result.exit_code == EXIT_OK, result.output
    _commit_all(repo)


# --- the scenarios: one per mutating command (and mode) -------------------------------------
# Needs a rationale only when `git.require_rationale` is true (the default).


def actor_add(tmp_path: Path) -> Scenario:
    repo = _commit_all(init_review(tmp_path))
    return Scenario(repo, ("actor", "add", "jo", "Jo Example"))


def actor_deactivate(tmp_path: Path) -> Scenario:
    repo = _commit_all(init_review(tmp_path))
    return Scenario(repo, ("actor", "deactivate", "sam"))


def search_add(tmp_path: Path) -> Scenario:
    repo = _commit_all(init_review(tmp_path))
    return Scenario(
        repo,
        (
            "search",
            "add",
            "--database",
            "MEDLINE",
            "--platform",
            "Ovid",
            "--by",
            "ethan",
            "--query",
            "q",
        ),
    )


def import_papers(tmp_path: Path) -> Scenario:
    repo = _commit_all(init_review(tmp_path))
    export = write_csl(tmp_path, "export.json", [1, 2, 3])
    return Scenario(repo, ("import", str(export), "--by", "ethan", "--via", "registry"))


def dedup(tmp_path: Path) -> Scenario:
    repo = init_review(tmp_path)
    for name, text in (("a.json", _AUTO_MERGE_A), ("b.json", _AUTO_MERGE_B)):
        (tmp_path / name).write_text(text, encoding="utf-8")
        import_file(repo, tmp_path / name, imported_by="ethan", via="registry")
    return Scenario(_commit_all(repo), ("dedup", "--by", "ethan"))


def fix(tmp_path: Path) -> Scenario:
    repo = init_review(tmp_path)
    import_file(repo, write_csl(tmp_path, "export.json", [1]), imported_by="ethan", via="registry")
    [record_id] = [r["id"] for r in records_mod.read_records(repo)]
    return Scenario(
        _commit_all(repo),
        ("fix", record_id, "--field", "title", "--value", "A corrected title", "--by", "ethan"),
    )


def screen_decisions(tmp_path: Path) -> Scenario:
    repo = init_review(tmp_path)
    ids = add_records(repo, 2)
    tsv = tmp_path / "decisions.tsv"
    tsv.write_text(
        "record_id\tdecision\tcriteria\tnote\n" + "".join(f"{i}\tinclude\t\t\n" for i in ids),
        encoding="utf-8",
    )
    return Scenario(
        _commit_all(repo), ("screen", "title-abstract", "--by", "ethan", "--decisions", str(tsv))
    )


def screen_interactive(tmp_path: Path) -> Scenario:
    repo = init_review(tmp_path)
    add_records(repo, 1)
    return Scenario(_commit_all(repo), ("screen", "title-abstract", "--by", "ethan"), input="i\n\n")


def assign(tmp_path: Path) -> Scenario:
    repo = init_review(tmp_path)
    add_records(repo, 2)
    return Scenario(
        _commit_all(repo), ("assign", "title-abstract", "--actors", "ethan,sam", "--by", "ethan")
    )


def rescreen_interactive(tmp_path: Path) -> Scenario:
    repo = init_review(tmp_path)
    [record_id] = add_records(repo, 1)
    record_screen_decision(
        repo, stage="title-abstract", record_id=record_id, decision="include", actor="ethan"
    )
    criteria_mod.add_criterion(
        repo, kind="exclusion", label="Older than 2005", definition="Published before 2005.",
        applies_at=["title-abstract"], actor="ethan", rationale="Amendment.",
    )  # fmt: skip
    return Scenario(
        _commit_all(repo),
        ("rescreen", "--stage", "title-abstract", "--by", "ethan"),
        input="k\n",  # keep the previous decision
    )


def retrieve_report(tmp_path: Path) -> Scenario:
    repo = _sought(tmp_path)
    return Scenario(
        repo,
        ("retrieve", "--by", "ethan", "--report", rpt(1), "--outcome", "retrieved",
         "--source", "institutional-access", "--version", "version-of-record"),
    )  # fmt: skip


def retrieve_interactive(tmp_path: Path) -> Scenario:
    return Scenario(_sought(tmp_path), ("retrieve", "--by", "ethan"), input="i\nq\n")


def studies_interactive(tmp_path: Path) -> Scenario:
    repo = _full_text_review(
        tmp_path, [record(1, abstract="NCT00713310"), record(2, abstract="NCT00713310")]
    )
    return Scenario(repo, ("studies", "--by", "ethan"), input="k\n")


def extract_init(tmp_path: Path) -> Scenario:
    repo = _commit_all(init_review(tmp_path))
    return Scenario(repo, ("extract", "init", "--by", "ethan"))


def extract_script(tmp_path: Path) -> Scenario:
    return Scenario(
        _form_repo(tmp_path), ("extract", S1, "--by", "ethan", "--set", "n_total=148 @ Table 1")
    )


def extract_reconcile_item(tmp_path: Path) -> Scenario:
    return Scenario(
        dual_extraction_repo(tmp_path),
        ("extract", "--reconcile", S1, "--by", "ethan", "--item", "field:retention_interval",
         "--choose", "ethan", "--rationale", "The paper says one week in the Methods."),
    )  # fmt: skip


def extract_reconcile_interactive(tmp_path: Path) -> Scenario:
    # accept the agreements, then choose sam for the one disagreement and say why
    return Scenario(
        dual_extraction_repo(tmp_path),
        ("extract", "--reconcile", "--by", "ethan"),
        input="y\nsam\nThe Methods table gives 24 hours.\n",
    )


def rob_init(tmp_path: Path) -> Scenario:
    return Scenario(_form_repo(tmp_path), ("rob", "init", "--instrument", "rob2", "--by", "ethan"))


def rob_script(tmp_path: Path) -> Scenario:
    return Scenario(
        _rob_repo(tmp_path),
        ("rob", S1, "--by", "ethan", "--domain", "D1", "--answer", "1.1=Y", "--answer", "1.2=Y",
         "--answer", "1.3=N", "--judgement", "low", "--support", "Central randomisation"),
    )  # fmt: skip


def analyze(tmp_path: Path) -> Scenario:
    return Scenario(analysis_review(tmp_path), ("analyze", "primary"))


def prisma(tmp_path: Path) -> Scenario:
    repo, _ = finished_review(tmp_path)
    return Scenario(_with_current_counts(repo), ("prisma",))


def report(tmp_path: Path) -> Scenario:
    repo, _ = finished_review(tmp_path)
    return Scenario(_with_current_counts(repo), ("report", "methods"))


def _with_current_counts(repo: Repo) -> Repo:
    """The builders write through the service functions; the CLI keeps derived/counts.json current."""
    from strata.core.repo import open_repo
    from strata.protocol import pool as pool_mod

    pool_mod.regenerate_all(open_repo(repo.root))
    return _commit_all(repo)


CONFIG_DEPENDENT: list[Build] = [
    actor_add,
    actor_deactivate,
    search_add,
    import_papers,
    dedup,
    fix,
    screen_decisions,
    screen_interactive,
    assign,
    rescreen_interactive,
    retrieve_report,
    retrieve_interactive,
    extract_init,
    extract_script,
    extract_reconcile_item,
    extract_reconcile_interactive,
    rob_init,
    rob_script,
    analyze,
    prisma,
    report,
]


# --- the scenarios that need a rationale whatever `git.require_rationale` says --------------
# Criteria changes, adjudications, study decisions and manual staleness record the rationale in
# the event itself (`_get_required_rationale`), so even `--no-commit` cannot do without one.


def criteria_add(tmp_path: Path) -> Scenario:
    repo = _commit_all(init_review(tmp_path))
    return Scenario(
        repo,
        ("criteria", "add", "--kind", "exclusion", "--label", "Not empirical",
         "--definition", "Not an empirical study.", "--applies-at", "title-abstract", "--by", "ethan"),
    )  # fmt: skip


def _with_criterion(tmp_path: Path) -> Repo:
    repo = init_review(tmp_path)
    criteria_mod.add_criterion(
        repo, kind="exclusion", label="Not empirical", definition="Not an empirical study.",
        applies_at=["title-abstract"], actor="ethan", rationale="Protocol.", criterion_id="EXC-01",
    )  # fmt: skip
    return _commit_all(repo)


def criteria_edit(tmp_path: Path) -> Scenario:
    return Scenario(
        _with_criterion(tmp_path),
        (
            "criteria",
            "edit",
            "EXC-01",
            "--direction",
            "editorial",
            "--by",
            "ethan",
            "--label",
            "Not primary research",
        ),
    )


def criteria_retire(tmp_path: Path) -> Scenario:
    return Scenario(_with_criterion(tmp_path), ("criteria", "retire", "EXC-01", "--by", "ethan"))


def rescreen_mark(tmp_path: Path) -> Scenario:
    repo = init_review(tmp_path)
    [record_id] = add_records(repo, 1)
    record_screen_decision(
        repo, stage="title-abstract", record_id=record_id, decision="include", actor="ethan"
    )
    return Scenario(
        _commit_all(repo),
        ("rescreen", "--stage", "title-abstract", "--by", "ethan", "--mark", record_id),
    )


def adjudicate(tmp_path: Path) -> Scenario:
    # Two conflicts: a discussion note on the first is written before the second is adjudicated
    # (which needs the rationale), so a late refusal would leave that note behind.
    repo = init_review(tmp_path)
    for record_id in add_records(repo, 2):
        for actor, decision in (("ethan", "include"), ("sam", "maybe")):
            record_screen_decision(
                repo,
                stage="title-abstract",
                record_id=record_id,
                decision=decision,
                actor=actor,  # type: ignore[arg-type]
            )
    return Scenario(
        _commit_all(repo),
        ("adjudicate", "--by", "ethan"),
        input="d\nWe disagree about the population here.\ni\n",
    )


def studies_group(tmp_path: Path) -> Scenario:
    return Scenario(
        _full_text_review(tmp_path, 3),
        ("studies", "--by", "ethan", "--group", rpt(1), "--group", rpt(2)),
    )


ALWAYS_REQUIRED: list[Build] = [
    criteria_add,
    criteria_edit,
    criteria_retire,
    rescreen_mark,
    adjudicate,
    studies_group,
    studies_interactive,  # a session may group or split, and keeping apart is the only exception
]


def _ids(builds: list[Build]) -> list[str]:
    return [b.__name__ for b in builds]


# --- the fix ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "build", [*CONFIG_DEPENDENT, *ALWAYS_REQUIRED], ids=_ids([*CONFIG_DEPENDENT, *ALWAYS_REQUIRED])
)
def test_refuses_before_writing_when_no_rationale_can_be_given(
    build: Build, tmp_path: Path
) -> None:
    scenario = build(tmp_path)
    repo = scenario.repo
    assert _porcelain(repo) == "", "the fixture must start clean"
    head = _head(repo)

    refused = _run(scenario)

    assert refused.exit_code == EXIT_RATIONALE_REFUSED, refused.output
    assert NEEDED in refused.output
    assert _porcelain(repo) == "", "the refusal left files behind"
    assert _head(repo) == head

    # Control: nothing was lost or half-done, and the command is a mutating one that goes
    # through (and commits) as soon as a rationale is supplied.
    done = _run(scenario, "--why", WHY)
    assert done.exit_code == EXIT_OK, done.output
    assert _head(repo) != head, "the control run made no commit"
    assert _porcelain(repo) == ""


@pytest.mark.parametrize(
    "build", [*CONFIG_DEPENDENT, *ALWAYS_REQUIRED], ids=_ids([*CONFIG_DEPENDENT, *ALWAYS_REQUIRED])
)
def test_refuses_a_rejected_rationale_before_writing(build: Build, tmp_path: Path) -> None:
    """A stop-listed `--why` fails the same way a missing one does: before the work, not after."""
    scenario = build(tmp_path)
    head = _head(scenario.repo)

    refused = _run(scenario, "--why", "wip")

    assert refused.exit_code == EXIT_RATIONALE_REFUSED, refused.output
    assert "not a rationale" in refused.output
    assert _porcelain(scenario.repo) == ""
    assert _head(scenario.repo) == head


def test_an_unreadable_why_file_is_refused_cleanly_before_writing(tmp_path: Path) -> None:
    scenario = actor_add(tmp_path)
    missing = tmp_path / "no-such-file.txt"

    refused = _run(scenario, "--why-file", str(missing))

    assert refused.exit_code == EXIT_RATIONALE_REFUSED, refused.output
    assert "cannot read --why-file" in refused.output
    assert "Traceback" not in refused.output
    assert _porcelain(scenario.repo) == ""


def test_why_file_supplies_the_rationale(tmp_path: Path) -> None:
    scenario = actor_add(tmp_path)
    why_file = tmp_path / "why.txt"
    why_file.write_text("Jo is joining to second-screen the pilot batch.", encoding="utf-8")

    done = _run(scenario, "--why-file", str(why_file))

    assert done.exit_code == EXIT_OK, done.output
    body = gitio.run(["log", "-1", "--format=%B"], cwd=scenario.repo.root).stdout
    assert "Jo is joining to second-screen the pilot batch." in body


# --- what must keep working ------------------------------------------------------------------


@pytest.mark.parametrize("build", CONFIG_DEPENDENT, ids=_ids(CONFIG_DEPENDENT))
def test_no_commit_needs_no_rationale(build: Build, tmp_path: Path) -> None:
    scenario = build(tmp_path)
    head = _head(scenario.repo)

    result = _run(scenario, "--no-commit")

    assert result.exit_code == EXIT_OK, result.output
    assert _head(scenario.repo) == head
    assert _porcelain(scenario.repo) != "", "--no-commit leaves the work in the tree"


@pytest.mark.parametrize("build", CONFIG_DEPENDENT, ids=_ids(CONFIG_DEPENDENT))
def test_a_review_that_does_not_require_rationales_commits_without_one(
    build: Build, tmp_path: Path
) -> None:
    scenario = build(tmp_path)
    _set_require_rationale(scenario.repo, False)
    head = _head(scenario.repo)

    result = _run(scenario)

    assert result.exit_code == EXIT_OK, result.output
    assert _head(scenario.repo) != head
    assert _porcelain(scenario.repo) == ""


@pytest.mark.parametrize("build", ALWAYS_REQUIRED, ids=_ids(ALWAYS_REQUIRED))
def test_required_rationales_ignore_the_config_and_no_commit(build: Build, tmp_path: Path) -> None:
    scenario = build(tmp_path)
    _set_require_rationale(scenario.repo, False)
    head = _head(scenario.repo)

    for options in ((), ("--no-commit",)):
        refused = _run(scenario, *options)
        assert refused.exit_code == EXIT_RATIONALE_REFUSED, (options, refused.output)
        assert _porcelain(scenario.repo) == ""
        assert _head(scenario.repo) == head


def test_an_interactive_run_still_prompts_after_the_work(tmp_path: Path, monkeypatch: Any) -> None:
    """The prompt shows what was done (`context_lines`), so it stays at commit time."""

    # Same technique as test_search_add_prompts_for_rationale_interactively: CliRunner.invoke()
    # swaps in its own sys.stdin, so the module's `sys` binding itself is replaced.
    class _FakeStdin:
        def isatty(self) -> bool:
            return True

    class _FakeSys:
        stdin = _FakeStdin()

    scenario = actor_add(tmp_path)
    seen: dict[str, str] = {}

    def prompt(*args: Any, **kwargs: Any) -> str:
        seen["manifest"] = scenario.repo.path("strata.toml").read_text(encoding="utf-8")
        return "Jo is joining to second-screen the pilot batch."

    monkeypatch.setattr("strata.cli.main.sys", _FakeSys())
    monkeypatch.setattr("strata.cli.main.typer.prompt", prompt)
    head = _head(scenario.repo)

    result = _run(scenario)

    assert result.exit_code == EXIT_OK, result.output
    assert "jo" in seen["manifest"], "the prompt came before the work, not after"
    assert "You add actor jo." in result.output
    assert _head(scenario.repo) != head
    assert _porcelain(scenario.repo) == ""


@pytest.mark.parametrize("build", [dedup, import_papers], ids=["dedup", "import_papers"])
def test_a_rerun_with_nothing_to_commit_is_not_refused(build: Build, tmp_path: Path) -> None:
    """The commit is what needs the rationale: a rerun that finds nothing new records nothing."""
    scenario = build(tmp_path)
    assert _run(scenario, "--why", WHY).exit_code == EXIT_OK
    head = _head(scenario.repo)

    rerun = _run(scenario)

    assert rerun.exit_code == EXIT_OK, rerun.output
    assert _head(scenario.repo) == head
    assert _porcelain(scenario.repo) == ""


def test_an_import_that_fails_still_reports_its_own_error(tmp_path: Path) -> None:
    """A usage error is not hidden behind the rationale refusal: nothing would be committed."""
    scenario = import_papers(tmp_path)

    result = _run(scenario, args=("import", str(tmp_path / "no-such-file.json"), "--by", "ethan"))

    assert result.exit_code == EXIT_USAGE, result.output
    assert "no such file" in result.output


# --- the read-only modes of the same commands need no rationale ------------------------------


def import_dry_run(tmp_path: Path) -> Scenario:
    scenario = import_papers(tmp_path)
    return Scenario(scenario.repo, (*scenario.args, "--dry-run"))


def analyze_check(tmp_path: Path) -> Scenario:
    return Scenario(analysis_review(tmp_path), ("analyze", "primary", "--check"))


def retrieve_list(tmp_path: Path) -> Scenario:
    return Scenario(_sought(tmp_path), ("retrieve", "--by", "ethan", "--list"))


def studies_list(tmp_path: Path) -> Scenario:
    return Scenario(_full_text_review(tmp_path, 3), ("studies", "--list"))


def extract_list(tmp_path: Path) -> Scenario:
    return Scenario(_screened(_form_repo(tmp_path)), ("extract", "--list"))


def extract_reconcile_list(tmp_path: Path) -> Scenario:
    return Scenario(dual_extraction_repo(tmp_path), ("extract", "--reconcile", "--list"))


def rob_list(tmp_path: Path) -> Scenario:
    return Scenario(_rob_repo(tmp_path), ("rob", "--list"))


def prisma_to_stdout(tmp_path: Path) -> Scenario:
    scenario = prisma(tmp_path)
    return Scenario(scenario.repo, (*scenario.args, "--format", "json", "--out", "-"))


def report_to_stdout(tmp_path: Path) -> Scenario:
    scenario = report(tmp_path)
    return Scenario(scenario.repo, (*scenario.args, "--out", "-"))


def checklist_status(tmp_path: Path) -> Scenario:
    scenario = report(tmp_path)
    return Scenario(scenario.repo, ("report", "checklist", "--status"))


READ_ONLY: list[Build] = [
    import_dry_run,
    analyze_check,
    retrieve_list,
    studies_list,
    extract_list,
    extract_reconcile_list,
    rob_list,
    prisma_to_stdout,
    report_to_stdout,
    checklist_status,
]


@pytest.mark.parametrize("build", READ_ONLY, ids=_ids(READ_ONLY))
def test_read_only_modes_need_no_rationale(build: Build, tmp_path: Path) -> None:
    scenario = build(tmp_path)
    head = _head(scenario.repo)

    result = _run(scenario)

    assert result.exit_code == EXIT_OK, result.output
    assert _head(scenario.repo) == head
