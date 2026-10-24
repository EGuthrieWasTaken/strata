"""Generate the wiki's command reference from the program's own help text.

`wiki/Command-Reference.md` and the `wiki/Commands-*.md` pages are written here, so they cannot drift
from the commands. Run `uv run python scripts/build_wiki_reference.py` after changing a command's help;
`scripts/check_wiki.py` fails when the committed pages differ from what this would write.

    --check      write nothing; exit 1 if a page is out of date
"""

# ruff: noqa: E501
from __future__ import annotations

import re
import sys
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from typer.main import get_command

from strata.cli.main import app

WIKI = Path(__file__).resolve().parents[1] / "wiki"

# The pages, in order: (file stem, title, one-line description, command names).
PAGES: list[tuple[str, str, str, list[str]]] = [
    (
        "Commands-Project",
        "Commands: project and repository",
        "Create, clone and check a review; settings; the team; history.",
        [
            "init",
            "clone",
            "doctor",
            "config",
            "actor",
            "verify",
            "status",
            "log",
            "diff",
            "version",
        ],
    ),
    (
        "Commands-Literature",
        "Commands: searching, importing and records",
        "Record searches, import exports, remove duplicates, inspect and correct records.",
        ["search", "import", "dedup", "records", "why", "fix"],
    ),
    (
        "Commands-Screening",
        "Commands: criteria and screening",
        "Eligibility criteria, assigning and screening records, re-screening, adjudication, agreement.",
        ["criteria", "assign", "screen", "rescreen", "adjudicate", "irr", "audit"],
    ),
    (
        "Commands-Full-Texts-and-Extraction",
        "Commands: full texts, studies, extraction and risk of bias",
        "Retrieval, grouping reports into studies, data extraction, risk of bias.",
        ["retrieve", "studies", "extract", "rob"],
    ),
    (
        "Commands-Analysis-and-Reporting",
        "Commands: analysis and reporting",
        "Pooling, the PRISMA diagram, generated text, exports.",
        ["analyze", "prisma", "report", "export"],
    ),
    (
        "Commands-Sharing-and-Tools",
        "Commands: sharing, the web interface and tools",
        "Syncing a shared review, the browser interface, the read-only assistant server, CI helpers.",
        ["sync", "serve", "mcp", "ci"],
    ),
]

# Where a command is explained in prose.
GUIDES: dict[str, list[tuple[str, str]]] = {
    "init": [("Setting-Up-a-Review", "Setting up a review")],
    "clone": [
        ("Git-for-Reviewers", "Git for reviewers"),
        ("Working-with-Others", "Working with others"),
    ],
    "doctor": [("Installation", "Installation")],
    "config": [("Configuration", "Configuration")],
    "actor": [("Setting-Up-a-Review", "Setting up a review")],
    "verify": [("Recovery-and-Troubleshooting", "Recovery and troubleshooting")],
    "status": [("Quickstart", "Quickstart")],
    "log": [("Searching-and-Importing", "Searching and importing")],
    "diff": [
        ("Analysis", "Analysis"),
        ("Changing-Criteria-Mid-Review", "Changing criteria mid-review"),
    ],
    "search": [("Searching-and-Importing", "Searching and importing")],
    "import": [("Searching-and-Importing", "Searching and importing")],
    "dedup": [
        ("Removing-Duplicates", "Removing duplicates"),
        ("How-Deduplication-Works", "How deduplication works"),
    ],
    "records": [
        ("Searching-and-Importing", "Searching and importing"),
        ("Filter-Language", "Filter language"),
    ],
    "why": [("Searching-and-Importing", "Searching and importing")],
    "fix": [("Searching-and-Importing", "Searching and importing")],
    "criteria": [
        ("Setting-Up-a-Review", "Setting up a review"),
        ("Changing-Criteria-Mid-Review", "Changing criteria mid-review"),
        ("Criteria-Versions-and-Direction", "Criteria versions and direction"),
    ],
    "assign": [("Screening", "Screening")],
    "screen": [
        ("Screening", "Screening"),
        ("Blinding-and-Independence", "Blinding and independence"),
    ],
    "rescreen": [
        ("Changing-Criteria-Mid-Review", "Changing criteria mid-review"),
        ("Staleness", "Staleness"),
    ],
    "adjudicate": [("Adjudication-and-Agreement", "Adjudication and agreement")],
    "irr": [("Adjudication-and-Agreement", "Adjudication and agreement")],
    "audit": [("Adjudication-and-Agreement", "Adjudication and agreement")],
    "retrieve": [("Retrieving-Full-Texts", "Retrieving full texts")],
    "studies": [("Grouping-Reports-into-Studies", "Grouping reports into studies")],
    "extract": [("Extracting-Data", "Extracting data")],
    "rob": [("Risk-of-Bias", "Risk of bias")],
    "analyze": [("Analysis", "Analysis"), ("Statistical-Methods", "Statistical methods")],
    "prisma": [("Reporting", "Reporting")],
    "report": [("Reporting", "Reporting"), ("Methods-Text-Cookbook", "Methods-text cookbook")],
    "export": [("Reporting", "Reporting"), ("Extracting-Data", "Extracting data")],
    "sync": [("Working-with-Others", "Working with others")],
    "serve": [
        ("The-Web-Interface", "The web interface"),
        ("Running-in-a-Container", "Running in a container"),
    ],
    "mcp": [("The-Web-Interface", "The web interface")],
    "ci": [("Working-with-Others", "Working with others")],
    "version": [("Installation", "Installation")],
}

