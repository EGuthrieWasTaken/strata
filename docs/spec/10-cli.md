# 10 — Command-line interface *(normative)*

## 1. Conventions

```
epic [global options] <command> [subcommand] [arguments] [options]
```

**Global options**

| Option | Effect |
|---|---|
| `-C <path>` | Run as if started in `<path>` |
| `--why <text>` | Supply the commit rationale non-interactively |
| `--why-file <path>` | Read the rationale from a file |
| `--no-commit` | Perform the operation, stage nothing, leave the tree dirty |
| `--json` | Machine-readable output on stdout; human output moves to stderr |
| `-q` / `-v` / `-vv` | Quieter / verbose / debug |
| `--yes` | Assume yes for confirmations. Never bypasses a rationale prompt. |
| `--no-color` | Also honoured via `NO_COLOR` |
| `--version`, `--help` | Standard |

**Conventions**

- Every command that mutates the repository commits, unless `--no-commit`.
- Every command that mutates the repository is safe to interrupt: events are
  appended and fsynced before any derived regeneration, so `Ctrl-C` loses at most
  the commit, which `epic status` then offers to complete.
- Long operations show progress on stderr and are silent under `-q`.
- `--json` output is a stable, versioned contract; breaking it is a minor-version
  bump.
- Record ids may be abbreviated to any unambiguous prefix, as in git.

**Exit codes**

| Code | Meaning |
|---|---|
| 0 | Success |
| 1 | Generic failure |
| 2 | Usage error |
| 3 | Not an `epic` repository |
| 4 | Validation failure (`epic verify` found problems) |
| 5 | Merge/sync conflict requiring human resolution |
| 6 | Schema version too new (`E_SCHEMA_TOO_NEW`) |
| 7 | Refused: the operation would require a rationale and none was available |
| 8 | Refused: a guardrail blocked the operation (use `--force`) |

## 2. Command reference

### Setup

| Command | Description |
|---|---|
| `epic init [--title T] [--remote URL]` | Create a repository: layout, `epic.toml`, `.gitattributes`, hooks, merge drivers, initial commit. Interactive unless `--title` given. |
| `epic clone <url>` | `git clone` plus merge-driver and hook installation plus `epic verify` |
| `epic doctor` | Diagnose and repair: missing merge drivers, missing hooks, stale cache, git version, unreadable files. `--fix` applies repairs. |
| `epic migrate` | Upgrade the repository to the current schema version |
| `epic config <key> [value]` | Read or set `epic.toml` values |
| `epic actor add\|list\|deactivate` | Manage contributors |

### Protocol

| Command | Description |
|---|---|
| `epic criteria list [--at STAGE] [--version N]` | Show criteria |
| `epic criteria add` | Add a criterion (interactive or flags) |
| `epic criteria edit <ID>` | Edit; prompts for direction ([06 §3.2](06-workflow-screening.md)) |
| `epic criteria retire <ID>` | Retire; behaves as `loosened` |
| `epic criteria diff <v1> <v2>` | Show what changed between versions and what it invalidated |
| `epic search add [--id ID]` | Record an executed search |
| `epic search list` | Show all searches with dates and hit counts |
| `epic moderators add\|list\|edit` | Manage planned moderators |

### Literature

| Command | Description |
|---|---|
| `epic import <file>... --search <id>` | Import exports. `--via`, `--map`, `--format`, `--dry-run` |
| `epic dedup [--review] [--strict]` | Run deduplication; `--review` opens the queue |
| `epic dedup --undo <canonical> <absorbed>` | Reverse a merge |
| `epic records list [--filter EXPR]` | List records; `--format tsv\|json\|csl` |
| `epic records show <id>` | Full record with sources and provenance |
| `epic fix <id> --field <f> --value <v>` | Correct a metadata field, recording the change |

### Screening

| Command | Description |
|---|---|
| `epic screen <stage> [--filter EXPR] [--limit N]` | Open the screening queue |
| `epic rescreen [--stage S]` | Open the stale queue |
| `epic adjudicate [--stage S]` | Resolve conflicts |
| `epic assign <stage> --actors a,b [--filter EXPR]` | Assign reviewers |
| `epic irr [--stage S]` | Inter-rater reliability report |
| `epic audit --criteria [--sample N]` | Re-present a random sample of past exclusions for verification ([06 §4.3](06-workflow-screening.md)) |

### Full text and extraction

| Command | Description |
|---|---|
| `epic retrieve` | Work the retrieval queue |
| `epic studies` | Group reports into studies; suggest groupings and splits |
| `epic extract init` | Generate a draft coding form from the protocol |
| `epic extract [<study>] [--missing]` | Extract data |
| `epic extract --reconcile [<study>]` | Reconcile dual extractions |
| `epic rob [<study>]` | Risk-of-bias assessment |

### Analysis and reporting

| Command | Description |
|---|---|
| `epic analyze [<id>] [--all]` | Run an analysis specification; writes `analysis/results/<id>/` |
| `epic analyze --check` | Validate analysis specs and report guardrails without computing |
| `epic prisma [--format F] [--columns one\|both]` | Flow diagram |
| `epic report <section>` | `methods`, `results`, `characteristics`, `amendments`, `checklist`, `rob`, `manuscript` |
| `epic export <what> --format F` | `effects`, `records`, `bibliography`, `package` |

