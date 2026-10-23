# M5 ("Reporting") — implementation notes

A working note for whoever picks up the work after M5, modelled on [`m4-plan.md`](m4-plan.md). The
normative text is the OpenSpec change `add-prisma-reporting` (and, once archived, the specs it merges
into: `prisma-reporting`, `manuscript-generation`, plus additions to `cli` and `web-ui`). This file
records what was built, the conventions that emerged, and what is deliberately partial.

## Status

| Group | What | Status |
|---|---|---|
| 1 | `report/counts.py`: every PRISMA count derived from the import manifests, records, screening, adjudication and retrieval events and the study grouping; per-origin funnels; the reconciliation identities; `derived/counts.json`; `E_COUNT_RECONCILE` in `strata verify` | done |
| 2 | `report/flow.py`, `strata prisma`: the flow diagram in SVG, PDF, PNG and JSON (with the `PRISMA2020` R package input), one or two columns, collapse beyond six reasons, DRAFT watermark, `--allow-stale`; byte-for-byte check in `strata verify`; `/prisma` web screen | done, wording caveat below |
| 3 | `report/checklist.py`, `strata report checklist [--status]`: 27 items and sub-items, auto-filled / auto-located / author, item 24c from the history, items 25 and 26 from `strata.toml` | done, wording not verified |
| 4 | `report/sections.py`, `strata report methods\|results\|characteristics\|amendments\|rob\|manuscript`: generated prose under the rules, the characteristics table, the risk-of-bias table and traffic-light plot, pandoc export | done |
| 5 | `report/bibliography.py`, `report/package.py`: `strata export bibliography` (BibTeX, CSL-JSON, RIS; four sets) and `strata export package` | done |
| 6 | P11, E2E-03 to publication, E2E-01's amendment and flow assertions, golden diagrams, a package with no full text | done |

### Partial or deliberately left for later

- **Official wording.** The flow-diagram labels were compared with the template in the `PRISMA2020` R
  package. The 27-item checklist wording could not be compared with the official template from the
  build environment; the generated checklist says so in its header and `WORDING_VERIFIED` in
  `report/checklist.py` is `False`. Compare it with prisma-statement.org, correct any difference
  (the official wording governs) and flip the flag. The item wording was written from the published
  statement, not copied from a machine-readable source.
- **Methodologist review.** A person who has written methods sections should read the generated Methods
  before release (task 6.4). It has not happened.
- **`registry` and `contact` imports.** The PRISMA 2020 template names websites, organisations and
  citation searching for other methods. Records imported with `--via registry` or `--via contact` are
  drawn as "Registries" and "Contact with experts" lines and counted like the others, but have no key
  in the `PRISMA2020` R input (they appear in strata's own counts).
- **Other methods and title/abstract screening.** In strata every imported record is screened at
  title/abstract, including those found by other methods, so the other-methods column draws a
  "records screened" box the official template does not have for that column. The arithmetic closes
  (every box is a count of the same funnel); the shape differs from the template.
- **`total_studies_ma` and `total_reports_ma`** (studies in the meta-analysis) are written as 0 in the R
  input; the analyses carry the real numbers.
- **Registers versus databases** are told apart by a built-in list of well-known trial registers
  (`counts.REGISTERS`); a search of anything else is a database. There is no per-search setting yet.
- **Not generated, by design:** a Discussion or Conclusion, certainty of evidence (GRADE), the
  title, abstract, rationale and objectives.
- **pandoc** is optional: `--format md` needs nothing, and a missing pandoc is a specific error that
  says so. The docx, html and LaTeX outputs are not byte-reproducible (pandoc's own metadata).
- **Cross-platform byte identity** of the flow diagrams is asserted by golden files on every platform
  in the CI matrix; it has been run on Linux only.

## Conventions established

Everything in [`m1-plan.md`](m1-plan.md) to [`m4-plan.md`](m4-plan.md) still applies. Additions:

- **Counts are derived, never typed.** Identified rows come from the import manifests (parsed rows,
  that is rows read less rows rejected); duplicates removed from an origin are its identified rows less
  its canonical records, and the total is also derived a second, independent way (rows imported onto an
  existing id plus records merged away), so a records file that no import accounts for fails
  `E_COUNT_RECONCILE` and names the identity.
- **Origins.** A canonical record's origin is `searches` if any of its sources is a search, otherwise
  the `via` of its first source. A via-found row that duplicates a database record is therefore a
  duplicate removed from the other-methods column.
- **A review in progress still closes.** Records not yet resolved at a stage are `awaiting_*` terms in
  the identities (zero for a finished review); `complete` is true only when nothing is awaiting and no
  decision is stale, and the diagram is a DRAFT until then. A stale decision also makes `strata prisma`
  refuse (exit code 8) without `--allow-stale`.
- **`derived/counts.json` follows every command that can move a count** (`import`, `dedup`, screening,
  retrieval, grouping, criteria changes) and is rewritten by `strata prisma` and `strata report`; it
  records the assertions whether or not they hold.
- **One reason per excluded report.** The adjudicator's first cited criterion, else the first criterion
  cited by an excluding reviewer (in handle order). More than six reasons collapse the smallest into
  "Other reasons" (the five largest are kept) and the full table is written beside the diagram.
- **Amendments are measured by replaying history.** A change to the criteria after screening began is an
  amendment (setting criteria up before anyone screens is writing the protocol). Its impact is the set of
  decisions stale just after it that were not stale just before it, with decisions ordered by
  `(timestamp, id)` as the fold orders them; how many were screened again and how many of those ended
  excluded is read from the current state. The commit that carried the change (found with `git log -S`)
  is cited.
- **Generated prose is a draft with a provenance line.** Every section opens with the strata version
  and the commit it came from (and says when the tree has uncommitted changes), so regenerating after
  committing changes the line. Numbers come from `estimates.json` and the counts; the wording check
  (`sections.violations`) bans causal and significance language outside quoted material and is run over
  generated output by the tests.
- **Reports are committed, deterministically.** Output goes to `reports/` (plain Markdown, SVG, TSV) and
  is committed as one `report` or `prisma` operation; nothing is written outside `reports/` unless
  `--out` says so. The reproducibility package has sorted entries and fixed timestamps.
- **The package carries no full text.** Nothing under `fulltext/` but the manifest, no `.pdf` anywhere,
  no raw exports, no `.git` or `.strata`; a declared `project.license` is required.
