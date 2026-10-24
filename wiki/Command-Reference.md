# Command reference

Every `strata` command, with its options. The pages are generated from the program's own help text, so they are exact; the guides ([Home](Home)) explain when and why to use each. In a terminal, `strata COMMAND --help` prints the same.

## Pages

- [Commands: project and repository](Commands-Project): Create, clone and check a review; settings; the team; history.
- [Commands: searching, importing and records](Commands-Literature): Record searches, import exports, remove duplicates, inspect and correct records.
- [Commands: criteria and screening](Commands-Screening): Eligibility criteria, assigning and screening records, re-screening, adjudication, agreement.
- [Commands: full texts, studies, extraction and risk of bias](Commands-Full-Texts-and-Extraction): Retrieval, grouping reports into studies, data extraction, risk of bias.
- [Commands: analysis and reporting](Commands-Analysis-and-Reporting): Pooling, the PRISMA diagram, generated text, exports.
- [Commands: sharing, the web interface and tools](Commands-Sharing-and-Tools): Syncing a shared review, the browser interface, the read-only assistant server, CI helpers.

## Options that go before the command

These apply to every command and are written *before* its name: `strata --why "..." import ...`.

| Option | Takes | Meaning |
|---|---|---|
| `--version` | flag | Show the version and exit |
| `-C` | str | Run as if started in <path> |
| `--json` | flag | Machine-readable output on stdout |
| `-q` | flag |  |
| `-v` | int |  |
| `--no-color` | flag |  |
| `--yes` | flag |  |
| `--why` | str | Supply the commit rationale non-interactively |
| `--why-file` | str | Read the rationale from a file |
| `--no-commit` | flag | Perform the operation, stage nothing, leave the tree dirty |

`--why` is the reason recorded in the history (a terminal asks you if you do not give it); `--json` prints machine-readable output; `-C PATH` runs the command as if started in `PATH`; `--no-commit` performs the operation and leaves the tree uncommitted.

## Conventions

- **Actor handles** (`--by ada`) say who is doing something. Handles are lowercase letters, digits and hyphens.
- **Record ids** (`rec_...`), **report ids** (`rpt_...`) and **study ids** (`std_...`) can be shortened to any unambiguous prefix, as in git.
- **Stages** are `title-abstract` and `full-text`.
- A command that changes the review makes a commit; it needs a reason (`--why`).

## Exit codes

`0` success; `1` error; `2` wrong usage; `3` not inside a review; `4` the repository does not validate; `5` a conflict needing a decision; `6` the review is from a newer version; `7` a reason was required and not given; `8` a guardrail refused. See [Recovery and troubleshooting](Recovery-and-Troubleshooting#exit-codes).

## Commands not listed

`strata internal ...`, `strata merge-records` and `strata merge-regenerate` are called by git (hooks and merge drivers) and are not meant to be run by hand.
