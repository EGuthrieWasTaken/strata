import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from strata import __version__, gitio
from strata.cli.main import (
    EXIT_GENERIC,
    EXIT_OK,
    EXIT_SCHEMA_TOO_NEW,
    EXIT_USAGE,
    EXIT_VALIDATION,
    _derive_clone_dest_name,
    app,
)
from strata.core.events import append_new_event
from strata.core.hooks import validate_commit_message_trailers

runner = CliRunner()


def _init(tmp_path: Path, name: str = "review") -> Path:
    root = tmp_path / name
    result = runner.invoke(
        app,
        [
            "init",
            str(root),
            "--title",
            "Test Review",
            "--actor",
            "ethan",
            "--actor-name",
            "Ethan Test",
        ],
    )
    assert result.exit_code == EXIT_OK, result.output
    return root


def test_version_command() -> None:
    result = runner.invoke(app, ["version"])
    assert result.exit_code == EXIT_OK
    assert __version__ in result.output


def test_no_color_flag_disables_colour(tmp_path: Path) -> None:
    root = _init(tmp_path)
    result = runner.invoke(app, ["--no-color", "-C", str(root), "status"])
    assert result.exit_code == EXIT_OK
    assert "[bold]" not in result.output
    assert "[/]" not in result.output


def test_resolve_repo_reports_schema_too_new(tmp_path: Path) -> None:
    root = _init(tmp_path)
    (root / ".strata" / "schema-version").write_text("999", encoding="utf-8")
    result = runner.invoke(app, ["-C", str(root), "status"])
    assert result.exit_code == EXIT_SCHEMA_TOO_NEW


def test_init_prompts_interactively_when_flags_omitted(tmp_path: Path, monkeypatch) -> None:
    # `CliRunner.invoke` swaps in its own `sys.stdin` around the call, which
    # would clobber a patch applied to the real `sys.stdin` object before it.
    # Replacing the module's `sys` binding itself survives that swap, since
    # `init()` looks up `sys.stdin` through this module's own globals.
    class _FakeStdin:
        def isatty(self) -> bool:
            return True

    class _FakeSys:
        stdin = _FakeStdin()

    prompts = iter(["Prompted Title", "ethan", "Ethan Prompted"])
    monkeypatch.setattr("strata.cli.main.sys", _FakeSys())
    monkeypatch.setattr("strata.cli.main.typer.prompt", lambda *a, **kw: next(prompts))
    root = tmp_path / "interactive-review"
    result = runner.invoke(app, ["init", str(root)])
    assert result.exit_code == EXIT_OK, result.output
    assert (root / "strata.toml").exists()


def _push_bare(root: Path, tmp_path: Path, bare_name: str = "origin.git") -> Path:
    bare = tmp_path / bare_name
    gitio.run(["init", "--bare", "--initial-branch=main", str(bare)], cwd=tmp_path)
    gitio.run(["remote", "add", "shared", str(bare)], cwd=root)
    gitio.run(["push", "shared", "HEAD:main"], cwd=root)
    return bare


def test_clone_command_with_explicit_dest(tmp_path: Path) -> None:
    root = _init(tmp_path)
    bare = _push_bare(root, tmp_path)
    dest = tmp_path / "clone-dest"
    result = runner.invoke(app, ["clone", str(bare), str(dest)])
    assert result.exit_code == EXIT_OK, result.output
    assert "cloned and verified" in result.output
    assert (dest / "strata.toml").exists()


def test_derive_clone_dest_name_handles_posix_and_windows_separators() -> None:
    assert _derive_clone_dest_name("https://example.invalid/team/review.git") == "review"
    assert _derive_clone_dest_name("git@example.invalid:team/review.git") == "review"
    assert _derive_clone_dest_name("/home/ethan/repos/review.git") == "review"
    assert _derive_clone_dest_name("/home/ethan/repos/review") == "review"
    # A Windows-style local path has no "/" for the old rsplit("/", ...) logic
    # to find at all, so it used to return the entire path unchanged.
    assert _derive_clone_dest_name(r"C:\Users\ethan\repos\review.git") == "review"
    assert _derive_clone_dest_name(r"C:\Users\ethan\repos\review\\") == "review"


def test_clone_command_derives_dest_name_from_url(tmp_path: Path, monkeypatch) -> None:
    root = _init(tmp_path)
    bare = _push_bare(root, tmp_path)
    workdir = tmp_path / "workdir"
    workdir.mkdir()
    monkeypatch.chdir(workdir)
    result = runner.invoke(app, ["clone", str(bare)])
    assert result.exit_code == EXIT_OK, result.output
    assert (workdir / "origin" / "strata.toml").exists()