# Commands that exist only for git hooks and merge drivers.
INTERNAL = {"internal", "merge-records", "merge-regenerate"}


def _clean(text: str) -> str:
    """Drop the internal `openspec:` cross-references that help text carries for developers."""
    text = re.sub(r"\s*\(openspec:[A-Za-z0-9#._-]+\)", "", text)
    text = re.sub(r"\n?\s*See openspec:[A-Za-z0-9#._-]+\.?", "", text)
    text = re.sub(r"openspec:[A-Za-z0-9#._-]+:?", "", text)
    text = re.sub(r"\(\s+", "(", text)
    text = re.sub(r":\s*\.", ".", text)
    text = re.sub(r"[ \t]+\n", "\n", text)
    return re.sub(r"[ \t]{2,}", " ", text)


def _cell(text: str) -> str:
    return " ".join(_clean(str(text)).split()).replace("|", "\\|")


def _default(param: Any) -> str:
    default = getattr(param, "default", None)
    if callable(default):
        return ""
    if default in (None, (), [], "") or getattr(param, "required", False):
        return ""
    if default is False and getattr(param, "is_flag", False):
        return ""
    return f"`{default}`"


def _type_name(param: Any) -> str:
    if getattr(param, "is_flag", False):
        return "flag"
    name = getattr(getattr(param, "type", None), "name", "") or ""
    shown = {"text": "text", "integer": "number", "float": "number", "boolean": "flag"}.get(
        name, name
    )
    return f"{shown}, repeatable" if getattr(param, "multiple", False) else shown


def _options(command: Any) -> tuple[list[Any], list[Any]]:
    arguments, options = [], []
    for param in command.params:
        if getattr(param, "name", "") == "help":
            continue
        (
            options
            if getattr(param, "opts", None) and param.param_type_name == "option"
            else arguments
        ).append(param)
    return arguments, options


def _usage(path: list[str], command: Any) -> str:
    arguments, options = _options(command)
    parts = ["strata", *path]
    if options:
        parts.append("[OPTIONS]")
    if hasattr(command, "commands") and command.commands:
        parts.append("COMMAND")
    for argument in arguments:
        name = (
            argument.human_readable_name.upper()
            if hasattr(argument, "human_readable_name")
            else argument.name.upper()
        )
        parts.append(name if argument.required else f"[{name}]")
    return " ".join(parts)


def _render_command(path: list[str], command: Any, depth: int) -> Iterable[str]:
    heading = "#" * depth
    yield f"{heading} `strata {' '.join(path)}`"
    yield ""
    help_text = _clean((command.help or "").strip())
    if help_text:
        yield help_text.rstrip()
        yield ""
    yield "```"
    yield _usage(path, command)
    yield "```"
    yield ""
    arguments, options = _options(command)
    if arguments:
        yield "| Argument | | Meaning |"
        yield "|---|---|---|"
        for argument in arguments:
            name = (
                argument.human_readable_name
                if hasattr(argument, "human_readable_name")
                else argument.name
            )
            need = "required" if argument.required else "optional"
            yield f"| `{name}` | {need} | {_cell(getattr(argument, 'help', '') or '')} |"
        yield ""
    if options:
        yield "| Option | Takes | Default | Meaning |"
        yield "|---|---|---|---|"
        for option in options:
            names = ", ".join(f"`{o}`" for o in option.opts)
            if getattr(option, "required", False):
                names += " (required)"
            env = getattr(option, "envvar", None)
            meaning = _cell(getattr(option, "help", "") or "")
            if env:
                meaning = f"{meaning} (environment variable `{env}`)".strip()
            yield f"| {names} | {_type_name(option)} | {_default(option)} | {meaning} |"
        yield ""
    if hasattr(command, "commands") and command.commands:
        for name in command.commands:
            yield from _render_command([*path, name], command.commands[name], depth + 1)


