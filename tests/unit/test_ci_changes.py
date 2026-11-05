"""`scripts/ci_changes.py`: which pull requests may skip the test jobs
(openspec:ci-gate#documentation-only-pull-requests-skip-the-test-jobs).

The property that matters is one-sided: a change that touches anything but documentation must say
"code", whatever else is true of it. Everything below that can go wrong in the git or the
environment must also say "code".
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from scripts import ci_changes
from scripts.ci_changes import changed_paths, changes_code, decide, is_documentation

# ---- which paths are documentation ----------------------------------------------------------

DOCUMENTATION = [
    "README.md",
    "CHANGELOG.md",
    "CONTRIBUTING.md",
    "docs/roadmap.md",
    "docs/origin/ProgramSpec.org",
    "wiki/Home.md",
    "wiki/images/review-folder.png",
    "openspec/README.md",
    "openspec/specs/ci-gate/spec.md",
    "openspec/changes/skip-tests-for-docs-only-prs/tasks.md",
]

CODE = [
    "src/strata/cli/main.py",
    "tests/unit/test_ci_changes.py",
    "tests/fixtures/zotero/README.md",
    "scripts/check_docs.py",
    ".github/workflows/ci.yml",
    ".github/PULL_REQUEST_TEMPLATE.md",
    ".claude/skills/openspec-explore/SKILL.md",
    "actions/verify/action.yml",
    "pyproject.toml",
    "uv.lock",
    "Dockerfile",
    ".dockerignore",
    "compose.yaml",
    "docker/entrypoint.sh",
    "LICENSE",
    ".gitignore",
    ".gitattributes",
    # Near misses: the name has to match at the repository root, exactly.
    "src/README.md",
    "src/docs/guide.md",
    "tests/wiki/Home.md",
    "Docs/roadmap.md",
    "docs.md",
    "docsy/guide.md",
    "wiki",
    "openspec",
    "README.markdown",
    "README.md.bak",
    "readme.md",
]


@pytest.mark.parametrize("path", DOCUMENTATION)
def test_documentation_paths(path: str) -> None:
    assert is_documentation(path)


@pytest.mark.parametrize("path", CODE)
def test_everything_else_is_code(path: str) -> None:
    assert not is_documentation(path)


def test_a_change_is_documentation_only_when_every_file_is() -> None:
    assert not changes_code(["README.md", "docs/roadmap.md", "wiki/Home.md"])
    assert changes_code(["README.md", "docs/roadmap.md", "src/strata/cli/main.py"])
    assert changes_code(["src/strata/cli/main.py"])


def test_no_changed_files_is_not_documentation_only() -> None:
    assert changes_code([])


def test_one_code_file_among_hundreds_of_documentation_files_is_code() -> None:
    paths = [f"wiki/page-{n}.md" for n in range(500)] + ["uv.lock"]
    assert changes_code(paths)


# ---- the decision, with the git behind it stubbed -------------------------------------------


def _diff(*paths: str):  # type: ignore[no-untyped-def]
    return lambda base: list(paths)


def _raises(exc: Exception):  # type: ignore[no-untyped-def]
    def diff(base: str) -> list[str]:
        raise exc

    return diff


@pytest.mark.parametrize("event", ["push", "workflow_dispatch", "schedule", ""])
def test_anything_that_is_not_a_pull_request_runs_every_job(event: str) -> None:
    code, reason = decide(event, "abc123", _diff("README.md"))
    assert code
    assert "every job runs" in reason


def test_a_pull_request_with_no_base_runs_every_job() -> None:
    code, reason = decide("pull_request", "", _diff("README.md"))
    assert code
    assert "no base commit" in reason


@pytest.mark.parametrize(
    "exc",
    [subprocess.CalledProcessError(128, ["git"]), FileNotFoundError("git"), PermissionError("x")],
)
def test_changes_that_cannot_be_read_run_every_job(exc: Exception) -> None:
    code, reason = decide("pull_request", "abc123", _raises(exc))
    assert code
    assert "could not be read" in reason


def test_a_pull_request_that_changes_nothing_runs_every_job() -> None:
    code, reason = decide("pull_request", "abc123", _diff())
    assert code
    assert "no changed files" in reason


def test_a_documentation_only_pull_request_skips_the_tests() -> None:
    code, reason = decide("pull_request", "abc123", _diff("README.md", "docs/roadmap.md"))
    assert not code
    assert "only documentation changed (2 files)" in reason


def test_the_reason_for_running_names_the_code_files() -> None:
    code, reason = decide(
        "pull_request", "abc123", _diff("README.md", "src/strata/cli/main.py", "uv.lock")
    )
    assert code
    assert "2 of 3 changed files are not documentation" in reason
    assert "src/strata/cli/main.py" in reason and "uv.lock" in reason


def test_a_long_list_of_code_files_is_shortened_in_the_log() -> None:
    paths = [f"src/strata/m{n}.py" for n in range(ci_changes.SHOWN + 5)]
    code, reason = decide("pull_request", "abc123", _diff(*paths))
    assert code
    assert paths[0] in reason and paths[ci_changes.SHOWN - 1] in reason
    assert paths[ci_changes.SHOWN] not in reason
    assert reason.endswith(", ...)")


# ---- the real git behind it -----------------------------------------------------------------


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        [
            "git",
            "-c",
            "user.name=test",
            "-c",
            "user.email=test@example.invalid",
            "-c",
            "commit.gpgsign=false",
            "-c",
            "core.quotepath=true",
            *args,
        ],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return result.stdout.strip()


def _write(repo: Path, name: str, text: str = "x\n") -> None:
    path = repo / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A repository with one commit holding a source file and a documentation file."""
    _git(tmp_path, "init", "-q")
    _write(tmp_path, "src/strata/mod.py", "VALUE = 1\n")
    _write(tmp_path, "README.md", "# strata\n")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-q", "-m", "base")
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _base(repo: Path) -> str:
    return _git(repo, "rev-parse", "HEAD")


