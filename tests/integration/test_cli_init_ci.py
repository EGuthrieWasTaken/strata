from pathlib import Path

from ruamel.yaml import YAML
from typer.testing import CliRunner

from strata import __version__, gitio
from strata.cli.main import EXIT_OK, app
from strata.core.init import init_repository
from strata.core.review_ci_workflow import REVIEW_CI_WORKFLOW_PATH

runner = CliRunner()


def _init(tmp_path: Path, *extra: str) -> Path:
    root = tmp_path / "review"
    result = runner.invoke(
        app,
        ["init", str(root), "--title", "Test Review", "--actor", "ethan", *extra],
    )
    assert result.exit_code == EXIT_OK, result.output
    return root


def test_init_ci_installs_the_workflow_in_the_initial_commit(tmp_path: Path) -> None:
    root = _init(tmp_path, "--ci")
    assert (root / REVIEW_CI_WORKFLOW_PATH).is_file()
    assert REVIEW_CI_WORKFLOW_PATH in gitio.run(["ls-files"], cwd=root).stdout.splitlines()
    assert gitio.run(["status", "--porcelain"], cwd=root).stdout == ""


def test_the_installed_workflow_calls_the_reusable_workflow_on_pull_request(
    tmp_path: Path,
) -> None:
    root = _init(tmp_path, "--ci")
    text = (root / REVIEW_CI_WORKFLOW_PATH).read_text(encoding="utf-8")
    assert "@@" not in text
    data = YAML(typ="safe").load(text)
    assert set(data["on"]) == {"pull_request"}
    job = data["jobs"]["review"]
    assert job["uses"] == f"EGuthrieWasTaken/strata/.github/workflows/review-ci.yml@v{__version__}"
    assert job["with"]["strata-spec"] == f"strata-review=={__version__}"


def test_a_repository_initialised_with_ci_still_verifies(tmp_path: Path) -> None:
    root = _init(tmp_path, "--ci")
    result = runner.invoke(app, ["-C", str(root), "verify"])
    assert result.exit_code == EXIT_OK, result.output


def test_init_without_the_flag_writes_no_workflow(tmp_path: Path) -> None:
    root = _init(tmp_path)
    assert not (root / ".github").exists()


def test_init_repository_ci_defaults_to_off(tmp_path: Path) -> None:
    root = tmp_path / "review"
    init_repository(root, title="T", actor_handle="ethan", actor_name="Ethan")
    assert not (root / ".github").exists()


def test_init_repository_with_ci_installs_the_workflow(tmp_path: Path) -> None:
    root = tmp_path / "review"
    init_repository(root, title="T", actor_handle="ethan", actor_name="Ethan", ci=True)
    assert (root / REVIEW_CI_WORKFLOW_PATH).is_file()
