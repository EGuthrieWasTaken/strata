# 05 — Search, import, and deduplication *(normative)*

## 1. Recording a search

Before importing, the search that produced the export is recorded. `strata search
add` walks the user through it and writes `protocol/searches/<id>.yaml`
([03 §5](03-schemas.md)).

The tool MUST NOT let the user skip the query string. PRISMA item 7 requires the
full search strategy for every database, and reconstructing it after the fact is
the single most common reason systematic reviews fail replication. If the user
does not have the query to hand, `strata` records `query: "PENDING"` and
`strata status` reports it as an outstanding requirement until supplied.

Where the export format carries the query (PubMed `.nbib` sometimes does, Ovid
exports often do), `strata import` MUST offer to pre-fill it and MUST show the user
what it extracted for confirmation rather than accepting it silently.

## 2. Import

### 2.1 Supported formats *(normative)*

| Format | Extensions | Notes |
|---|---|---|
| RIS | `.ris`, `.txt` | The lingua franca. Tag-per-line; handle both `TY  - ` and `TY - ` spacing |
| PubMed / MEDLINE | `.nbib`, `.txt` | `PMID- `, `TI  - `, continuation lines indented six spaces |
| BibTeX | `.bib` | Brace-balanced parsing; preserve `@misc` and unknown fields |
| EndNote XML | `.xml` | `<records><record>` with style-nested text nodes |
| CSL-JSON | `.json` | Round-trips losslessly; the native format |
| CSV / TSV | `.csv`, `.tsv` | Platform-specific column mapping, §2.2 |
| Excel | `.xlsx` | Read-only; first sheet unless `--sheet` given |
| PRISMA-style citation list | `.txt` | Best-effort; always routed to manual review |

Parsers MUST be tolerant of the specific malformations these platforms actually
emit: BOM at start of file, CRLF and CR line endings, unescaped `&` in EndNote
XML, RIS records missing `ER  -`, non-UTF-8 encodings (try UTF-8, then UTF-8
with BOM, then CP1252, then Latin-1, and record which was used in the manifest),
and HTML entities in titles and abstracts.

A row that cannot be parsed MUST NOT abort the import. It is written verbatim to
`imports/<id>/rejected.txt` with the parse error and a line number, counted in
the manifest, and reported. Losing 3 records silently is worse than losing 3
records loudly.

### 2.2 CSV column mapping

CSV exports vary per platform and per user configuration, so mapping cannot be
hard-coded. `strata` MUST:

1. Ship detection profiles for common exports (EBSCOhost, Scopus, Web of Science,
   ProQuest, Dimensions, Google Scholar via Publish or Perish), matched by
   header signature.
2. On an unrecognised header row, present an interactive mapping UI (or accept
   `--map title=Article Title,doi=DOI,...`).
3. Save the resolved mapping to `imports/<id>/manifest.yaml` and offer to reuse
   it for the next import with the same signature.

### 2.3 What import does

```
$ strata import ~/Downloads/medline-2026-03-04.nbib --search S-01-medline
```

1. Copy the file **unmodified** to `imports/<import-id>/raw/`. This file is the
   ground truth and is never edited. Record its sha256.
2. Parse into records; apply normalisation ([01 §3.2](01-domain-model.md)).
3. Compute record ids; emit `record-add` events.
4. For an id already present, append to `strata.sources` rather than creating a
   duplicate row — an exact-id match is a same-record re-import, not a dedup
   candidate.
5. Write `imports/<id>/manifest.yaml`: source file, digest, parser, encoding
   detected, rows read, records created, rows rejected, column mapping, search id.
6. Emit an `import` event; regenerate derived views; commit.

Import MUST be **idempotent**: importing the same file twice creates no new
records and no second `import` event (detected by file digest), and MUST say so
rather than appearing to succeed silently.

### 2.4 Other sources

PRISMA 2020 tracks records found outside database searching separately, and the
flow diagram has a whole second column for it. `strata import --via
citation-searching | website | organisation | registry | contact` tags records
accordingly, and those tags flow through to the correct column of the diagram.

Backward and forward citation chasing is a common and valuable method; `strata`
v1 supports importing its results (as a normal export file with `--via
citation-searching`) but does not perform the chasing.

## 3. Deduplication

The same paper appears in MEDLINE, Embase, PsycINFO, and Scopus, in four
slightly different forms. Deduplication is unglamorous and is where reviews
silently break: a missed duplicate double-counts a study in the meta-analysis; an
over-eager merge deletes a real study. Both are publishable errors.

### 3.1 Design requirements

- **Sticky.** Every merge and every non-merge is recorded as an event. Re-running
  `strata dedup` after a new import never re-asks about a pair a human already
  judged.
- **Reversible.** `strata dedup --undo <canonical> <absorbed>` restores a record
  and records why.
- **Conservative.** When uncertain, ask. The cost of a review question is
  seconds; the cost of a wrong merge is a retraction.
- **Explainable.** Every automatic merge stores the features that drove it, so
  `strata why` can show them.

### 3.2 Blocking *(normative)*

All-pairs comparison is O(n^2) and infeasible at 50,000 records. Candidate pairs
are generated by blocking; two records are compared if they share **any** block
key:

| Key | Definition |
|---|---|
| `doi` | Normalised DOI |
| `pmid` | PubMed id |
| `title-prefix` | First 12 characters of the normalised title, plus year |
| `author-year-vol` | Normalised first-author family name + year + volume |
| `title-lsh` | MinHash/LSH band over character 3-grams of the normalised title, 128 permutations, 32 bands of 4 rows (tuned for ~0.8 Jaccard sensitivity) |
| `first-page` | Normalised journal + volume + first page |

The LSH band is what catches titles differing by an OCR error, a subtitle, or a
truncation, which prefix blocking misses. Implementations MUST cap any single
block at 2,000 members and, on exceeding it, split by year and warn — a runaway
block is almost always a parse failure that put a constant string in the title
field.

### 3.3 Scoring *(normative)*

For each candidate pair, compute a similarity in `[0, 1]`:

```
if both have a DOI:
    score = 1.00 if DOIs equal
    score = 0.00 if DOIs differ          # a hard veto: different DOI, different paper
else:
    score = 0.50 * title_sim
          + 0.20 * author_sim
          + 0.15 * year_sim
          + 0.10 * journal_sim
          + 0.05 * locator_sim
```

- `title_sim`: token-set ratio over normalised title tokens (Jaccard on the
  token sets, combined with a normalised Levenshtein ratio on the sorted token
  string; take the maximum). Robust to reordering and to appended subtitles.
- `author_sim`: Jaccard over normalised family-name sets; 0.5 weight if only the
  first author is available on either side.
- `year_sim`: 1.0 if equal, 0.7 if differing by 1 (online-first vs issue year is
  a routine discrepancy), 0.0 otherwise.
- `journal_sim`: normalised container title ratio after abbreviation expansion.
- `locator_sim`: 1.0 if volume and first page both match, 0.5 if one matches.

**The DOI veto is deliberate and is the highest-risk rule in this specification.**
Different DOIs usually mean different papers (an erratum, a reprint, a
preprint/version-of-record pair are genuinely distinct records). But publishers do
occasionally issue two DOIs for one article. Implementations MUST therefore:
route DOI-mismatched pairs scoring above `review_threshold` on the non-DOI
features into the review queue rather than discarding them, and label them
`doi-conflict` so a human sees them.

### 3.4 Thresholds and actions

| Score | Action |
|---|---|
| `>= auto_merge_threshold` (default 0.95) | Auto-merge; emit `dedup-merge` |
| `>= review_threshold` (default 0.80) | Queue for human review |
| `< review_threshold` | Distinct; no event recorded (absence is the default) |

`strata dedup --strict` sets both thresholds to 1.0, so every non-exact pair is
reviewed. Recommended for reviews small enough to afford it.

### 3.5 Merge semantics

The surviving canonical record is chosen by: most complete record (count of
populated high-value fields: DOI, abstract, authors, pages), then highest
`source_trust`, then lowest id (deterministic tie-break).

Field-wise merge into the canonical record:

- A field empty on the canonical and present on the absorbed is copied.
- A field present on both is kept from the higher-`source_trust` source.
- `abstract`: the longest non-empty value wins (truncated abstracts are the
  common case).
- `keyword`: set union.
- `strata.sources`: append.
- Every field's origin is recorded in `strata.field_provenance`.

The absorbed record is retained in `records.ndjson` with `strata.canonical: false`
and an entry in `aliases.ndjson`. Nothing is deleted, ever.

### 3.6 The review queue

```
$ strata dedup --review

  Pair 3 of 47                                       score 0.88   doi-conflict

  A  rec_3kq8v1r0zx2m4a7b     [scopus]   10.1111/j.1467-9280.2008.02209.x
     Cepeda, Vul, Rohrer, Wixted & Pashler (2008)
     Spacing effects in learning: A temporal ridgeline of optimal retention
     Psychological Science, 19(11), 1095-1102

  B  rec_7p1m4k8v2x6z0a3c     [embase]   10.1111/j.1467-9280.2008.02209.x-2
     Cepeda N.J., Vul E., Rohrer D., et al. (2009)
     Spacing effects in learning. A temporal ridgeline of optimal retention
     Psychol Sci, 19, 1095

     title 0.97 | authors 1.00 | year 0.70 | journal 1.00 | pages 0.50
     DOIs differ (suffix "-2" on B) -- flagged for human judgement

  [m] merge   [k] keep both   [s] skip   [o] open both   [?] help
```

Keyboard-driven, one pair per screen, with the evidence visible. `[k]` records a
`dedup-distinct` event so the pair is never raised again.

### 3.7 Performance *(normative)*

Deduplicating 50,000 records MUST complete in under 120 seconds on a 2020-era
laptop, single-threaded, and MUST NOT exceed 2 GB of resident memory.
Implementations SHOULD parallelise scoring across blocks.

### 3.8 Validation

The dedup engine MUST be evaluated against a labelled benchmark and the results
published in the repository. Suitable public benchmarks exist from the ASySD and
`revtools` projects. Required metrics: precision, recall, F1, and — reported
separately and weighted most heavily — the **false-merge rate**, since a false
merge destroys data while a missed duplicate merely wastes screening time.

Target for v1: recall >= 0.95, false-merge rate <= 0.001 at default thresholds.
