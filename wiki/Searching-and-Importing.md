# Searching and importing

Searching happens in the databases themselves (Ovid, PubMed, Scopus, ...). `strata` does two things around it:
it records *exactly what you searched* (PRISMA items 6 and 7) and it brings the results in with their
provenance, so that for any record you can later ask where it came from.

## The rhythm for each search

1. Run the search in the database and note the date and the number of hits.
2. **Record the search** with its query verbatim.
3. Export the results from the database.
4. **Import the export**, naming the search it came from.

```
strata --why "Recording the MEDLINE search" search add \
    --database MEDLINE --platform Ovid --by ada --executed 2026-10-01 --hits 8 \
    --query "1. exp Learning/ 2. (spaced or distributed or massed) adj3 practi*.ti,ab. 3. 1 and 2"
strata --why "Importing the MEDLINE export" import --by ada --search S-01-medline medline-export.ris
```

```
recorded search S-01-medline
imported medline-export.ris as imp_01m5p5sm4k7ny08j3gp0x6phd0: 7 new, 1 matched existing, 0 rejected
```

### Recording a search

`strata search add` writes `protocol/searches/<id>.yaml`.

| Option | Meaning |
|---|---|
| `--database` | The database, e.g. MEDLINE, Embase, PsycINFO |
| `--platform` | The interface you actually used, e.g. Ovid, EBSCOhost, PubMed (the same database searches differently on different platforms) |
| `--by` | Who ran it |
| `--query` or `--query-file` | The query, verbatim. Use `--query-file` for long, multi-line strategies |
| `--executed` | Date run (`YYYY-MM-DD`), default today |
| `--hits` | How many results the platform reported |
| `--notes` | Filters applied (language, years) and anything else a reader needs |
| `--export-file` | The export file(s) this search produced (repeatable) |
| `--peer-reviewed-by` | Who peer-reviewed the strategy (PRESS), if anyone |
| `--supersedes` | The id of an earlier version of this search (when you re-run an updated strategy) |
| `--id` | Override the generated id |

Ids are `S-<nn>-<database>`, where `nn` counts searches *per database*: your first MEDLINE search is
`S-01-medline`, your first Embase search is `S-01-embase` (not `S-02-...`), and re-running MEDLINE is
`S-02-medline`. `strata search list` shows them all:

```
S-01-embase          Embase         2026-10-02  3 hits
S-01-medline         MEDLINE        2026-10-01  8 hits
```

If you re-run a search later (an update before submission), record it as a new search with `--supersedes` and
import the new export. Records you already have are recognised and not duplicated; only new ones arrive, and
the PRISMA counts show them.

### Importing an export

`strata import FILE... --by YOU --search S-01-medline` copies the raw file into the repository
(`imports/<id>/raw/`, unchanged), parses it, gives every reference a stable id, and commits. Each file is its
own import and its own commit.

| Option | Meaning |
|---|---|
| `--search` | The search this export came from (required for database searches) |
| `--via` | For records that did **not** come from a database search: `citation-searching`, `website`, `organisation`, `registry` or `contact`. These feed the "other methods" column of the PRISMA diagram |
| `--format` | Override format detection (see below) |
| `--map` | For CSV/TSV: map columns to fields, e.g. `title="Article Title",author=Authors,doi=DOI` |
| `--sheet` | For `.xlsx`: the sheet name or position (default the first) |
| `--dry-run` | Parse and report, write nothing |

**Try `--dry-run` first with a new kind of file.** It tells you how many records would be created and which
rows would be rejected and why, without touching the review.

### Formats

`strata` detects the format from the file. These are supported:

