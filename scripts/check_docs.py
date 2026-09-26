"""Specification integrity checks.

Implements openspec:ci-gate#specification-integrity-checks, run by
`.github/workflows/docs.yml` on every pull request alongside
`openspec validate --all --strict`:

1. Every relative Markdown link in the documentation resolves to a file that
   exists.
2. Every `#anchor` resolves to a heading that exists in the target file.
3. Every fenced `toml`, `yaml`, and `json` block in `openspec/` and `docs/`
   parses.
4. Every capability under `openspec/specs/` has both `spec.md` and
   `design.md`, and is listed in `openspec/README.md`; every capability listed
   there exists.
5. Every `openspec:<capability>` / `openspec:<capability>#<requirement-slug>`
   reference anywhere in the repository names a capability and requirement
   that exist (in `openspec/specs/` or a change's delta specs).
6. Nothing outside the historical milestone plans and the changelog refers to
   the retired specification directory.
"""

from __future__ import annotations

import json as json_mod
import re
import sys
import tomllib
from collections import Counter
from collections.abc import Iterable
from pathlib import Path

from ruamel.yaml import YAML

REPO_ROOT = Path(__file__).resolve().parent.parent

# Markdown checked for links/anchors, relative to the repository root.
MARKDOWN_GLOBS = ("README.md", "docs/**/*.md", "openspec/**/*.md", ".github/**/*.md")
# Where fenced config blocks must parse.
FENCE_GLOBS = ("docs/**/*.md", "openspec/**/*.md")
# Where `openspec:` references and retired-path references are looked for.
TEXT_ROOTS = ("src", "tests", "scripts", ".github", "docs", "openspec")
TEXT_FILES = ("README.md", "CHANGELOG.md", "pyproject.toml")
TEXT_SUFFIXES = {".py", ".md", ".yml", ".yaml", ".toml", ".json", ".html", ".js", ".css", ".txt"}
# Historical records, left as written: they describe the project as it was.
HISTORICAL = {"docs/m1-plan.md", "docs/m2-plan.md", "docs/m2.1-plan.md", "CHANGELOG.md"}
# Built by concatenation so this file does not trip its own check.
RETIRED_SPEC_DIR = "docs/" + "spec/"

_LINK_RE = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$", re.MULTILINE)
_FENCE_RE = re.compile(r"```(toml|yaml|json)\n(.*?)```", re.DOTALL)
_ANY_FENCE_RE = re.compile(r"```.*?```", re.DOTALL)
_STRIP_MARKDOWN_RE = re.compile(r"[`*_]")
_NON_SLUG_RE = re.compile(r"[^a-z0-9 -]")
_REQUIREMENT_RE = re.compile(r"^### Requirement:\s*(.+?)\s*$", re.MULTILINE)
_OPENSPEC_REF_RE = re.compile(r"openspec:([a-z0-9][a-z0-9-]*)(?:#([a-z0-9][a-z0-9-]*))?")


def slugify(heading: str) -> str:
    """Approximate GitHub's heading -> anchor algorithm."""
    text = _STRIP_MARKDOWN_RE.sub("", heading).lower()
    text = _NON_SLUG_RE.sub("", text)
    return text.replace(" ", "-")


def requirement_slug(name: str) -> str:
    """The `#slug` half of an `openspec:` reference: the requirement name
    lower-cased, with every run of other characters replaced by `-`."""
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def _files(root: Path, globs: Iterable[str]) -> list[Path]:
    found: set[Path] = set()
    for pattern in globs:
        found.update(p for p in root.glob(pattern) if p.is_file())
    return sorted(p for p in found if _rel(root, p) not in HISTORICAL)


