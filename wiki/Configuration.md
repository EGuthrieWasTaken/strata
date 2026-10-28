# Configuration (`strata.toml`)

A review's settings live in `strata.toml` at the top of the review folder. It is plain text; read or set a
value with `strata config`:

```
strata config screening.mode                    # read
strata config screening.blind_metadata true     # set (booleans, numbers and text are recognised)
```

> `strata config` changes the file but does **not** commit it yet. After changing a setting, run
> `git commit -am "settings: ..."` so the change is part of the history and is shared by `strata sync`
> ([Known limitations](Known-Limitations)).

A freshly created review contains:

```toml
schema_version = 1
created_with = "strata/0.1.0"

[project]
id = "prj_01m5p5pw9bds9y3ps0e3ha9b7v"
title = "Spacing and retention"
slug = "spacing-and-retention"
created = "2026-10-24"

[[actors]]
handle = "ada"
name = "Ada Example"
role = "lead"

[screening]
stages = ["title-abstract", "full-text"]
mode = "dual"
adjudicators = ["ada"]
blind_reviewers = true
blind_metadata = false
require_exclusion_reason = true

[dedup]
auto_merge_threshold = 0.95
review_threshold = 0.8
source_trust = ["crossref", "pubmed", "scopus", "wos", "embase", "ebsco", "manual"]

[git]
commit_style = "structured"
require_rationale = true
sync_strategy = "merge"
remote = "origin"

[enrichment]
enabled = false
providers = []
contact_email = ""

[analysis]
engine = "native"
```

## Settings

### `[project]`

| Key | Meaning |
|---|---|
| `title` | The review's title |
| `license` | The licence you give the review data (for example `CC-BY-4.0`). **Required by `strata export package`**, which refuses to build a supplement without one |
| `registry` | A table of register name to number, for example `PROSPERO = "CRD42026000000"` (PRISMA item 24a) |
| `funding` | A table with `sources` (a list of text) and `role_of_funders` (text) (item 25) |
| `competing_interests` | A table with `statement` and/or `declarations` (a list of `{author, statement}`) (item 26) |

For example:

```toml
[project]
license = "CC-BY-4.0"

[project.registry]
PROSPERO = "CRD42026000000"

[project.funding]
sources = ["National Education Research Council grant 123"]
role_of_funders = "The funder had no role in the design, conduct or reporting of the review."
```

Add these by editing the file (nested tables are easiest to write by hand) and commit.

### `[[actors]]`

One entry per person: `handle`, `name`, `role`, optionally `email`. Manage with `strata actor add|list|deactivate`
rather than editing.

### `[screening]`

| Key | Default | Meaning |
|---|---|---|
| `stages` | `["title-abstract", "full-text"]` | The stages, in order. A one-stage review can list just `title-abstract` |
| `mode` | `dual` | `dual` (two independent reviewers) or `single` (a pilot; disclosed in the generated Methods) |
| `adjudicators` | the lead | Who may resolve conflicts |
| `blind_reviewers` | `true` | Hide one reviewer's decision from the other until both have decided |
| `blind_metadata` | `false` | Also hide authors, journal and year while screening |
| `require_exclusion_reason` | `true` | An exclusion must cite at least one criterion (always required at full text) |
| `assignment` | everyone | Default reviewers per stage, if you do not want every screener on every record |

### `[extraction]`

| Key | Default | Meaning |
|---|---|---|
| `mode` | `single` | `dual` makes two extractors work independently, then reconcile |

(The section is absent until you add it.)

### `[dedup]`

| Key | Default | Meaning |
|---|---|---|
| `auto_merge_threshold` | `0.95` | Pairs scoring at least this are merged automatically |
| `review_threshold` | `0.8` | Pairs scoring at least this (and below the first) go to the review queue |
| `source_trust` | CrossRef, PubMed, Scopus, WoS, Embase, EBSCO, manual | When two sources disagree on a field, the earlier one wins |

See [How deduplication works](How-Deduplication-Works).

### `[git]`

| Key | Default | Meaning |
|---|---|---|
| `commit_style` | `structured` | Commits carry `Strata-` trailers that `strata log` reads |
| `require_rationale` | `true` | Every change needs a `--why` (adjudications and criteria changes always do) |
| `sync_strategy` | `merge` | `merge` or `rebase` for `strata sync` |
| `remote` | `origin` | Which remote `strata sync` uses |

### `[enrichment]`

Off by default. With `enabled = true`, `strata` may ask Unpaywall for a legal open-access link for a report you
are seeking; set `contact_email` to your address, which Unpaywall requires. Nothing is downloaded
automatically, and nothing else is looked up.

### `[analysis]`

| Key | Default | Meaning |
|---|---|---|
| `engine` | `native` | The built-in, `metafor`-validated engine |

## Environment variables

| Variable | Used by |
|---|---|
| `STRATA_TOKEN` | `strata serve`: a fixed session token (instead of `--token`) |
| `STRATA_PUBLIC_URL` | `strata serve`: the address browsers use (instead of `--public-url`) |
| `GIT_AUTHOR_NAME`, `GIT_AUTHOR_EMAIL`, `GIT_COMMITTER_NAME`, `GIT_COMMITTER_EMAIL` | git's identity for the commits `strata` makes (needed in a container) |
| `NO_COLOR` | switches off coloured output (as does `--no-color`) |
