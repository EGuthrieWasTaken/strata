"""Specification integrity checks.

Implements docs/spec/14-testing.md §9.6, run by `.github/workflows/docs.yml`
on every pull request:

1. Every relative markdown link resolves to a file that exists.
2. Every `#anchor` resolves to a heading that exists in the target file.
3. Every fenced `toml`, `yaml`, and `json` block in `docs/spec/` parses.
4. Every document referenced in `docs/spec/README.md` exists, and every
   document in `docs/spec/` is listed there.
"""

from __future__ import annotations

import json as json_mod
import re
import sys
import tomllib
from collections import Counter
from pathlib import Path

from ruamel.yaml import YAML

SPEC_DIR = Path(__file__).resolve().parent.parent / "docs" / "spec"
README = SPEC_DIR / "README.md"

_LINK_RE = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$", re.MULTILINE)
_FENCE_RE = re.compile(r"```(toml|yaml|json)\n(.*?)```", re.DOTALL)
_STRIP_MARKDOWN_RE = re.compile(r"[`*_]")
_NON_SLUG_RE = re.compile(r"[^a-z0-9 -]")
_DOC_LINK_RE = re.compile(r"\((\d\d-[a-z0-9-]+\.md)\)")


def slugify(heading: str) -> str:
    """Approximate GitHub's heading -> anchor algorithm (verified against the
    one real cross-document anchor link this spec currently uses)."""
    text = _STRIP_MARKDOWN_RE.sub("", heading).lower()
    text = _NON_SLUG_RE.sub("", text)
    return text.replace(" ", "-")


def headings_for(path: Path) -> set[str]:
    text = path.read_text(encoding="utf-8")
    slugs = [slugify(m.group(2)) for m in _HEADING_RE.finditer(text)]
    seen: Counter[str] = Counter()
    result = set()
    for slug in slugs:
        seen[slug] += 1
        result.add(slug if seen[slug] == 1 else f"{slug}-{seen[slug] - 1}")
    return result


def check_links_and_anchors() -> list[str]:
    errors = []
    for md_file in sorted(SPEC_DIR.glob("*.md")):
        text = md_file.read_text(encoding="utf-8")
        for match in _LINK_RE.finditer(text):
            target = match.group(1)
            if target.startswith(("http://", "https://", "mailto:")):
                continue
            path_part, _, anchor = target.partition("#")
            target_path = (md_file.parent / path_part).resolve() if path_part else md_file
            if path_part and not target_path.exists():
                errors.append(f"{md_file.name}: broken link target {target!r}")
                continue
            if anchor and anchor not in headings_for(target_path):
                errors.append(f"{md_file.name}: anchor {target!r} not found in {target_path.name}")
    return errors


def check_fenced_blocks() -> list[str]:
    errors = []
    yaml = YAML(typ="safe")
    for md_file in sorted(SPEC_DIR.glob("*.md")):
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
                errors.append(f"{md_file.name}:{line}: invalid {lang} block: {exc}")
    return errors


def check_readme_index() -> list[str]:
    errors = []
    readme_text = README.read_text(encoding="utf-8")
    listed = set(_DOC_LINK_RE.findall(readme_text))
    actual = {p.name for p in SPEC_DIR.glob("*.md") if p.name != "README.md"}
    for missing in sorted(actual - listed):
        errors.append(f"README.md: {missing} exists but is not listed in the document map")
    for extra in sorted(listed - actual):
        errors.append(f"README.md: lists {extra} but it does not exist")
    return errors


def main() -> int:
    errors = check_links_and_anchors() + check_fenced_blocks() + check_readme_index()
    if errors:
        for error in errors:
            print(f"::error::{error}")
        print(f"\n{len(errors)} specification integrity issue(s) found.", file=sys.stderr)
        return 1
    print("specification integrity checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
