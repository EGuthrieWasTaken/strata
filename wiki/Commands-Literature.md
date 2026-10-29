# Commands: searching, importing and records

Record searches, import exports, remove duplicates, inspect and correct records. Part of the [Command reference](Command-Reference).

> This page is generated from the program's own help text by `scripts/build_wiki_reference.py`. Do not edit it by hand; change the help text in the code and regenerate.

Contents: [`search`](#strata-search), [`import`](#strata-import), [`dedup`](#strata-dedup), [`records`](#strata-records), [`why`](#strata-why), [`fix`](#strata-fix)

## `strata search`

Record and list executed searches.

```
strata search COMMAND
```

### `strata search add`

Record an executed search: `protocol/searches/<id>.yaml`.

```
strata search add [OPTIONS]
```

| Option | Takes | Default | Meaning |
|---|---|---|---|
| `--database` (required) | str |  | e.g. MEDLINE, Embase, PsycINFO |
| `--platform` (required) | str |  | Interface actually used, e.g. Ovid |
| `--by` (required) | str |  | Actor handle who ran the search |
| `--id` | str |  | Defaults to S-<nn>-<database> |
| `--executed` | str |  | Date run YYYY-MM-DD; default today |
| `--query` | str |  | The verbatim query string |
| `--query-file` | str |  | Read the query from a file |
| `--hits` | int |  |  |
| `--export-file` | str, repeatable |  | May be repeated |
| `--peer-reviewed-by` | str |  |  |
| `--notes` | str |  |  |
| `--supersedes` | str |  | Id of an earlier version |

### `strata search list`

Show all searches with dates and hit counts.

```
strata search list
```

Guide: [Searching and importing](Searching-and-Importing)

## `strata import`

Import one or more bibliographic exports: copy raw, parse, assign ids, commit.

Each file is its own import (`imports/<id>/`) and, unless `--dry-run`/`--no-commit`, its own commit —
a failure partway through a multi-file import leaves every earlier file's
import already committed rather than the tree half-written and dirty.

```
strata import [OPTIONS] FILES
```

| Argument | | Meaning |
|---|---|---|
| `files` | required | One or more export files to import |

| Option | Takes | Default | Meaning |
|---|---|---|---|
| `--by` (required) | str |  | Actor handle who ran the import |
| `--search` | str |  | Id of the search that produced this export |
| `--via` | str |  | citation-searching \| website \| organisation \| registry \| contact |
| `--format` | str |  | Override format detection: csl-json \| ris \| bibtex \| medline \| endnote-xml \| csv \| tsv \| xlsx \| citation-list |
| `--sheet` | str |  | For .xlsx: the sheet name or position (default: the first sheet) |
| `--map` | str |  | CSV/TSV column mapping, e.g. title=Article Title,author=Authors,doi=DOI |
| `--dry-run` | flag |  | Parse and report without writing anything |

Guide: [Searching and importing](Searching-and-Importing)

## `strata dedup`

Find and auto-merge obvious duplicates; `--review` walks the rest interactively.

```
strata dedup [OPTIONS]
```

| Option | Takes | Default | Meaning |
|---|---|---|---|
| `--by` (required) | str |  | Actor handle running dedup |
| `--review` | flag |  | Interactively work the review queue |
| `--strict` | flag |  | Force both thresholds to 1.0 |
| `--undo` | <str str> | `('', '')` | CANONICAL_ID ABSORBED_ID: reverse one merge |

Guide: [Removing duplicates](Removing-Duplicates), [How deduplication works](How-Deduplication-Works)

## `strata records`

List and inspect bibliographic records.

```
strata records COMMAND
```

### `strata records list`

List records; `--filter` narrows them, `--format` controls the output shape.

```
strata records list [OPTIONS]
```

| Option | Takes | Default | Meaning |
|---|---|---|---|
| `--filter` | str |  | Filter expression, |
| `--format` | str | `tsv` | tsv \| json \| csl |
| `--all` | flag |  | Include absorbed duplicates (excluded by default) |

### `strata records show`

Full record: metadata, sources, and dedup/provenance flags.

```
strata records show RECORD_ID
```

| Argument | | Meaning |
|---|---|---|
| `record_id` | required |  |

Guide: [Searching and importing](Searching-and-Importing), [Filter language](Filter-Language)

## `strata why`

Full provenance for a record: search, import, amendments, and dedup history.

```
strata why RECORD_ID
```

| Argument | | Meaning |
|---|---|---|
| `record_id` | required |  |

Guide: [Searching and importing](Searching-and-Importing)

## `strata fix`

Correct a metadata field, recording the change as a `record-amend` event.

Plain-text fields (title, journal, DOI, ...), `author` and the date (`year`, or `issued` for a
full date) can be corrected. An empty value removes the field. A DOI, PMID, PMCID or ISBN is
stored as an import would store it, and a value the record already has changes nothing. A
correction that changes how the record is identified keeps its id, and an export carrying the
corrected value is then matched to it.

```
strata fix [OPTIONS] RECORD_ID
```

| Argument | | Meaning |
|---|---|---|
| `record_id` | required |  |

| Option | Takes | Default | Meaning |
|---|---|---|---|
| `--field` (required) | str |  | The field to correct (title, author, year, DOI, ...) |
| `--value` (required) | str |  | The corrected value (authors: 'Family, Given; Family, Given'; a date: YYYY-MM-DD) |
| `--by` (required) | str |  | Actor handle making the correction |

Guide: [Searching and importing](Searching-and-Importing)
