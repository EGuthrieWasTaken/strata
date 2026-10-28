import subprocess
import sys
from pathlib import Path

import pytest

from strata.core.hooks import HOOK_SCRIPTS, validate_commit_message_trailers


def test_unstructured_style_always_passes() -> None:
    assert validate_commit_message_trailers("anything\n\nStrata-Op broken", structured=False) == []


def test_message_with_no_trailers_passes() -> None:
    message = "fix: correct a typo\n\nNo trailers here at all.\n"
    assert validate_commit_message_trailers(message, structured=True) == []


def test_well_formed_trailer_block_passes() -> None:
    message = (
        "screen(title-abstract): exclude 1 record\n\nBody text.\n\n"
        "Strata-Op: screen\nStrata-Actor: ethan\n"
    )
    assert validate_commit_message_trailers(message, structured=True) == []


def test_trailer_block_must_be_contiguous() -> None:
    message = "subject\n\nStrata-Op: screen\nnot a trailer\nStrata-Actor: ethan\n"
    errors = validate_commit_message_trailers(message, structured=True)
    assert any("contiguous" in e for e in errors)


def test_trailer_block_must_be_preceded_by_blank_line() -> None:
    message = "subject\nStrata-Op: screen\n"
    errors = validate_commit_message_trailers(message, structured=True)
    assert any("blank line" in e for e in errors)


def test_trailers_starting_at_line_one_need_no_blank_line() -> None:
    message = "Strata-Op: screen\n"
    assert validate_commit_message_trailers(message, structured=True) == []


def test_malformed_trailer_line_reported() -> None:
    message = "subject\n\nStrata-Op\n"
    errors = validate_commit_message_trailers(message, structured=True)
    assert any("malformed trailer" in e for e in errors)


# --- a hook that cannot find `strata` says so (openspec:git-integration#versioned-hooks) ------


def _run_hook(name: str, tmp_path: Path, *, on_path: bool) -> subprocess.CompletedProcess[str]:
    """Run a hook script with a PATH that has, or lacks, a stand-in `strata`."""
    script = tmp_path / name
    script.write_text(HOOK_SCRIPTS[name], encoding="utf-8")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    if on_path:
        stand_in = bin_dir / "strata"
        stand_in.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        stand_in.chmod(0o755)
    env = {"PATH": str(bin_dir)}
    return subprocess.run(
        ["/bin/sh", str(script), "msg-file"], capture_output=True, text=True, env=env, check=False
    )


posix_only = pytest.mark.skipif(sys.platform == "win32", reason="the hooks are POSIX shell scripts")


@posix_only
@pytest.mark.parametrize("name", ["pre-commit", "commit-msg"])
def test_a_blocking_hook_without_strata_blocks_and_names_the_bypass(
    name: str, tmp_path: Path
) -> None:
    result = _run_hook(name, tmp_path, on_path=False)
    assert result.returncode == 1
    assert "strata: not found on PATH" in result.stderr
    assert "STRATA_SKIP_HOOKS=1" in result.stderr


@posix_only
@pytest.mark.parametrize("name", ["post-merge", "post-checkout"])
def test_a_warning_hook_without_strata_warns_and_succeeds(name: str, tmp_path: Path) -> None:
    result = _run_hook(name, tmp_path, on_path=False)
    assert result.returncode == 0
    assert "strata: not found on PATH" in result.stderr


@posix_only
@pytest.mark.parametrize("name", sorted(HOOK_SCRIPTS))
def test_every_hook_runs_strata_when_it_is_on_path(name: str, tmp_path: Path) -> None:
    result = _run_hook(name, tmp_path, on_path=True)
    assert result.returncode == 0
    assert result.stderr == ""
