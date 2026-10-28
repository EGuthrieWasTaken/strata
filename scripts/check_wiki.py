"""Check the wiki pages in `wiki/`.

    uv run python scripts/check_wiki.py

Fails when:
  * a link names a page or a heading that does not exist;
  * a page is missing from `_Sidebar.md`;
  * the generated command reference is out of date (`scripts/build_wiki_reference.py --check`);
  * a `strata ...` example in a code block names a command, subcommand or option that does not exist.

Part of the documentation checks (`docs` in CI), alongside `scripts/check_docs.py`.
"""

# ruff: noqa: E501
from __future__ import annotations

import re
import shlex
import subprocess
import sys
from pathlib import Path

from typer.main import get_command

from strata.cli.main import app

ROOT = Path(__file__).resolve().parents[1]
WIKI = ROOT / "wiki"
SPECIAL = {"_Sidebar", "_Footer"}

LINK = re.compile(r"(?<!\!)\[([^\]]*)\]\(([^)\s]+)\)")
FENCE = re.compile(r"^(\s*)(```|~~~)")
HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")


def slug(heading: str) -> str:
    """GitHub's anchor for a heading."""
    text = re.sub(r"[`*_]", "", heading.strip().lower())
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
    return re.sub(r"[^\w\- ]", "", text).replace(" ", "-")


def parse(path: Path) -> tuple[list[str], list[tuple[int, str]], list[tuple[int, str]]]:
    """Headings (as slugs), links (line, target) outside code, and code lines (line, text)."""
    headings: list[str] = []
    links: list[tuple[int, str]] = []
    code: list[tuple[int, str]] = []
    in_fence = False
    seen: dict[str, int] = {}
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if FENCE.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            code.append((number, line))
            continue
        match = HEADING.match(line)
        if match:
            base = slug(match.group(2))
            count = seen.get(base, 0)
            seen[base] = count + 1
            headings.append(base if count == 0 else f"{base}-{count}")
        stripped = re.sub(r"`[^`]*`", "", line)
        links.extend((number, m.group(2)) for m in LINK.finditer(stripped))
    return headings, links, code


def command_tree() -> tuple[dict, set[str]]:
    root = get_command(app)
    return dict(root.commands), {o for p in root.params for o in getattr(p, "opts", [])}


def option_names(command: object) -> set[str]:
    names: set[str] = set()
    for param in getattr(command, "params", []):
        names.update(getattr(param, "opts", []))
        names.update(getattr(param, "secondary_opts", []))
    return names


GLOBAL_WITH_VALUE = {"-C", "--why", "--why-file", "-v"}


def check_example(line: str, commands: dict, global_opts: set[str]) -> str | None:
    text = line.strip()
    if text.startswith("$ "):
        text = text[2:]
    if not text.startswith("strata "):
        return None
    text = text.split(" #", 1)[0].rstrip("\\ ").strip()
    try:
        tokens = shlex.split(text)[1:]
    except ValueError:
        return (
            None  # a continued or partial line; the first line of a command is checked on its own
        )
    index = 0
    while index < len(tokens) and tokens[index].startswith("-"):
        if tokens[index] not in global_opts:
            return f"unknown option {tokens[index]!r} before the command"
        index += 2 if tokens[index] in GLOBAL_WITH_VALUE else 1
    if index >= len(tokens):
        return None
    name = tokens[index]
    if name not in commands:
        # Prose in an output block ("strata serve listening on ...") is not a command; only judge
        # lines whose first word looks like a command name and is followed by options or arguments.
        return f"unknown command {name!r}"
    command = commands[name]
    rest = tokens[index + 1 :]
    path = [name]
    subs = getattr(command, "commands", None)
    if subs:
        if rest and not rest[0].startswith("-") and rest[0] in subs:
            command = subs[rest[0]]
            path.append(rest[0])
            rest = rest[1:]
        elif rest and not rest[0].startswith("-"):
            return f"unknown subcommand {rest[0]!r} of `strata {name}`"
    allowed = option_names(command) | {"--help"}
    for token in rest:
        if token.startswith("--"):
            option = token.split("=", 1)[0]
            if option not in allowed:
                return f"`strata {' '.join(path)}` has no option {option}"
    return None


def main() -> int:
    pages = {p.stem: p for p in sorted(WIKI.glob("*.md"))}
    parsed = {stem: parse(path) for stem, path in pages.items()}
    errors: list[str] = []

    for stem, (_headings, links, _code) in parsed.items():
        for number, target in links:
            if re.match(r"^[a-z][a-z0-9+.-]*:", target) or target.startswith("mailto:"):
                continue
            page, _, anchor = target.partition("#")
            if not page:
                page = stem
            if page not in pages:
                errors.append(f"{stem}.md:{number}: link to missing page {page!r}")
                continue
            if anchor and anchor not in parsed[page][0]:
                errors.append(f"{stem}.md:{number}: no heading {anchor!r} in {page}.md")

    sidebar = parsed.get("_Sidebar")
    if sidebar is None:
        errors.append("wiki/_Sidebar.md is missing")
    else:
        listed = {t.split("#")[0] for _, t in sidebar[1]}
        for stem in pages:
            if stem not in SPECIAL and stem not in listed and not stem.startswith("Commands-"):
                errors.append(f"{stem}.md is not in the sidebar")

    commands, global_opts = command_tree()
    for stem, (_h, _l, code) in parsed.items():
        if stem.startswith("Commands-"):
            continue  # generated; its usage lines are exact by construction
        for number, line in code:
            problem = check_example(line, commands, global_opts)
            if problem:
                errors.append(f"{stem}.md:{number}: {problem}: {line.strip()[:90]}")

    reference = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "build_wiki_reference.py"), "--check"],
        capture_output=True, text=True, check=False,
    )  # fmt: skip
    if reference.returncode != 0:
        errors.append(
            (reference.stdout + reference.stderr).strip() or "command reference out of date"
        )

    for error in errors:
        print(error)
    if errors:
        print(f"\n{len(errors)} problem(s) in the wiki.")
        return 1
    print(f"wiki ok: {len(pages)} pages.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
