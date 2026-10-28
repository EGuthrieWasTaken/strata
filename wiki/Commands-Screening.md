# Commands: criteria and screening

Eligibility criteria, assigning and screening records, re-screening, adjudication, agreement. Part of the [Command reference](Command-Reference).

> This page is generated from the program's own help text by `scripts/build_wiki_reference.py`. Do not edit it by hand; change the help text in the code and regenerate.

Contents: [`criteria`](#strata-criteria), [`assign`](#strata-assign), [`screen`](#strata-screen), [`rescreen`](#strata-rescreen), [`adjudicate`](#strata-adjudicate), [`irr`](#strata-irr), [`audit`](#strata-audit)

## `strata criteria`

Manage inclusion/exclusion criteria.

```
strata criteria COMMAND
```

### `strata criteria add`

Add a criterion. A criterion added behaves as `tightened`.

```
strata criteria add [OPTIONS]
```

| Option | Takes | Default | Meaning |
|---|---|---|---|
| `--kind` (required) | str |  | inclusion \| exclusion |
| `--label` (required) | str |  |  |
| `--definition` (required) | str |  |  |
| `--applies-at` (required) | str |  | Comma-separated stages |
| `--by` (required) | str |  | Actor handle making the change |
| `--id` | str |  |  |

### `strata criteria edit`

Edit a criterion; MUST classify the change's direction.

```
strata criteria edit [OPTIONS] CRITERION_ID
```

| Argument | | Meaning |
|---|---|---|
| `criterion_id` | required |  |

| Option | Takes | Default | Meaning |
|---|---|---|---|
| `--direction` (required) | str |  | tightened \| loosened \| both \| editorial |
| `--by` (required) | str |  | Actor handle making the change |
| `--definition` | str |  |  |
| `--label` | str |  |  |
| `--applies-at` | str |  | Comma-separated stages |

### `strata criteria retire`

Retire a criterion; behaves as `loosened`.

```
strata criteria retire [OPTIONS] CRITERION_ID
```

| Argument | | Meaning |
|---|---|---|
| `criterion_id` | required |  |

| Option | Takes | Default | Meaning |
|---|---|---|---|
| `--by` (required) | str |  |  |

### `strata criteria list`

```
strata criteria list [OPTIONS]
```

| Option | Takes | Default | Meaning |
|---|---|---|---|
| `--at` | str |  | Filter to criteria applying at this stage |
| `--version` | int |  | Reconstruct the set as of version N |

### `strata criteria diff`

Show what changed between two criteria versions.

```
strata criteria diff V1 V2
```

| Argument | | Meaning |
|---|---|---|
| `v1` | required |  |
| `v2` | required |  |

Guide: [Setting up a review](Setting-Up-a-Review), [Changing criteria mid-review](Changing-Criteria-Mid-Review), [Criteria versions and direction](Criteria-Versions-and-Direction)

## `strata assign`

Assign reviewers to records at `stage` (all canonical records by default).

```
strata assign [OPTIONS] STAGE
```

| Argument | | Meaning |
|---|---|---|
| `stage` | required |  |

| Option | Takes | Default | Meaning |
|---|---|---|---|
| `--actors` (required) | str |  | Comma-separated actor handles |
| `--by` (required) | str |  | Actor handle recording the assignment |
| `--filter` | str |  | Assign only matching records |

Guide: [Screening](Screening)

## `strata screen`

Open the screening queue for `stage`, or bulk-import decisions with `--decisions`.

```
strata screen [OPTIONS] STAGE
```

| Argument | | Meaning |
|---|---|---|
| `stage` | required |  |

| Option | Takes | Default | Meaning |
|---|---|---|---|
| `--by` (required) | str |  | Actor handle doing the screening |
| `--filter` | str |  | Narrow the queue |
| `--limit` | int |  | Screen at most N records |
| `--decisions` | str |  | TSV of record_id/decision/criteria/note |

Guide: [Screening](Screening), [Blinding and independence](Blinding-and-Independence)

## `strata rescreen`

Open the stale queue:

```
strata rescreen [OPTIONS]
```

| Option | Takes | Default | Meaning |
|---|---|---|---|
| `--stage` | str |  | Restrict to one stage |
| `--by` (required) | str |  | Actor handle doing the re-screening |
| `--mark` | str, repeatable |  | Force record(s) stale (manual reason) instead of re-screening |

Guide: [Changing criteria mid-review](Changing-Criteria-Mid-Review), [Staleness](Staleness)

## `strata adjudicate`

Resolve screening conflicts:

```
strata adjudicate [OPTIONS]
```

| Option | Takes | Default | Meaning |
|---|---|---|---|
| `--stage` | str |  | Restrict to one stage |
| `--by` (required) | str |  | Actor handle adjudicating |

Guide: [Adjudication and agreement](Adjudication-and-Agreement)

## `strata irr`

Inter-rater reliability, over independent first opinions.

Read-only with respect to the event log: recomputes and rewrites
`derived/irr.json` on disk, but does not commit -- the next mutating
screening command's commit (or a manual commit) picks the file up, same
as any other derived view.

```
strata irr [OPTIONS]
```

| Option | Takes | Default | Meaning |
|---|---|---|---|
| `--stage` | str |  | Restrict to one stage |

Guide: [Adjudication and agreement](Adjudication-and-Agreement)

## `strata audit`

Re-present a random sample of past exclusions for verification.

```
strata audit [OPTIONS]
```

| Option | Takes | Default | Meaning |
|---|---|---|---|
| `--criteria` | flag |  | Sample past exclusions for criterion-citation review |
| `--sample` | int | `20` | Sample size |
| `--seed` | int |  | Reproduce a specific sample |

Guide: [Adjudication and agreement](Adjudication-and-Agreement)