def _commit(repo: Path, message: str = "change") -> None:
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", message)


def test_git_reports_the_files_that_changed(repo: Path) -> None:
    base = _base(repo)
    _write(repo, "README.md", "# strata, changed\n")
    _write(repo, "docs/new.md")
    _commit(repo)
    assert sorted(changed_paths(base)) == ["README.md", "docs/new.md"]


def test_a_real_documentation_only_change_skips_the_tests(repo: Path) -> None:
    base = _base(repo)
    _write(repo, "CHANGELOG.md")
    _write(repo, "wiki/Home.md")
    _write(repo, "openspec/changes/x/tasks.md")
    _commit(repo)
    code, reason = decide("pull_request", base)
    assert not code, reason


def test_a_real_source_change_runs_the_tests(repo: Path) -> None:
    base = _base(repo)
    _write(repo, "README.md", "# changed\n")
    _write(repo, "src/strata/mod.py", "VALUE = 2\n")
    _commit(repo)
    code, reason = decide("pull_request", base)
    assert code and "src/strata/mod.py" in reason


def test_a_change_that_touches_only_a_workflow_runs_the_tests(repo: Path) -> None:
    base = _base(repo)
    _write(repo, ".github/workflows/ci.yml")
    _commit(repo)
    assert decide("pull_request", base)[0]


def test_moving_a_source_file_into_the_docs_still_counts_as_code(repo: Path) -> None:
    base = _base(repo)
    (repo / "docs").mkdir()
    _git(repo, "mv", "src/strata/mod.py", "docs/mod.py")
    _commit(repo)
    # Without `--no-renames` git reports only the new name, `docs/mod.py`, and the move looks
    # like documentation.
    assert sorted(changed_paths(base)) == ["docs/mod.py", "src/strata/mod.py"]
    assert decide("pull_request", base)[0]


def test_moving_a_documentation_file_out_of_the_docs_counts_as_code(repo: Path) -> None:
    base = _base(repo)
    _git(repo, "mv", "README.md", "src/README.md")
    _commit(repo)
    assert decide("pull_request", base)[0]


def test_deleting_a_source_file_counts_as_code(repo: Path) -> None:
    base = _base(repo)
    _git(repo, "rm", "-q", "src/strata/mod.py")
    _commit(repo)
    assert decide("pull_request", base)[0]


def test_unusual_file_names_are_read_back_unquoted(repo: Path) -> None:
    base = _base(repo)
    _write(repo, "docs/résumé of a review.md")
    _write(repo, "src/strata/é.py")
    _commit(repo)
    assert sorted(changed_paths(base)) == ["docs/résumé of a review.md", "src/strata/é.py"]
    # Without `-z` git quotes such a name (`"docs/r\303\251sum\303\251 of a review.md"`); it would
    # start with a quote, match no documentation directory, and so send a documentation-only
    # change to the full suite.
    only_docs_base = _base(repo)
    _write(repo, "wiki/Pâtes.md")
    _commit(repo, "docs only")
    assert not decide("pull_request", only_docs_base)[0]


def test_an_unknown_base_commit_runs_every_job(repo: Path) -> None:
    code, reason = decide("pull_request", "0" * 40)
    assert code and "could not be read" in reason


# ---- the script, as the workflow runs it ----------------------------------------------------


def test_main_writes_the_answer_for_the_workflow(
    repo: Path, monkeypatch: pytest.MonkeyPatch, tmp_path_factory: pytest.TempPathFactory
) -> None:
    base = _base(repo)
    _write(repo, "docs/guide.md")
    _commit(repo)
    output = tmp_path_factory.mktemp("out") / "github_output"
    output.write_text("earlier=1\n", encoding="utf-8")
    monkeypatch.setenv("EVENT", "pull_request")
    monkeypatch.setenv("BASE_SHA", base)
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    assert ci_changes.main() == 0
    assert output.read_text(encoding="utf-8") == "earlier=1\ncode=false\n"


def test_main_says_true_for_a_push(
    repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path_factory: pytest.TempPathFactory,
    capsys: pytest.CaptureFixture[str],
) -> None:
    output = tmp_path_factory.mktemp("out") / "github_output"
    monkeypatch.setenv("EVENT", "push")
    monkeypatch.setenv("BASE_SHA", "")
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    assert ci_changes.main() == 0
    assert output.read_text(encoding="utf-8") == "code=true\n"
    assert "every job runs" in capsys.readouterr().out


def test_main_without_an_output_file_prints_the_answer(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("GITHUB_OUTPUT", raising=False)
    monkeypatch.delenv("EVENT", raising=False)
    monkeypatch.delenv("BASE_SHA", raising=False)
    assert ci_changes.main() == 0
    assert capsys.readouterr().out.endswith("code=true\n")
