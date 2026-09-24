# Fixture provenance

Per `docs/spec/14-testing.md` §3, every fixture under `tests/fixtures/` must be
redistributable: either synthesised to mimic a real export format, or drawn
from records whose metadata is not copyrightable (bibliographic facts --
titles, author names, journal names, volumes, pages, DOIs, years -- are not
copyrightable subject matter; the prose of an abstract can be, so fixture
abstracts here are always invented text, never copied from a real one).

## `tests/fixtures/exports/`

All files in this directory are hand-written by the `strata` project
specifically as test fixtures. None are copied from an actual database
export. Where a record's bibliographic metadata (title/authors/journal/
year/DOI) matches a real, published paper, that is deliberate -- it makes the
fixture realistic and lets a reader cross-check it against a public source --
but the file's *bytes* (its RIS tags, its BibTeX field layout, its specific
malformations) are synthesised, not extracted from any platform's actual
export.

- `csl-json/clean.json`, `csl-json/malformed.json`,
  `csl-json/broken-document.json` -- CSL-JSON, hand-written. One record's
  metadata (Cepeda, Vul & Rohrer, 2008, *Psychological Science*) matches the
  paper used as a running example throughout `docs/spec/`.
- `ris/clean.ris`, `ris/malformed.ris`, `ris/malformed-bom.ris`,
  `ris/malformed-cp1252.ris` -- RIS, hand-written tag-per-line text.
  `malformed-bom.ris` and `malformed-cp1252.ris` are generated with a small
  script (not checked in) that prepends a literal UTF-8 BOM byte sequence and
  encodes a title containing U+201C/U+201D "smart quotes" as CP1252 bytes,
  respectively, to produce byte-for-byte realistic encoding malformations
  rather than approximations of them.
- `bibtex/clean.bib`, `bibtex/malformed.bib` -- BibTeX, hand-written.
- `medline/clean.nbib`, `medline/malformed.nbib` -- PubMed/MEDLINE, hand-written
  tag-per-line text (see `docs/spec/05-workflow-import.md` §2.1's `PMID- `/
  `TI  - ` convention). `malformed.nbib`'s line endings were converted to CRLF
  with a small script (not checked in) after being written, for the same
  reason as the RIS encoding fixtures above.

Each `clean.*` fixture has a committed `*.expected.json`: the exact list of
CSL-JSON-shaped records the corresponding parser must produce. Each
`malformed.*` fixture (and the two RIS encoding fixtures) has a committed
`*.expected.json` of shape `{"encoding": ..., "records": [...], "rejected":
[...]}`, pinning both the records that survive and the `RejectedRow`s for the
ones that don't -- see `tests/golden/test_golden_parsers.py`.

## Malformation coverage

Tracking against the list in `docs/spec/14-testing.md` §3:

| Malformation | Covered by |
|---|---|
| BOM at start of file | `ris/malformed-bom.ris` |
| CRLF line endings | `ris/malformed.ris`, `medline/malformed.nbib` |
| Missing `ER  -` | `ris/malformed.ris` |
| `TY - ` (single-space) tag spacing | `ris/malformed.ris` |
| CP1252 smart quotes | `ris/malformed-cp1252.ris` |
| HTML entities in titles | `ris/malformed.ris`, `medline/malformed.nbib` (`&amp;`) |
| Multi-line abstract, inconsistent indentation | `ris/malformed.ris`, `medline/malformed.nbib` |
| Diacritics in author names | `ris/clean.ris`, `bibtex/clean.bib`, `medline/malformed.nbib` (Müller) |
| Corporate authors | `ris/clean.ris`, `bibtex/clean.bib`, `medline/clean.nbib` (World Health Organization) |
| Missing years | `ris/malformed.ris` |
| DOIs with trailing punctuation | `ris/malformed.ris` |
| Empty title | one record in each of `ris/malformed.ris`,
  `bibtex/malformed.bib`, `csl-json/malformed.json`, `medline/malformed.nbib` |
| Brace-unbalanced / syntactically broken entry | `bibtex/malformed.bib` |
| Non-UTF-8 whole-document / non-array JSON | `csl-json/broken-document.json` |

Not yet covered (carried forward -- see `docs/m1-plan.md` sub-objective 3):
CR-only (old Mac) line endings; a lone-CR variant; LaTeX-escaped diacritics
(`\"u`) rather than literal UTF-8 in BibTeX author names, since this
implementation does not run `bibtexparser`'s LaTeX-decoding middleware; and
the remaining platform-specific fixtures the table in §3 asks for by name
(Ovid, EBSCOhost, Scopus, Web of Science, ProQuest, Cochrane CENTRAL,
ClinicalTrials.gov, EndNote, Google Scholar), which belong to the EndNote XML
and CSV/TSV/Excel parsers of sub-objective 3, not yet implemented.