def test_clone_command_reports_verify_failure(tmp_path: Path) -> None:
    root = _init(tmp_path)
    path = root / "events" / "screen" / "title-abstract.ethan.ndjson"
    append_new_event(
        path,
        ev="screen",
        actor="ethan",
        body={
            "stage": "title-abstract",
            "record": "rec_doesnotexist000000",
            "decision": "include",
            "criteria": [],
            "criteria_version": 1,
        },
    )
    gitio.add_all(root)
    gitio.commit(root, "screen(title-abstract): screen 1 record\n\nStrata-Op: screen\n")
    bare = _push_bare(root, tmp_path)
    dest = tmp_path / "clone-dest"
    result = runner.invoke(app, ["clone", str(bare), str(dest)])
    assert result.exit_code == EXIT_VALIDATION
    assert "E_DANGLING_REF" in result.output


def test_doctor_reports_problems_and_fixes_them(tmp_path: Path) -> None:
    root = _init(tmp_path)
    gitio.set_config(root, "core.hooksPath", "")
    not_fixed = runner.invoke(app, ["-C", str(root), "doctor"])
    assert not_fixed.exit_code == EXIT_GENERIC
    assert "!!" in not_fixed.output

    fixed = runner.invoke(app, ["-C", str(root), "doctor", "--fix"])
    assert fixed.exit_code == EXIT_OK
    assert "fixed" in fixed.output


def test_config_unknown_key_is_usage_error(tmp_path: Path) -> None:
    root = _init(tmp_path)
    result = runner.invoke(app, ["-C", str(root), "config", "nonexistent.key"])
    assert result.exit_code == EXIT_USAGE


def test_verify_json_output_ok(tmp_path: Path) -> None:
    root = _init(tmp_path)
    result = runner.invoke(app, ["--json", "-C", str(root), "verify"])
    assert result.exit_code == EXIT_OK
    payload = json.loads(result.output)
    assert payload == {"ok": True, "issues": []}


def test_verify_json_output_with_issues(tmp_path: Path) -> None:
    root = _init(tmp_path)
    path = root / "events" / "screen" / "title-abstract.ethan.ndjson"
    append_new_event(
        path,
        ev="screen",
        actor="ethan",
        body={
            "stage": "title-abstract",
            "record": "rec_doesnotexist000000",
            "decision": "include",
            "criteria": [],
            "criteria_version": 1,
        },
    )
    result = runner.invoke(app, ["--json", "-C", str(root), "verify"])
    assert result.exit_code == EXIT_VALIDATION
    payload = json.loads(result.output)
    assert payload["ok"] is False
    assert any(i["code"] == "E_DANGLING_REF" for i in payload["issues"])


def test_status_json_output(tmp_path: Path) -> None:
    root = _init(tmp_path)
    result = runner.invoke(app, ["--json", "-C", str(root), "status"])
    assert result.exit_code == EXIT_OK
    payload = json.loads(result.output)
    assert payload["title"] == "Test Review"
    assert {s["stage"] for s in payload["stages"]} == {"title-abstract", "full-text"}
    assert payload["next_action"] is None


def test_status_shows_next_action_and_regenerates_derived_files(tmp_path: Path) -> None:
    root = _init(tmp_path)
    export = tmp_path / "one.json"
    export.write_text(
        '[{"id": "1", "type": "article-journal", "title": "A test record", "DOI": "10.1234/test"}]',
        encoding="utf-8",
    )
    import_result = runner.invoke(
        app,
        [
            "--why",
            "importing one.json for a status test",
            "-C",
            str(root),
            "import",
            str(export),
            "--by",
            "ethan",
            "--via",
            "registry",
        ],
    )
    assert import_result.exit_code == EXIT_OK, import_result.output

    status_result = runner.invoke(app, ["-C", str(root), "status"])
    assert status_result.exit_code == EXIT_OK, status_result.output
    assert "TITLE-ABSTRACT" in status_result.output
    assert "NEXT" in status_result.output
    assert "strata screen title-abstract" in status_result.output

    screen_result = runner.invoke(
        app,
        [
            "--why",
            "Screening the pilot batch for the review.",
            "-C",
            str(root),
            "screen",
            "title-abstract",
            "--by",
            "ethan",
        ],
        input="i\n\n",
    )
    assert screen_result.exit_code == EXIT_OK, screen_result.output

    pool_tsv = (root / "derived" / "pool.tsv").read_text(encoding="utf-8")
    assert "include" in pool_tsv


