"""The wiki pages in `wiki/` (openspec:project-documentation#project-wiki): the checker passes,
the command reference is current, and the publish workflow is the plain one it is meant to be."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

from strata.core.canon import load_yaml_str

ROOT = Path(__file__).resolve().parents[2]


def _load(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_wiki_checks_pass(capsys: pytest.CaptureFixture[str]) -> None:
    result = _load("check_wiki").main()
    assert result == 0, capsys.readouterr().out


def test_the_generated_reference_covers_every_command() -> None:
    pages = _load("build_wiki_reference").build()  # raises if a command has no page
    assert "Command-Reference" in pages and len(pages) == 7


def test_slugs_match_githubs_anchors() -> None:
    slug = _load("check_wiki").slug
    assert slug("`strata verify` says…") == "strata-verify-says"
    assert slug('"I made a wrong decision"') == "i-made-a-wrong-decision"
    assert slug("Sharing went wrong (`strata sync`)") == "sharing-went-wrong-strata-sync"


def test_an_example_naming_a_missing_command_or_option_is_caught() -> None:
    module = _load("check_wiki")
    commands, global_opts = module.command_tree()
    assert module.check_example("strata status", commands, global_opts) is None
    assert (
        module.check_example('strata --why "x" import f.ris --by a', commands, global_opts) is None
    )
    assert "unknown command" in module.check_example("strata frobnicate", commands, global_opts)
    assert "no option --nope" in module.check_example("strata status --nope", commands, global_opts)
    assert "unknown subcommand" in module.check_example("strata search wat", commands, global_opts)
    assert "no option --why" in module.check_example(
        "strata studies --why x", commands, global_opts
    )


def test_the_publish_workflow_pushes_only_from_main_with_the_repository_token() -> None:
    doc = load_yaml_str((ROOT / ".github" / "workflows" / "wiki.yml").read_text(encoding="utf-8"))
    on = doc.get("on", doc.get(True))
    assert on["push"]["branches"] == ["main"] and "wiki/**" in on["push"]["paths"]
    assert doc["permissions"] == {"contents": "write"}
    job = doc["jobs"]["publish"]
    assert "github.repository ==" in job["if"]
    text = (ROOT / ".github" / "workflows" / "wiki.yml").read_text(encoding="utf-8")
    assert "secrets." not in text
    for step in job["steps"]:
        if "uses" in step:
            assert "@" in step["uses"] and len(step["uses"].split("@")[1].split()[0]) == 40
