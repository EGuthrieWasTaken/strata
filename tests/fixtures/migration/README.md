# Migration fixtures

Exports from Rayyan, Covidence and EPPI-Reviewer for `strata import --format rayyan|covidence|eppi-json`
and `strata screen --from` (openspec:literature-import#migration-imports-from-incumbent-tools).

**Hand-written, not exported from the tools.** Each follows the export format as the tool documents
it (summarised in `src/strata/ingest/parsers/migration.py`), with the project's usual running
example (Cepeda et al. 2008, Roediger & Karpicke 2006) and invented records. They pin the shape
`strata` reads; they cannot show that the tools export that shape. A real export from each tool, with
its identifying details removed, should replace or be checked against these before tasks 2.1-2.3 of
`add-distribution-and-adoption` are ticked.

| File | Tool | What it holds |
|---|---|---|
| `rayyan-articles.csv` | Rayyan CSV export | Three articles; two reviewers' decisions and an exclusion reason in `notes`; one row with no title |
| `covidence-excluded.csv` | Covidence CSV export of the Excluded list | Two references with exclusion reasons |
| `eppi-reviewer.json` | EPPI-Reviewer JSON export | Code sets with Include and Exclude codes, and three references coded with them |
