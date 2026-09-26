# ci-gate Specification Delta

## MODIFIED Requirements

### Requirement: Specification integrity checks

`docs.yml` MUST verify on every pull request that:

1. Every relative Markdown link in `README.md`, `docs/`, `openspec/`, and
   `.github/` resolves to an existing file.
2. Every `#anchor` in those links resolves to an existing heading in the target
   file.
3. Every fenced `toml`, `yaml`, and `json` block in `openspec/` and `docs/`
   parses.
4. Every capability under `openspec/specs/` has both a `spec.md` and a
   `design.md` and is listed in `openspec/README.md`, and every capability
   listed there exists.
5. Every `openspec:<capability>` and `openspec:<capability>#<requirement-slug>`
   reference in the repository resolves to an existing capability and
   requirement, in `openspec/specs/` or in a change's delta specs.
6. No file outside the historical milestone plans and the changelog refers to
   the retired long-form specification directory.
7. The OpenSpec specs and change proposals under `openspec/` pass
   `openspec validate --all --strict`.

#### Scenario: Renamed requirement

- **WHEN** a requirement is renamed and a code comment still cites its old slug
- **THEN** the `docs` job fails naming the file, line, and unresolved reference

#### Scenario: Renumbered section

- **WHEN** a heading is renamed and another document still links to its old anchor
- **THEN** the `docs` job fails naming the broken anchor

#### Scenario: Requirement without a scenario

- **WHEN** a pull request adds an OpenSpec requirement with no scenario
- **THEN** the `docs` job fails

#### Scenario: Capability without a design note

- **WHEN** a pull request adds `openspec/specs/<capability>/spec.md` without a `design.md`
- **THEN** the `docs` job fails