def build() -> dict[str, str]:
    root = get_command(app)
    commands = dict(root.commands)
    known = {name for _, _, _, names in PAGES for name in names}
    missing = sorted(set(commands) - known - INTERNAL)
    if missing:
        raise SystemExit(
            f"commands without a wiki reference page: {', '.join(missing)}; add them to PAGES"
        )
    stale = sorted(known - set(commands))
    if stale:
        raise SystemExit(f"PAGES names commands that no longer exist: {', '.join(stale)}")

    pages: dict[str, str] = {}
    for stem, title, blurb, names in PAGES:
        lines = [
            f"# {title}",
            "",
            f"{blurb} Part of the [Command reference](Command-Reference).",
            "",
            "> This page is generated from the program's own help text by `scripts/build_wiki_reference.py`."
            " Do not edit it by hand; change the help text in the code and regenerate.",
            "",
            "Contents: " + ", ".join(f"[`{n}`](#strata-{n.replace(' ', '-')})" for n in names),
            "",
        ]
        for name in names:
            command = commands[name]
            lines.extend(_render_command([name], command, 2))
            guides = GUIDES.get(name, [])
            if guides:
                lines.append("Guide: " + ", ".join(f"[{label}]({page})" for page, label in guides))
                lines.append("")
        pages[stem] = "\n".join(lines).rstrip() + "\n"

    glob = [p for p in root.params if getattr(p, "name", "") != "help"]
    rows = []
    for option in glob:
        names = ", ".join(f"`{o}`" for o in option.opts)
        rows.append(
            f"| {names} | {_type_name(option)} | {_cell(getattr(option, 'help', '') or '')} |"
        )
    index = [
        "# Command reference",
        "",
        "Every `strata` command, with its options. The pages are generated from the program's own help text, so they are"
        " exact; the guides ([Home](Home)) explain when and why to use each. In a terminal, `strata COMMAND --help`"
        " prints the same.",
        "",
        "## Pages",
        "",
        *[f"- [{title}]({stem}): {blurb}" for stem, title, blurb, _ in PAGES],
        "",
        "## Options that go before the command",
        "",
        'These apply to every command and are written *before* its name: `strata --why "..." import ...`.',
        "",
        "| Option | Takes | Meaning |",
        "|---|---|---|",
        *rows,
        "",
        "`--why` is the reason recorded in the history (a terminal asks you if you do not give it);"
        " `--json` prints machine-readable output; `-C PATH` runs the command as if started in `PATH`; `--no-commit`"
        " performs the operation and leaves the tree uncommitted.",
        "",
        "## Conventions",
        "",
        "- **Actor handles** (`--by ada`) say who is doing something. Handles are lowercase letters, digits and hyphens.",
        "- **Record ids** (`rec_...`), **report ids** (`rpt_...`) and **study ids** (`std_...`) can be shortened to any"
        " unambiguous prefix, as in git.",
        "- **Stages** are `title-abstract` and `full-text`.",
        "- A command that changes the review makes a commit; it needs a reason (`--why`).",
        "",
        "## Exit codes",
        "",
        "`0` success; `1` error; `2` wrong usage; `3` not inside a review; `4` the repository does not validate;"
        " `5` a conflict needing a decision; `6` the review is from a newer version; `7` a reason was required and not"
        " given; `8` a guardrail refused. See [Recovery and troubleshooting](Recovery-and-Troubleshooting#exit-codes).",
        "",
        "## Commands not listed",
        "",
        "`strata internal ...`, `strata merge-records` and `strata merge-regenerate` are called by git (hooks and merge"
        " drivers) and are not meant to be run by hand.",
        "",
    ]
    pages["Command-Reference"] = "\n".join(index)
    return pages


def main(argv: list[str]) -> int:
    pages = build()
    check = "--check" in argv
    wrong = []
    for stem, text in pages.items():
        path = WIKI / f"{stem}.md"
        if check:
            if not path.exists() or path.read_text(encoding="utf-8") != text:
                wrong.append(path.name)
        else:
            path.write_text(text, encoding="utf-8")
    if check and wrong:
        print(
            "out of date (run: uv run python scripts/build_wiki_reference.py): " + ", ".join(wrong)
        )
        return 1
    print(("checked " if check else "wrote ") + f"{len(pages)} pages")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