| Format | Typical source |
|---|---|
| RIS (`.ris`) | Most databases, EndNote, Zotero, Mendeley |
| PubMed/MEDLINE (`.nbib`, `.txt`) | PubMed "Save > Citation manager" |
| BibTeX (`.bib`) | Google Scholar, LaTeX users, Zotero |
| CSL-JSON (`.json`) | Zotero, Pandoc, other tools |
| EndNote XML (`.xml`) | EndNote "Export > XML" |
| CSV / TSV (`.csv`, `.tsv`) | Scopus, Web of Science, EBSCOhost, ProQuest, Dimensions, Google Scholar (Publish or Perish); other columns via `--map` |
| Excel (`.xlsx`) | Spreadsheets; read as the CSV would be (formula results, not formulas) |
| Plain-text reference list (`.txt`) | A numbered Vancouver or APA reference list pasted from a paper |

A plain-text reference list is parsed on a best-effort basis: each record gets the flag `best-effort-parse`,
and duplicate detection never merges a flagged record automatically (it asks you), because a guessed title or
year should not silently erase a real record. For database CSVs, the columns of the six platform exports above
are recognised from the header row, so `strata import scopus.csv` just works; for any other CSV give `--map`.

### What import does with problems

- **A row it cannot use is rejected with a reason**, listed at the end ("0 rejected" above), and the rest of
  the file is imported. A rejected row is never silently dropped: its reason is in the import record.
- **Importing the same file twice does nothing**; identical records are recognised by an id built from the
  normalised DOI/title/authors/year. "7 new, 1 matched existing" means one entry in that file was the same
  paper as another.
- **Encoding and format quirks** (a byte-order mark, Windows line endings, CP1252 "smart quotes", HTML
  entities, a missing end-of-record marker) are handled.
- **Nothing is fetched.** `strata` does not look anything up unless you enable *enrichment* in
  `strata.toml` (it then only asks Unpaywall for legal open-access links).

## Looking at what you have

```
strata records list                                  # id, year, authors, title
strata records list --filter "year >= 2015 and title contains 'spacing'"
strata records show rec_bja43jkhyfj1qxwv             # one record with its sources
strata why rec_bja43jkhyfj1qxwv                      # its complete history
```

`--filter` uses a small safe expression language shared by the whole tool: see
[Filter language](Filter-Language). `strata why` is the provenance view: for the record in the example it
shows the search it came from (database, platform, date, the full query), the import (file digest, row), and
the duplicate merge that absorbed another record into it, with the scores that justified the merge.

```
SEARCH by ada
  id: S-01-medline
  database: MEDLINE
  platform: Ovid
  executed: 2026-10-01
  query: 1. exp Learning/ 2. (spaced or distributed or massed) adj3 practi*.ti,ab. 3. 1 and 2
  hits: 8

IMPORT 2026-10-24T05:23:04Z by ada
  count: 7
  import_id: imp_01m5p5sm4k7ny08j3gp0x6phd0
  search_id: S-01-medline
  source: medline-export.ris

RECORD-ADD 2026-10-24T05:23:04Z by ada
  record: rec_bja43jkhyfj1qxwv

DEDUP-MERGE 2026-10-24T05:24:04Z by ada
  absorbed: rec_7cd2313c81sxpyce
```

### Correcting a record

If an export has a wrong title, year or page, correct it rather than editing a file:

```
strata --why "Export truncated the title" fix rec_bja43jkhyfj1qxwv --field title --value "The corrected title" --by ada
```

You can correct plain text fields: `title`, `container-title` (journal), `volume`, `issue`, `page`, `DOI`,
`PMID`, `PMCID`, `URL`, `ISBN`, `abstract` and a few others. The change is recorded as an event with the old
and new value, and `strata why` shows it. Authors and dates are structured fields and are not yet editable
this way.

## Before you move on

- `strata search list` shows every database you searched, with a hit count that matches the platform's.
- Each import's "new + matched" accounts for the references in the file (the PRISMA identification numbers are
  built from these counts, and `strata verify` checks they add up).
- You have run `strata dedup` ([Removing duplicates](Removing-Duplicates)).

Next: [Removing duplicates](Removing-Duplicates).
