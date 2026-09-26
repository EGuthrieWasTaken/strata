# Proposal: Retire the long-form specification documents

## Why

After the conversion to OpenSpec, the specification existed twice: normative
requirements in `openspec/specs/` and the original long-form documents they came
from. Two sources of truth drift, and OpenSpec's change workflow only updates
one of them. The project lead decided to retire the long-form documents.

## What Changes

- The long-form specification directory is deleted. Its normative content is
  already in `openspec/specs/`; its rationale, worked examples, and rejected
  alternatives move into a `design.md` beside each capability's `spec.md` (and
  into the design documents of the changes for unbuilt milestones); its overview,
  roadmap, and open questions move to `docs/overview.md`, `docs/roadmap.md`, and
  `docs/open-questions.md`.
- Every reference in code, tests, scripts, workflows, templates, and JSON
  Schemas is rewritten to the `openspec:<capability>#<requirement-slug>` form.
- The specification integrity checks change accordingly: they cover
  `openspec/` and `docs/`, require a `design.md` per capability and an index
  entry in `openspec/README.md`, resolve every `openspec:` reference in the
  repository, and reject new references to the retired directory.
- The historical milestone plans and the changelog keep their original
  citations as records of the time; the retired text remains in git history.

## Capabilities

### New Capabilities

(none)

### Modified Capabilities

- `ci-gate`: the "Specification integrity checks" requirement now describes
  checks over `openspec/` and `docs/`.

## Impact

- `scripts/check_docs.py` rewritten, with unit tests; `docs.yml` unchanged in
  shape.
- No runtime behaviour changes; JSON Schema `description` strings and a few
  error messages now cite `openspec:` references instead of section numbers.
- No schema-version bump.
