# Commands: full texts, studies, extraction and risk of bias

Retrieval, Zotero, grouping reports into studies, data extraction, risk of bias. Part of the [Command reference](Command-Reference).

> This page is generated from the program's own help text by `scripts/build_wiki_reference.py`. Do not edit it by hand; change the help text in the code and regenerate.

Contents: [`retrieve`](#strata-retrieve), [`zotero`](#strata-zotero), [`studies`](#strata-studies), [`extract`](#strata-extract), [`rob`](#strata-rob)

## `strata retrieve`

Work the queue of reports sought for retrieval:

Interactive by default. With --report and --outcome it records one outcome and exits
(scriptable); with --list it prints the outstanding reports.

Example: strata retrieve --by ethan --report rpt_3kq8v1r0zx2m4a7b --outcome retrieved
--source institutional-access --version version-of-record

```
strata retrieve [OPTIONS]
```

| Option | Takes | Default | Meaning |
|---|---|---|---|
| `--by` (required) | str |  | Actor handle recording the outcome |
| `--report` | str |  | Record one outcome for this report |
| `--outcome` | str |  | retrieved \| ill-requested \| not-retrieved \| sought |
| `--source` | str |  | e.g. institutional-access |
| `--version` | str |  | preprint \| version-of-record \| ... |
| `--path` | str |  | Local file path (a convenience only) |
| `--locator` | str, repeatable |  | kind=value (doi, pmid, ...); repeatable |
| `--reason` | str |  | Why it could not be retrieved |
| `--reason-text` | str |  | Required for 'other' |
| `--list` | flag |  | List outstanding reports and exit |
| `--zotero` | flag |  | With --outcome retrieved: record the document as held in Zotero, by its item key |

Guide: [Retrieving full texts](Retrieving-Full-Texts)

## `strata zotero`

Optional: link a review to Zotero (it holds the documents, strata holds the decisions).

```
strata zotero COMMAND
```

### `strata zotero link`

Link this review to a Zotero library and map the records it already has to its items.

Uses Zotero's local API when the desktop app offers it (no key, nothing leaves this computer),
and the Web API otherwise. Records are matched to items by DOI, then PMID, then title, year and
first author; an item that matches nothing is listed, never forced onto the nearest record. An
API key is kept only in your operating system's keychain, or read from $STRATA_ZOTERO_API_KEY.

```
strata zotero link [OPTIONS]
```

| Option | Takes | Default | Meaning |
|---|---|---|---|
| `--by` (required) | str |  | Actor handle linking the review |
| `--library` | str |  | users/<id> or groups/<id>; asked for if there is a choice |
| `--web` | flag |  | Use the Web API (needs an API key) so included studies can be pushed to Zotero |

### `strata zotero pull`

Pull a Zotero collection as an import source.

Exactly one of --search (the collection holds the results of a recorded database search) and
--via (a hand-built collection, counted by PRISMA as another method) is required. The
collection's name and the day it was pulled are kept for the PRISMA report. Items already
linked to a record correct it where Zotero's bibliographic metadata differs, each correction a
`record-amend` event; no screening decision ever crosses.

```
strata zotero pull [OPTIONS]
```

| Option | Takes | Default | Meaning |
|---|---|---|---|
| `--collection` (required) | str |  | A Zotero collection, by name or key |
| `--by` (required) | str |  | Actor handle running the pull |
| `--search` | str |  | Id of the recorded search whose results the collection holds |
| `--via` | str |  | For a hand-built collection: citation-searching \| website \| organisation \| registry \| contact |

### `strata zotero push`

Put the included studies in a Zotero collection, so you can cite them while writing.

Creates Zotero items for studies Zotero lacks and adds the ones it has to the collection. It
never deletes anything, never changes an item it did not create beyond adding it to the
collection, and refuses (item by item) any item edited in Zotero since strata last saw it: pull
first. Needs a link made with --web and an API key that can write.

```
strata zotero push [OPTIONS]
```

| Option | Takes | Default | Meaning |
|---|---|---|---|
| `--collection` (required) | str |  | A Zotero collection, by name or key |
| `--by` (required) | str |  | Actor handle running the push |
| `--set` | str | `included` | Which records to push: included |

### `strata zotero status`

Which records are linked to Zotero, which are not, and which links have gone stale.

```
strata zotero status
```

### `strata zotero open`

Open a record's PDF (or, with no PDF, its item) in Zotero.

```
strata zotero open [OPTIONS] RECORD
```

| Argument | | Meaning |
|---|---|---|
| `record` | required | A record id, or any unambiguous prefix of one |

| Option | Takes | Default | Meaning |
|---|---|---|---|
| `--print-only` | flag |  | Print the zotero:// link instead of opening it |

Guide: [Using Zotero](Using-Zotero)

## `strata studies`

Group reports into studies and split multi-study reports:

Suggestions (shared trial registration, shared authors and sample, follow-up language,
mutual citation) are shown with their evidence and never applied automatically. Every
grouping and splitting decision needs a rationale (--why).

Example: strata --why "Same trial, 12-month follow-up" studies --by ethan \
 --group rpt_3kq8v1r0zx2m4a7b --group rpt_9m2f4t7c1x8a5d6e

```
strata studies [OPTIONS]
```

| Option | Takes | Default | Meaning |
|---|---|---|---|
| `--by` | str |  | Actor handle recording the decision |
| `--list` | flag |  | Show the counts and suggestions only |
| `--group` | str, repeatable |  | Report id to group; repeat per report |
| `--study` | str |  | With --group: redefine this study |
| `--split` | str |  | Report id to split into studies |
| `--into` | int | `2` | With --split: how many studies |

Guide: [Grouping reports into studies](Grouping-Reports-into-Studies)

## `strata extract`

Extract data from included studies:

`strata extract init` drafts the coding form from the protocol's moderators and outcomes.
`strata extract` walks the studies (`--missing`: only those lacking required values; `NR` means
not reported; add '@ p.4' after a value for its source). With dual extraction each reviewer
works into their own files and `--reconcile` settles the differences.

Example: strata extract std_3kq8v1r0zx2m4a7b --by ethan --set "n_total=120 @ Table 1" \
 --effect '{"outcome": "memory", "design": "two-group-means", "n1": 20, "m1": 5.1, ...}'

```
strata extract [OPTIONS] [TARGET]
```

| Argument | | Meaning |
|---|---|---|
| `target` | optional | `init`, or a study id (a prefix will do) |

| Option | Takes | Default | Meaning |
|---|---|---|---|
| `--by` | str |  | Actor handle extracting |
| `--missing` | flag |  | Only studies with missing required values |
| `--reconcile` | flag |  | Reconcile dual extractions |
| `--list` | flag |  | List the queue and exit |
| `--overwrite` | flag |  | With init: replace the coding form |
| `--set` | str, repeatable |  | NAME=VALUE ('value @ source' ok); repeatable |
| `--effect` | str, repeatable |  | An effect as a JSON object; repeatable |
| `--ack` | str, repeatable |  | CODE=EFFECT_KEY: accept a data-quality warning |
| `--note` | str |  | With --ack: why the warning is acceptable |
| `--item` | str |  | With --reconcile: the item to settle |
| `--choose` | str |  | A reviewer's handle, agreement, other |
| `--value` | str |  | With --choose other: the value |
| `--rationale` | str |  | Why this choice |
| `--source` | str |  | Source locator for the chosen value |

Guide: [Extracting data](Extracting-Data)

## `strata rob`

Risk-of-bias assessment:

`strata rob init --instrument rob2|rob2-adhering|robins-i|nos-cohort|nos-case-control` copies
a built-in instrument into rob/instrument.yaml. `strata rob <study>` walks the domains: the
signalling questions the RoB 2 algorithm needs, its suggested judgement, and your judgement
(an override of the suggestion needs a justification).

Example: strata rob std_3kq8v1r0zx2m4a7b --by ethan --domain D1 --answer 1.1=Y \
 --answer 1.2=Y --answer 1.3=N --judgement low --support "Central randomisation"

```
strata rob [OPTIONS] [TARGET]
```

| Argument | | Meaning |
|---|---|---|
| `target` | optional | `init`, or a study id (a prefix will do) |

| Option | Takes | Default | Meaning |
|---|---|---|---|
| `--by` | str |  | Actor handle assessing |
| `--instrument` | str | `rob2` | With init: rob2, rob2-adhering, robins-i, nos-cohort, nos-case-control |
| `--overwrite` | flag |  | With init: replace the instrument |
| `--list` | flag |  | Show the assessments and exit |
| `--reconcile` | flag |  | Reconcile dual assessments |
| `--domain` | str |  | A domain id, or overall |
| `--answer` | str, repeatable |  | QUESTION=ANSWER, e.g. 1.2=Y; repeatable |
| `--judgement` | str |  | The judgement for --domain |
| `--support` | str |  | Supporting quote or note |
| `--source` | str |  | Source locator (page, section) |
| `--override-justification` | str |  | Why this differs from the suggestion |
| `--choose` | str |  | With --reconcile: a reviewer's handle, agreement, other |
| `--value` | str |  | With --choose other: the judgement |
| `--rationale` | str |  | Why this choice |

Guide: [Risk of bias](Risk-of-Bias)
