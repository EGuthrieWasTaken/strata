## What this changes

## Tests
- [ ] A test exists that fails without this change
- [ ] New normative requirements are linked to their test ids
- [ ] Touched one of: ids / normalisation / canon / fold / staleness?
      -> property cases added, schema version reviewed

## Spec
- [ ] OpenSpec change proposed/archived under openspec/ (validated with
      `openspec validate --all --strict`), or this changes no specified behaviour
- [ ] `openspec:` references updated for any renamed requirement
      (`uv run python scripts/check_docs.py`)
- [ ] Schema version bumped, or this is not a breaking format change

## Wiki
- [ ] Wiki updated (the pages are in `wiki/`; run
      `uv run python scripts/build_wiki_reference.py` after changing a command's help and
      `uv run python scripts/check_wiki.py`) for any new/changed user-facing command,
      web screen, or concept, or this PR has none (a fast-follow is fine)
