# Design: Full text, study grouping, and data extraction

## Context

M0–M2 shipped the event log, identity, screening, and staleness. Reports,
studies, and effects exist in the domain model (`domain-model` spec) and their
event types are catalogued (`event-log` spec), but nothing yet produces them.

## Goals / Non-Goals

**Goals:**

- A complete review can be conducted through to an analysis-ready dataset.
- Every extracted value can answer "where did this number come from?".
- Dual extraction reconciliation records every decision.

**Non-Goals:**

- Storing or redistributing PDFs (see `copyright-and-licensing`).
- Automatic study grouping — heuristics only suggest.
- Pooling or effect-size inference beyond displaying the computed effect while
  typing (M4).

## Decisions

- **Identify documents by identifier and version, never by content hash.**
  Annotating a PDF changes its bytes without changing the document, so a hash
  check would report disagreement between two copies of the same paper in the
  ordinary case. `version` plus a per-version `locator` is both more robust and
  more informative. A `sha256` MAY be recorded as advisory metadata only.
- **Adding a required extraction field makes prior extractions incomplete, not
  stale.** Missing data is reported and queued (`strata extract --missing`)
  rather than invalidating completed work.
- **Store entered and normalised quantity values together.** "1 week" alone is
  unanalysable; 168 hours alone is unverifiable against the paper.
- **Data-quality guards warn, never block**, and acknowledgements are recorded
  so they are auditable and do not nag.
- **RoB is structurally identical to extraction** (instrument, per-reviewer
  assessment, reconciliation, consensus) and is specified separately only
  because the instruments are standardised and shipped.

## Risks / Trade-offs

- RoB 2 and ROBINS-I licence terms must be checked before shipping their
  definitions (`copyright-and-licensing`).
- The GRIM/statcheck-style consistency check can produce false alarms on
  rounded reporting; it is a warning with an acknowledgement path for this
  reason.

## Reference: interaction sketches

Retrieval queue:

```
$ strata retrieve

  204 reports sought. 8 outstanding.

  rpt_3kq8v1r0zx2m4a7b  Cepeda et al. (2008)  Psychological Science
    doi:10.1111/j.1467-9280.2008.02209.x

    [f] I have the file      [u] open DOI in browser      [i] interlibrary loan requested
    [n] not retrievable      [s] skip
```

A manifest entry written by `[f]`:

```json
{"report":"rpt_3kq8v1r0zx2m4a7b","locator":{"doi":"10.1111/j.1467-9280.2008.02209.x","pmid":"19076480"},"version":"version-of-record","path":"cepeda-2008.pdf","retrieved":"2026-03-28","source":"institutional-access","actor":"ethan"}
```

Study grouping:

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

Double-counting a study reported twice is one of the most common serious errors
in published meta-analyses, which is why grouping decisions need a rationale and
are visible to readers.

Reconciliation:

```
$ strata extract --reconcile std_7x2k9m1p3v5r8t0w

  Cepeda et al. (2008)                       11 fields, 2 disagreements

  n_total            ethan 148     sam 148       agree
  design             ethan rct     sam rct       agree
  retention_interval ethan 168 h   sam 24 h      DISAGREE
      ethan: "p. 1097 -- 1 week retention interval"
      sam:   "Table 2 -- the 1-day condition"
      [1] ethan   [2] sam   [o] other value   [?] open the PDF
```

Risk of bias:

```
$ strata rob std_7x2k9m1p3v5r8t0w

  RoB 2 -- Domain 1: Randomisation process

  1.1  Was the allocation sequence random?                   [Y] [PY] [PN] [N] [NI]
  1.2  Was the allocation sequence concealed?                [Y] [PY] [PN] [N] [NI]
  1.3  Did baseline differences suggest a problem?           [Y] [PY] [PN] [N] [NI]

  Algorithmic suggestion: LOW
  Your judgement: [l] low  [s] some concerns  [h] high      Support: ______
```

## Reference: file examples

`extraction/schema.yaml`:

```yaml
version: 2
fields:
  - name: "n_total"
    label: "Total analysed N"
    type: integer
    required: true
    min: 1
    help: "Number of participants in the analysed sample, not the enrolled sample."
  - name: "design"
    label: "Study design"
    type: categorical
    levels: ["rct", "quasi-experimental", "within-subjects", "observational"]
    required: true
  - name: "retention_interval"
    label: "Retention interval"
    type: quantity
    unit: "hours"
    accepts_units: ["minutes", "hours", "days", "weeks"]
    required: true
    help: "Converted to hours on entry; the entered value and unit are both stored."
  - name: "notes"
    type: text
    required: false
effects:
  outcome_field: "outcome"
  outcomes: ["recall", "recognition", "transfer"]
  designs:
    - id: "two-group-means"
      requires: ["n1", "m1", "sd1", "n2", "m2", "sd2"]
    - id: "two-group-binary"
      requires: ["events1", "n1", "events2", "n2"]
    - id: "correlation"
      requires: ["r", "n"]
    - id: "precomputed"
      requires: ["yi", "vi", "measure"]
```

`extraction/consensus/std_7x2k9m1p3v5r8t0w.yaml`:

```yaml
study: "std_7x2k9m1p3v5r8t0w"
reports: ["rpt_3kq8v1r0zx2m4a7b"]
schema_version: 2
extracted_by: ["ethan", "sam"]
reconciled_by: "ethan"
fields:
  n_total:   {value: 148, source: "p. 1097, para 2"}
  design:    {value: "rct", source: "p. 1096, Methods"}
  retention_interval: {value: 168, unit: "hours", entered: "1 week", source: "p. 1097"}
  mean_age:  {value: 20.4, source: "Table 1"}
effects:
  - id: "eff_7x2k9m1p3v5r8t0w_0001"
    outcome: "recall"
    design: "two-group-means"
    timepoint: "1 week"
    n1: 74
    m1: 0.62
    sd1: 0.18
    n2: 74
    m2: 0.48
    sd2: 0.21
    source: "Table 2"
    moderators: {dose: 3, condition: "spaced"}
```

`rob/instrument.yaml`:

```yaml
instrument: "RoB 2"
version: "2019-08-22"
applies_to: ["rct"]
domains:
  - id: "D1"
    label: "Randomisation process"
    judgements: ["low", "some-concerns", "high"]
    signalling_questions:
      - id: "1.1"
        text: "Was the allocation sequence random?"
        options: ["Y", "PY", "PN", "N", "NI"]
overall:
  algorithm: "worst-domain"
```
