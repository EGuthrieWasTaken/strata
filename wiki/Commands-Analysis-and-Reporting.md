# Commands: analysis and reporting

Pooling, the PRISMA diagram, generated text, exports. Part of the [Command reference](Command-Reference).

> This page is generated from the program's own help text by `scripts/build_wiki_reference.py`. Do not edit it by hand; change the help text in the code and regenerate.

Contents: [`analyze`](#strata-analyze), [`prisma`](#strata-prisma), [`report`](#strata-report), [`export`](#strata-export)

## `strata analyze`

Run analysis specifications and write analysis/results/<id>/.

Results are written, and committed, only when you run this command. `--check` validates the
specifications and reports guardrails without computing anything. A blocking guardrail exits
with code 8 unless `--force` is given; the bypass is recorded in run.json.

Example: strata analyze primary --ack exploratory

```
strata analyze [OPTIONS] [ANALYSIS_ID]
```

| Argument | | Meaning |
|---|---|---|
| `analysis_id` | optional | An analysis id (analysis/<id>.yaml) |

| Option | Takes | Default | Meaning |
|---|---|---|---|
| `--all` | flag |  | Run every analysis specification |
| `--check` | flag |  | Validate specifications and report guardrails without computing |
| `--force` | flag |  | Bypass blocking guardrails (recorded) |
| `--ack` | str, repeatable |  | Acknowledge a named warning; repeatable |
| `--plot-format` | str | `svg` | svg \| pdf \| png |

Guide: [Analysis](Analysis), [Statistical methods](Statistical-Methods)

## `strata prisma`

The PRISMA 2020 flow diagram, drawn from the event log:

Every count is derived and every reconciliation identity is asserted first (a broken one is
E_COUNT_RECONCILE, exit code 4). While any decision is stale the command refuses (exit code 8)
unless `--allow-stale`; the diagram is then watermarked DRAFT, as it is whenever screening is
unfinished. The default output, reports/prisma.<format>, is committed.

Example: strata prisma --columns both --format svg

```
strata prisma [OPTIONS]
```

| Option | Takes | Default | Meaning |
|---|---|---|---|
| `--format` | str | `svg` | svg \| pdf \| png \| json |
| `--columns` | str | `one` | one \| both (other methods in a second column) |
| `--allow-stale` | flag |  | Render a DRAFT even though decisions are stale |
| `--out` | str |  | Write here (`-` for standard output); default reports/prisma.<format> |

Guide: [Reporting](Reporting)

## `strata report`

Generate manuscript material from the repository:

Methods and Results (and the characteristics table, the amendments, the risk-of-bias table and
the PRISMA checklist) are drafted from what the repository records, marked with the commit
they came from. strata does not write a Discussion or a Conclusion. Output goes to
reports/<section>.<format> and is committed.

Example: strata report manuscript --format docx

```
strata report [OPTIONS] SECTION
```

| Argument | | Meaning |
|---|---|---|
| `section` | required | methods \| results \| characteristics \| amendments \| checklist \| rob \| manuscript |

| Option | Takes | Default | Meaning |
|---|---|---|---|
| `--status` | flag |  | checklist: how many items remain |
| `--format` | str | `md` | md \| html \| docx \| latex (csv for characteristics, svg for rob) |
| `--out` | str |  | Write here (`-` for standard output) |

Guide: [Reporting](Reporting), [Methods-text cookbook](Methods-Text-Cookbook)

## `strata export`

Export data for analysis elsewhere.

```
strata export COMMAND
```

### `strata export effects`

One row per effect, with study-level and effect-level moderators joined, for outside
analysis:

The columns include `study_id`, `effect_id`, `yi` and `vi`, so the CSV loads straight into
`metafor::rma(yi, vi, data = read.csv("effects.csv"))`. xlsx and rds are binary and need --out.

Example: strata export effects --format csv --out effects.csv

```
strata export effects [OPTIONS]
```

| Option | Takes | Default | Meaning |
|---|---|---|---|
| `--format` | str | `csv` | csv \| tsv \| xlsx \| rds \| json |
| `--out` | str |  | Write here instead of standard output |

### `strata export bibliography`

A bibliography of one set of records:

CSL-JSON feeds pandoc directly (`pandoc --citeproc --bibliography=included.json`); the
`excluded-at-fulltext` set is the appendix of studies excluded at full-text screening.

Example: strata export bibliography --format ris --set excluded-at-fulltext --out excluded.ris

```
strata export bibliography [OPTIONS]
```

| Option | Takes | Default | Meaning |
|---|---|---|---|
| `--format` | str | `csl` | bibtex \| csl \| ris |
| `--set` | str | `included` | included \| excluded-at-fulltext \| all-screened \| not-retrieved |
| `--out` | str |  | Write here instead of standard output |

### `strata export package`

The reproducibility package for PRISMA item 27: search strategies, criteria and their
history, the decision log, extraction data, analysis specifications and results, the data
licence, and a README naming the commit. It contains no full texts.

Example: strata export package --out supplement.zip

```
strata export package [OPTIONS]
```

| Option | Takes | Default | Meaning |
|---|---|---|---|
| `--out` (required) | str |  | The archive to write (a .zip) |

### `strata export provenance`

Every extracted value with its study and source locator, one row each: the provenance table
of

Example: strata export provenance --format tsv --out provenance.tsv

```
strata export provenance [OPTIONS]
```

| Option | Takes | Default | Meaning |
|---|---|---|---|
| `--format` | str | `csv` | csv \| tsv \| xlsx \| rds \| json |
| `--out` | str |  | Write here instead of standard output |

Guide: [Reporting](Reporting), [Extracting data](Extracting-Data)
