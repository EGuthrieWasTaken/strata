# project-documentation Specification

## Purpose

User-facing documentation as a release requirement: the audience-oriented
documentation set, the project wiki that carries it, and the process that keeps
it current by updating it in the same pull request as the feature.

Rationale: `docs/spec/13-nonfunctional.md` §8; `docs/spec/15-roadmap.md` M2.1 (Wiki).

## Requirements

### Requirement: Documentation set

The project MUST maintain, as a release requirement, a documentation set
covering: a quickstart (first review in 30 minutes), an "I have never used git"
guide, a methods-text cookbook, a statistical methods reference with formulae
and sources, a repository format reference, a recovery guide, and a
contributing guide including how to add a parser.

_Source: `docs/spec/13-nonfunctional.md` §8_

#### Scenario: Release readiness

- **WHEN** a release is prepared
- **THEN** each document in the set exists and reflects the released behaviour

### Requirement: Project wiki

The project MUST keep a GitHub Wiki (`strata.wiki.git`) carrying the
audience-oriented documentation — quickstart, first-time-git guide, per-command
CLI reference, web UI walkthrough, and a concepts section (staleness, criteria
versioning and direction, dedup, blinding) — written for reviewers rather than
implementers, and treated as a live document.

_Source: `docs/spec/15-roadmap.md` M2.1 (Wiki)_

#### Scenario: Concept page

- **WHEN** a reviewer looks up staleness in the wiki
- **THEN** they find a concepts page explaining it in methodologist terms, not implementation terms

### Requirement: Documentation ships with the feature

The pull-request template MUST include a Wiki checklist item asking whether the
change adds or alters a user-facing command, web screen, or concept, and if so
whether the corresponding wiki page was updated in the same pull request or a
fast-follow. This MUST remain a review-time checklist prompt, not a CI gate.

_Source: `docs/spec/15-roadmap.md` M2.1 (Wiki)_

#### Scenario: New CLI flag

- **WHEN** a pull request adds a user-facing flag
- **THEN** its template checklist prompts the author to update the wiki page for that command