def _rel(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix()


def headings_for(path: Path) -> set[str]:
    text = _ANY_FENCE_RE.sub("", path.read_text(encoding="utf-8"))
    slugs = [slugify(m.group(2)) for m in _HEADING_RE.finditer(text)]
    seen: Counter[str] = Counter()
    result = set()
    for slug in slugs:
        seen[slug] += 1
        result.add(slug if seen[slug] == 1 else f"{slug}-{seen[slug] - 1}")
    return result


def check_links_and_anchors(root: Path = REPO_ROOT) -> list[str]:
    errors = []
    for md_file in _files(root, MARKDOWN_GLOBS):
        text = _ANY_FENCE_RE.sub("", md_file.read_text(encoding="utf-8"))
        for match in _LINK_RE.finditer(text):
            target = match.group(1)
            if target.startswith(("http://", "https://", "mailto:")):
                continue
            path_part, _, anchor = target.partition("#")
            target_path = (md_file.parent / path_part).resolve() if path_part else md_file
            where = _rel(root, md_file)
            if path_part and not target_path.exists():
                errors.append(f"{where}: broken link target {target!r}")
                continue
            if anchor and target_path.is_file() and anchor not in headings_for(target_path):
                errors.append(f"{where}: anchor {target!r} not found in {target_path.name}")
    return errors


def check_fenced_blocks(root: Path = REPO_ROOT) -> list[str]:
    errors = []
    yaml = YAML(typ="safe")
    for md_file in _files(root, FENCE_GLOBS):
        text = md_file.read_text(encoding="utf-8")
        for match in _FENCE_RE.finditer(text):
            lang, body = match.group(1), match.group(2)
            try:
                if lang == "toml":
                    tomllib.loads(body)
                elif lang == "json":
                    json_mod.loads(body)
                else:
                    yaml.load(body)
            except Exception as exc:  # noqa: BLE001 — report every parse failure kind
                line = text[: match.start()].count("\n") + 1
                errors.append(f"{_rel(root, md_file)}:{line}: invalid {lang} block: {exc}")
    return errors


def known_requirements(root: Path = REPO_ROOT) -> dict[str, set[str]]:
    """Capability -> requirement slugs, from the main specs and every change's
    delta specs (archived changes are already merged into the main specs)."""
    specs = list((root / "openspec" / "specs").glob("*/spec.md"))
    specs += list((root / "openspec" / "changes").glob("*/specs/*/spec.md"))
    result: dict[str, set[str]] = {}
    for spec in specs:
        names = _REQUIREMENT_RE.findall(spec.read_text(encoding="utf-8"))
        result.setdefault(spec.parent.name, set()).update(requirement_slug(n) for n in names)
    return result


def check_capability_index(root: Path = REPO_ROOT) -> list[str]:
    errors = []
    specs_dir = root / "openspec" / "specs"
    readme = root / "openspec" / "README.md"
    readme_text = readme.read_text(encoding="utf-8") if readme.exists() else ""
    actual = {p.name for p in specs_dir.iterdir() if p.is_dir()} if specs_dir.exists() else set()
    listed = set(re.findall(r"\(specs/([a-z0-9-]+)/spec\.md\)", readme_text))
    for cap in sorted(actual):
        for required in ("spec.md", "design.md"):
            if not (specs_dir / cap / required).exists():
                errors.append(f"openspec/specs/{cap}: missing {required}")
    for missing in sorted(actual - listed):
        errors.append(f"openspec/README.md: capability {missing!r} is not listed")
    for extra in sorted(listed - actual):
        errors.append(f"openspec/README.md: lists capability {extra!r}, which does not exist")
    return errors


def _text_files(root: Path) -> list[Path]:
    found = [root / name for name in TEXT_FILES if (root / name).is_file()]
    for top in TEXT_ROOTS:
        base = root / top
        if base.is_dir():
            found += [
                p
                for p in base.rglob("*")
                if p.is_file() and p.suffix in TEXT_SUFFIXES and "__pycache__" not in p.parts
            ]
    return sorted(set(found))


def check_openspec_references(root: Path = REPO_ROOT) -> list[str]:
    errors = []
    known = known_requirements(root)
    for path in _text_files(root):
        where = _rel(root, path)
        if where in HISTORICAL:
            continue
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            for match in _OPENSPEC_REF_RE.finditer(line):
                cap, slug = match.group(1), match.group(2)
                if cap not in known:
                    errors.append(f"{where}:{lineno}: unknown capability in {match.group(0)!r}")
                elif slug and slug not in known[cap]:
                    errors.append(f"{where}:{lineno}: unknown requirement in {match.group(0)!r}")
    return errors


def check_no_retired_references(root: Path = REPO_ROOT) -> list[str]:
    errors = []
    for path in _text_files(root):
        where = _rel(root, path)
        if where in HISTORICAL:
            continue
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if RETIRED_SPEC_DIR in line:
                errors.append(
                    f"{where}:{lineno}: refers to the retired {RETIRED_SPEC_DIR} directory; "
                    "cite openspec:<capability>#<requirement> instead"
                )
    return errors


def run_all(root: Path = REPO_ROOT) -> list[str]:
    return (
        check_links_and_anchors(root)
        + check_fenced_blocks(root)
        + check_capability_index(root)
        + check_openspec_references(root)
        + check_no_retired_references(root)
    )


def main() -> int:
    errors = run_all()
    if errors:
        for error in errors:
            print(f"::error::{error}")
        print(f"\n{len(errors)} specification integrity issue(s) found.", file=sys.stderr)
        return 1
    print("specification integrity checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
