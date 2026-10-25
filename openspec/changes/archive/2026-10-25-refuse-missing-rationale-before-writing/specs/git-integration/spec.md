# git-integration Specification Delta

## MODIFIED Requirements

### Requirement: Eliciting the rationale

When `git.require_rationale` is true (the default), a mutating command MUST
obtain a rationale before committing, using a prompt that tells the user what
changed so the answer is about why. The rationale:

- MUST NOT be empty or whitespace, and MUST be at least 12 characters.
- MUST NOT be one of the shipped stop-list values (`.`, `x`, `fix`, `update`,
  `wip`, `asdf`); rejection explains why the rationale matters.
- MAY be supplied with `--why "<text>"` or `--why-file <path>`.

In a non-interactive context with neither flag, the command MUST fail (exit
code 7) rather than invent a rationale. It MUST fail before it changes any file,
so that a refused command leaves the working tree as it found it. A rationale
given with `--why` or `--why-file` is checked at the same point, so one that
would be rejected also stops the command before it changes anything. A command
that makes no commit (`--no-commit`) needs no rationale, except that criteria
changes, adjudications and study decisions carry their rationale in the event
itself and always need one. An interactive run is prompted as before.

#### Scenario: Stop-listed rationale

- **WHEN** a user answers the rationale prompt with `wip`
- **THEN** the answer is rejected with an explanation and the prompt repeats

#### Scenario: Script without a rationale

- **WHEN** a mutating command runs non-interactively without `--why` or `--why-file`
- **THEN** it exits with code 7, makes no commit, and changes no file

#### Scenario: Rationale rejected before the work

- **WHEN** a mutating command runs non-interactively with `--why wip`
- **THEN** it exits with code 7 and changes no file

#### Scenario: No commit, no rationale

- **WHEN** a mutating command other than a criteria change, adjudication or study decision runs non-interactively with `--no-commit` and without `--why`
- **THEN** it makes its change, commits nothing, and exits with code 0

#### Scenario: Criteria edit prompt shows the impact

- **WHEN** a user tightens `EXC-03` interactively
- **THEN** the prompt states how many screening decisions the change invalidates before asking why
