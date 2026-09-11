# 07 — Full text, study grouping, and data extraction *(normative)*

## 1. Retrieval

Records promoted out of title/abstract screening become **reports** to be
obtained. PRISMA distinguishes "reports sought for retrieval" from "reports
assessed for eligibility"; the gap between them is reports you could not get, and
it must be reported.

```
$ strata retrieve

  204 reports sought. 8 outstanding.

  rpt_3kq8v1r0zx2m4a7b  Cepeda et al. (2008)  Psychological Science
    doi:10.1111/j.1467-9280.2008.02209.x

    [f] I have the file      [u] open DOI in browser      [i] interlibrary loan requested
    [n] not retrievable      [s] skip
```

`[f]` records that the document was obtained and appends to
`fulltext/manifest.ndjson`:

```json
{"report":"rpt_3kq8v1r0zx2m4a7b","locator":{"doi":"10.1111/j.1467-9280.2008.02209.x","pmid":"19076480"},"version":"version-of-record","path":"cepeda-2008.pdf","retrieved":"2026-03-28","source":"institutional-access","actor":"ethan"}
```

The manifest is committed; the PDF is not ([13 §6](13-nonfunctional.md)).

### 1.1 Identify documents by identifier, not by bytes *(normative)*

The manifest's authoritative field is `locator` — the DOI, or PMID/PMCID/arXiv id
/ ISBN / URL where no DOI exists. That is what makes the document findable again
by anyone, on any machine, years later. `path` is a local convenience and carries
no guarantee; a collaborator's copy will live somewhere else and may well be
named something else.

`strata` MUST NOT require, and MUST NOT depend on, a content hash of the retrieved
file. A reviewer who highlights a passage, adds a sticky note, or opens the PDF
in a reader that rewrites metadata changes the bytes without changing the
document — and annotating while reading is exactly what full-text screening
involves. A hash-based equivalence check would therefore report disagreement on
two copies of the same paper in the ordinary case, which makes it worse than no
check at all.

Where two reviewers genuinely might assess *different documents* — a preprint
versus the version of record, or a paper with an erratum — the distinction is
recorded explicitly and by identifier:

| Field | Values |
|---|---|
| `version` | `preprint`, `accepted-manuscript`, `version-of-record`, `corrected`, `retracted`, `unknown` |
| `locator` | The identifier **of that version**; preprints carry their own DOI, which is precisely the identifier that distinguishes them |
| `related` | Optional: identifiers of other versions (`{"preprint": "10.1101/..."}`) |

This is both more robust and more informative than a hash: `version:
"preprint"` tells a reader something, whereas `sha256: 1a2b...` tells them only
that two files differ, without saying how or whether it matters.

A `sha256` field MAY be recorded and is OPTIONAL. If present it is advisory
metadata only; `strata` MUST NOT treat a mismatch as an error, MUST NOT warn on
one, and MUST NOT use it to decide whether two reviewers saw the same document.

`[n]` requires a reason from a fixed vocabulary (`no-access`, `not-found`,
`retracted`, `language`, `no-response-from-author`, `other` + free text). These
reasons populate the "Reports not retrieved" box of the flow diagram.

Optional, opt-in: with `enrichment.enabled`, `strata` MAY query Unpaywall for a
legal open-access copy and offer the link. It MUST NOT download anything
automatically, and MUST NOT touch Sci-Hub or comparable sources.

## 2. Study grouping

After full-text inclusion, reports are grouped into studies
([01 §2.3](01-domain-model.md)).

```
$ strata studies

  41 included reports -> 38 studies

  Suggested groupings (shared trial registration, sample, or authors):
    std_?  Larsen 2009 (Med Educ) + Larsen 2013 (Med Educ)
           same NCT id: NCT00713310; overlapping sample description
           [g] group   [k] keep separate   [?] show both

  Suggested splits:
    rpt_8k2m...  Kornell 2009 reports 3 independent experiments
           [s] split   [k] keep as one
```

Detection heuristics (suggestions only, never automatic): shared trial
registration number, shared author set plus overlapping sample size and
population description, explicit "follow-up of" or "secondary analysis of"
language in the abstract, and reports citing each other.

Grouping and splitting both require a rationale. Double-counting a study reported
twice is one of the most common serious errors in published meta-analyses, and
the grouping decisions should be visible to a reader.

## 3. Data extraction

### 3.1 The coding form

`extraction/schema.yaml` ([03 §6](03-schemas.md)) defines the form. `strata` MUST
support generating a draft schema from the protocol's declared moderators and
outcomes (`strata extract init`), so the user does not start from a blank file.

The form is versioned. Adding a field to the schema mid-extraction marks existing
extractions **incomplete** for that field, not invalid — `strata status` lists
studies with missing values and `strata extract --missing` queues exactly those.

### 3.2 Dual extraction