def test_log_command_lists_and_filters_commits(tmp_path: Path) -> None:
    root = _init(tmp_path)
    (root / "protocol" / "question.md").write_text("updated\n", encoding="utf-8")
    gitio.add_all(root)
    gitio.commit(
        root,
        "criteria(v2): tighten EXC-01\n\nStrata-Op: criteria-change\nStrata-Actor: ethan\n",
    )

    all_result = runner.invoke(app, ["-C", str(root), "log"])
    assert all_result.exit_code == EXIT_OK
    assert "criteria(v2)" in all_result.output

    criteria_result = runner.invoke(app, ["-C", str(root), "log", "--criteria"])
    assert "criteria(v2)" in criteria_result.output

    actor_result = runner.invoke(app, ["-C", str(root), "log", "--actor", "nobody"])
    assert "criteria(v2)" not in actor_result.output


def test_actor_list_json_output(tmp_path: Path) -> None:
    root = _init(tmp_path)
    result = runner.invoke(app, ["--json", "-C", str(root), "actor", "list"])
    assert result.exit_code == EXIT_OK
    payload = json.loads(result.output)
    assert payload[0]["handle"] == "ethan"


def test_internal_hook_pre_commit_passes_and_fails(tmp_path: Path, monkeypatch) -> None:
    root = _init(tmp_path)
    monkeypatch.chdir(root)
    ok_result = runner.invoke(app, ["internal", "hook-pre-commit"])
    assert ok_result.exit_code == EXIT_OK

    bad_event_path = root / "events" / "screen" / "title-abstract.ethan.ndjson"
    bad_event_path.parent.mkdir(parents=True, exist_ok=True)
    bad_event_path.write_text('{"ev":"screen","id":"not-a-valid-id"}\n', encoding="utf-8")
    bad_result = runner.invoke(app, ["internal", "hook-pre-commit"])
    assert bad_result.exit_code == EXIT_VALIDATION


def test_internal_hook_commit_msg_passes_and_fails(tmp_path: Path, monkeypatch) -> None:
    root = _init(tmp_path)
    monkeypatch.chdir(root)

    good_msg = tmp_path / "good-msg.txt"
    good_msg.write_text("subject\n\nStrata-Op: screen\n", encoding="utf-8")
    good_result = runner.invoke(app, ["internal", "hook-commit-msg", str(good_msg)])
    assert good_result.exit_code == EXIT_OK

    bad_msg = tmp_path / "bad-msg.txt"
    bad_msg.write_text("subject\nStrata-Op: screen\n", encoding="utf-8")
    bad_result = runner.invoke(app, ["internal", "hook-commit-msg", str(bad_msg)])
    assert bad_result.exit_code == EXIT_VALIDATION


def test_internal_hook_post_merge_warns_on_issues(tmp_path: Path, monkeypatch) -> None:
    root = _init(tmp_path)
    monkeypatch.chdir(root)
    clean_result = runner.invoke(app, ["internal", "hook-post-merge"])
    assert clean_result.exit_code == EXIT_OK
    assert "warning" not in clean_result.output

    path = root / "events" / "screen" / "title-abstract.ethan.ndjson"
    append_new_event(
        path,
        ev="screen",
        actor="ethan",
        body={
            "stage": "title-abstract",
            "record": "rec_doesnotexist000000",
            "decision": "include",
            "criteria": [],
            "criteria_version": 1,
        },
    )
    warn_result = runner.invoke(app, ["internal", "hook-post-merge"])
    assert warn_result.exit_code == EXIT_OK
    assert "E_DANGLING_REF" in warn_result.output


def test_internal_hook_post_checkout_recreates_cache(tmp_path: Path, monkeypatch) -> None:
    root = _init(tmp_path)
    monkeypatch.chdir(root)
    cache_dir = root / ".strata" / "cache"
    (cache_dir / "stale.sqlite").write_text("junk", encoding="utf-8")

    result = runner.invoke(app, ["internal", "hook-post-checkout"])
    assert result.exit_code == EXIT_OK
    assert cache_dir.exists()
    assert not (cache_dir / "stale.sqlite").exists()


def test_internal_hook_post_checkout_creates_missing_cache_dir(tmp_path: Path, monkeypatch) -> None:
    root = _init(tmp_path)
    monkeypatch.chdir(root)
    cache_dir = root / ".strata" / "cache"
    import shutil

    shutil.rmtree(cache_dir)
    assert not cache_dir.exists()

    result = runner.invoke(app, ["internal", "hook-post-checkout"])
    assert result.exit_code == EXIT_OK
    assert cache_dir.exists()


def test_validate_commit_message_trailers_reexported_for_hook() -> None:
    # Sanity check that the CLI's import path still works after any refactor.
    assert validate_commit_message_trailers("Strata-Op: init\n", structured=True) == []


@pytest.mark.parametrize("value", ["true", "false", "42", "3.5", "plain"])
def test_config_set_parses_value_types(tmp_path: Path, value: str) -> None:
    root = _init(tmp_path)
    result = runner.invoke(app, ["-C", str(root), "config", "custom.value", value])
    assert result.exit_code == EXIT_OK