### Repository operations

| Command | Description |
|---|---|
| `epic status` | The dashboard: stage counts, conflicts, stale, missing data, outstanding requirements |
| `epic sync` | Fetch, merge, regenerate, verify, push ([04 §5](04-git-integration.md)) |
| `epic verify [--fast] [--fix]` | Validate the whole repository ([03 §10](03-schemas.md)) |
| `epic log [--criteria] [--stage S] [--actor A]` | Domain-level history |
| `epic why <id>` | Full provenance for a record, report, study, or effect |
| `epic diff <ref>..<ref>` | Domain-level diff between two commits |
| `epic serve [--port N]` | Start the local web UI ([11](11-web-ui.md)) |

## 3. Filter expressions *(normative)*

`--filter` accepts a small, safe expression language used identically in the CLI,
the web UI, and analysis specifications. It MUST NOT be implemented by evaluating
the host language (no `eval`, no `exec`); it is parsed to an AST and interpreted.

**Grammar**

```
expr    := or_expr
or_expr := and_expr ("or" and_expr)*
and_expr:= not_expr ("and" not_expr)*
not_expr:= "not" not_expr | primary
primary := "(" expr ")" | comparison | field
comparison := field op value
op      := "==" | "!=" | "<" | "<=" | ">" | ">=" | "in" | "not in" | "contains" | "matches"
value   := string | number | boolean | null | list
```

**Available fields**

| Field | Type | Notes |
|---|---|---|
| `id`, `doi`, `pmid` | string | |
| `title`, `abstract`, `journal` | string | `contains` is case-insensitive substring; `matches` is a regex |
| `year` | integer | |
| `authors` | list of strings | `contains` tests any family name |
| `tiab`, `fulltext` | string | Screening state |
| `stale` | boolean | |
| `criteria` | list | Criteria cited at the resolved decision |
| `via` | string | `database`, `citation-searching`, ... |
| `search` | string | Search id |
| `actor_decision.<handle>` | string | One reviewer's opinion |
| `<moderator>` / `<extraction field>` | per schema | Available once extracted |
| `rob_overall`, `rob.<domain>` | string | |
| `derived_from_pvalue`, `assumed_correlation` | boolean/number | Effect-level |

`matches` MUST use a linear-time regex engine or enforce a timeout; user-supplied
patterns must not be able to hang the tool.

**Examples**

```
year >= 2000 and tiab == 'include'
abstract contains 'randomi' and not (journal contains 'Proceedings')
stale == true and fulltext == 'include'
rob_overall in ['low', 'some-concerns']
criteria contains 'EXC-03'
```

## 4. `epic status` output

The default view, and the answer to "where am I?":

```
$ epic status

  Spaced retrieval and long-term retention                   criteria v4
  38 commits · 2 actors · last sync 2 hours ago · clean

  SEARCHES        4 databases, 7,282 records identified, last run 2026-03-04
                  ! S-04-psycinfo has no query string recorded  (PRISMA item 7)

  DEDUPLICATION   2,918 canonical  (4,364 duplicates removed)
                  47 pairs awaiting review                     epic dedup --review

  TITLE/ABSTRACT  2,918 records
                  ############################......  4,002 / 4,182 resolved
                  14 conflicts                                 epic adjudicate
                  180 stale                                    epic rescreen

  FULL TEXT       204 reports · 196 assessed · 8 not retrieved
                  21 stale (upstream)

  EXTRACTION      38 studies · 31 complete · 5 partial · 2 not started
                  3 studies with unreconciled disagreements     epic extract --reconcile

  ANALYSIS        primary        stale (data changed since last run)
                  sensitivity    up to date

  NEXT            epic rescreen        180 records, ~55 min at your recent pace
```

Every line that reports a problem MUST name the command that addresses it. The
tool should never report a state the user cannot act on.

## 5. Non-interactive use

Every interactive workflow MUST have a scriptable equivalent, so that reviews can
be driven from CI or reproduced from a script:

```
epic import *.ris --search S-01 --why "initial MEDLINE search"
epic screen title-abstract --decisions decisions.tsv --why "imported from pilot"
epic analyze --all --json > results.json
epic verify --json
```

`epic screen --decisions <file>` accepts a TSV of
`record_id  decision  criteria  note` and is the supported path for importing
screening work done in another tool. Imported decisions MUST be attributed to the
declared actor and marked `imported: true` in the event body, because their
independence cannot be verified.

## 6. Error message requirements *(normative)*

Every error MUST state what happened, why, and what to do next. The tool's users
are researchers under deadline pressure, not developers.

```
  error: cannot run `epic analyze primary`

  3 included studies have no reconciled extraction:

    std_7x2k9m1p3v5r8t0w   Larsen et al. (2009)
    std_2b8n4k6m0p2r4t6v   Kornell (2009)
    std_9v3x1z5c7b9n1m3q   Roediger & Karpicke (2006)

  Extract them first:   epic extract --missing
  Or exclude them from this analysis by editing the `include.filter`
  in analysis/primary.yaml.
```

Errors MUST NOT include stack traces unless `-vv` is set. A crash MUST write a
full report to `.epic/crash-<timestamp>.log` and print the path plus the issue
tracker URL.