`extraction.mode = "dual"` (RECOMMENDED, and the Cochrane standard) has two
people extract independently into `extraction/by-reviewer/<handle>/`, then
reconcile into `extraction/consensus/`.

```
$ strata extract --reconcile std_7x2k9m1p3v5r8t0w

  Cepeda et al. (2008)                       11 fields, 2 disagreements

  n_total            ethan 148     sam 148       agree
  design             ethan rct     sam rct       agree
  retention_interval ethan 168 h   sam 24 h      DISAGREE
      ethan: "p. 1097 -- 1 week retention interval"
      sam:   "Table 2 -- the 1-day condition"
      [1] ethan   [2] sam   [o] other value   [?] open the PDF

  effects[0].sd2     ethan 0.21    sam 0.12      DISAGREE
      ...
```

Every reconciliation writes a `reconcile` event with the chosen value, its
source, and a rationale. `strata report` MUST be able to state the extraction
agreement rate, which reviewers ask for.

### 3.3 Units

A `quantity` field stores the entered value and unit **and** the normalised
value. Recording "1 week" as 168 hours without keeping "1 week" makes the
extraction unverifiable against the paper; recording only "1 week" makes it
unanalysable. Both are kept.

Unit conversion tables ship with `strata` for time, mass, length, and dose, and are
extensible per project. An unconvertible unit is `E_UNIT` and blocks analysis.

### 3.4 Effect data entry

The form adapts to the declared effect design ([03 §6](03-schemas.md)). `strata`
MUST support entering an effect in whatever form the paper reports, and
converting:

| Reported as | Accepted inputs |
|---|---|
| Group means | `n1, m1, sd1, n2, m2, sd2` |
| Group means with SE | `n1, m1, se1, n2, m2, se2` |
| Group means with CI | `n1, m1, ci1_lo, ci1_hi, ...` |
| 2x2 table | `events1, n1, events2, n2` |
| Correlation | `r, n` |
| Test statistic | `t, df` or `F, df1, df2` or `chi2, n` |
| p-value only | `p, n1, n2, direction` (with a loud caveat, §3.5) |
| Pre-computed | `yi, vi, measure` |
| Pre-post | `n, m_pre, sd_pre, m_post, sd_post, r` |

Conversions are specified in [08 §3](08-analysis.md). `strata` MUST show the
computed effect size immediately as the user types, so a data-entry error
(transposed digits, SD entered as SE) is visible at the moment it is made rather
than in the forest plot three weeks later.

### 3.5 Data quality guards *(normative)*

`strata` MUST warn — not block — on:

- An SD that is more than 3x or less than 1/3 of the median SD for that outcome
  across studies (commonly an SE entered as an SD, or a unit mismatch).
- A computed standardised effect size with `|g| > 3`.
- A 2x2 table with a zero cell (explain the continuity correction that will be
  applied).
- `n` inconsistent between the study-level `n_total` and the sum of arm `n`s.
- A p-value-derived effect size (lowest-quality conversion; flag for the
  sensitivity analysis).
- A reported statistic internally inconsistent with its p-value (a GRIM/statcheck
  style consistency check). This is cheap to implement for t and F tests and
  catches real reporting errors in source papers.

Every warning MUST be recordable as acknowledged, with a note, so it does not
nag on every subsequent run and so the acknowledgement is itself auditable.

## 4. Risk of bias

RoB assessment is structurally identical to extraction: an instrument definition
([03 §8](03-schemas.md)), per-reviewer assessments, reconciliation, and a
consensus record. It is specified separately only because the instruments are
standardised and `strata` ships them.

```
$ strata rob std_7x2k9m1p3v5r8t0w

  RoB 2 -- Domain 1: Randomisation process

  1.1  Was the allocation sequence random?                   [Y] [PY] [PN] [N] [NI]
  1.2  Was the allocation sequence concealed?                [Y] [PY] [PN] [N] [NI]
  1.3  Did baseline differences suggest a problem?           [Y] [PY] [PN] [N] [NI]

  Algorithmic suggestion: LOW
  Your judgement: [l] low  [s] some concerns  [h] high      Support: ______
```

`strata` MUST compute the instrument's algorithmic suggestion where the instrument
defines one (RoB 2 does) and MUST allow the reviewer to override it with a
recorded justification. `strata report rob` emits a robvis-compatible traffic-light
plot and a summary bar plot.

RoB judgements are available as moderators in analysis, which is how a
"restricted to low risk of bias" sensitivity analysis is expressed.

## 5. Exporting for outside analysis

`strata export effects --format csv|tsv|xlsx|rds|json` emits one row per effect
with all study-level and effect-level moderators joined, ready for `metafor`,
`R`, or anything else. This is a first-class, supported path, not an escape
hatch: the review's value is the curated dataset, and `strata` must never hold it
hostage. The export MUST include the `study_id` and `effect_id` so results can be
traced back.
