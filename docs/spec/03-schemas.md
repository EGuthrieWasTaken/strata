# 03 — Schemas *(normative)*

Every schema here MUST have a machine-readable JSON Schema (Draft 2020-12)
shipped in the `epic` source tree under `epic/schemas/`, and MUST be validated on
write and on load. The tables below are the human-readable contract; where they
disagree with the shipped schema, the shipped schema is a bug.

## 1. `epic.toml` — project manifest

```toml
schema_version = 1
created_with   = "epic/0.4.1"

[project]
id       = "prj_01j9x7m2q4h8s0v3n5k1t6w2yb"
title    = "Effects of spaced retrieval practice on long-term retention"
slug     = "spaced-retrieval"
created  = "2026-02-11"
registry = { name = "PROSPERO", id = "CRD42026512345", url = "https://..." }
license  = "CC-BY-4.0"          # licence for the review's *data*, not the tool

[[actors]]
handle = "ethan"
name   = "Ethan Guthrie"
email  = "ethan@example.edu"
orcid  = "0000-0002-1825-0097"
role   = "lead"                 # lead | screener | extractor | adjudicator | observer

[[actors]]
handle = "sam"
name   = "Sam Okonkwo"
email  = "sam@example.edu"
role   = "screener"

[screening]
stages        = ["title-abstract", "full-text"]
mode          = "dual"          # single | dual | dual-then-adjudicate
adjudicators  = ["ethan"]
blind_reviewers = true          # reviewers cannot see each other's decisions
blind_metadata  = false         # hide author/journal/year during screening
require_exclusion_reason = true

[screening.assignment]
"title-abstract" = ["ethan", "sam"]
"full-text"      = ["ethan", "sam"]

[dedup]
auto_merge_threshold   = 0.95
review_threshold       = 0.80
source_trust           = ["crossref", "pubmed", "scopus", "wos", "embase", "ebsco", "manual"]

[git]
commit_style   = "structured"   # structured | plain
require_rationale = true
sync_strategy  = "merge"        # merge | rebase
remote         = "origin"

[enrichment]
enabled = false                 # opt-in only; see 13 §4
providers = []                  # crossref | openalex | pubmed | unpaywall
contact_email = ""              # sent as mailto= in the polite-pool User-Agent

[analysis]
engine = "native"               # native | metafor
```

Rules:

- `actors[].handle` MUST match `^[a-z0-9][a-z0-9-]{0,31}$` and MUST be unique.
- An actor MUST NOT be removed once they have authored an event; set
  `role = "inactive"` instead. Removing them would orphan history.
- `screening.mode = "dual"` with an assignment list of length 1 is a
  configuration error (`E_CONFIG`).
- `enrichment.enabled = true` with an empty `contact_email` is a configuration
  error: the open APIs `epic` uses require a contact address for their polite
  pools, and sending requests without one is abuse of a free service.

## 2. Record — `records/records.ndjson`

The record schema is **CSL-JSON** (the Citation Style Language data model used by
Zotero, pandoc, and citeproc) with a single namespaced extension object. This
buys interoperability for free: `epic export --format csl` feeds pandoc directly,
and Zotero libraries import without a translation layer.

```json
{
  "id": "rec_3kq8v1r0zx2m4a7b",
  "type": "article-journal",
  "title": "Spacing effects in learning: a temporal ridgeline of optimal retention",
  "author": [{"family": "Cepeda", "given": "Nicholas J."}],
  "issued": {"date-parts": [[2008]]},
  "container-title": "Psychological Science",
  "volume": "19", "issue": "11", "page": "1095-1102",
  "DOI": "10.1111/j.1467-9280.2008.02209.x",
  "PMID": "19076480",
  "abstract": "...",
  "language": "en",
  "epic": {
    "canonical_key": "doi:10.1111/j.1467-9280.2008.02209.x",
    "canonical": true,
    "absorbed": ["rec_9m2p0000000000ab"],
    "sources": [
      {"import": "imp_01j9x...", "search": "S-01-medline", "database": "medline",
       "platform": "ovid", "native_id": "19076480", "row": 412,
       "retrieved": "2026-03-04"}
    ],
    "field_provenance": {"abstract": "scopus", "DOI": "crossref"},
    "flags": ["no-abstract"]
  }
}
```

| Field | Required | Notes |
|---|---|---|
| `id` | yes | Per [01 §3.1](01-domain-model.md) |
| `type` | yes | CSL type; default `article-journal` |
| `title` | yes | Empty title is a hard import error |
| `author` | no | CSL name objects; `literal` allowed for corporate authors |
| `issued` | no | CSL date; `date-parts` only, no raw strings |
| `DOI`, `PMID`, `PMCID`, `URL`, `ISBN` | no | Normalised per [01 §3.2](01-domain-model.md) |
| `abstract` | no | Verbatim from source; structured-abstract labels preserved |
| `keyword` | no | CSL is a single string; `epic` stores a `;`-joined list |
| `epic.canonical` | yes | `false` means this row is retained only for provenance |
| `epic.sources` | yes | Append-only; one entry per import that saw this record |
| `epic.field_provenance` | no | Which source each field's current value came from |
| `epic.flags` | no | `no-abstract`, `no-doi`, `retracted`, `preprint`, `non-english`, `id-unstable` |

Unknown CSL fields MUST be preserved on round-trip. `epic` is not permitted to
silently drop metadata.

**Retraction flag.** If enrichment is enabled, `epic` SHOULD check Crossref for
`update-to` relations and set the `retracted` flag. A retracted study in an
included pool is a publishable-error-level problem, and the check is nearly free.

## 3. Criteria — `protocol/criteria.yaml`

```yaml
version: 4
digest: "sha256:9f1c..."        # GENERATED: over the canonical form of `criteria`
criteria:
  - id: "INC-01"
    kind: inclusion
    label: "Empirical study with original data"
    definition: >
      Reports original empirical data collected by the authors. Excludes
      narrative and systematic reviews, editorials, commentaries, and
      conference abstracts for which no full paper is available.
    applies_at: ["title-abstract", "full-text"]
    since_version: 1
    status: active              # active | retired
    examples:
      include: ["A randomised trial of spacing in undergraduates"]
      exclude: ["A meta-analysis of spacing effects"]

  - id: "EXC-07"
    kind: exclusion
    label: "Mean sample age under 18"
    definition: >
      The reported mean age of the analysed sample is below 18 years, or the
      sample is described as children/adolescents without an age statistic.
    applies_at: ["full-text"]
    since_version: 4
    status: active
```

| Field | Required | Notes |
|---|---|---|
| `id` | yes | `INC-nn` or `EXC-nn`; never reused |
| `kind` | yes | `inclusion` or `exclusion` |
| `label` | yes | <= 80 chars; appears on screening hotkeys and in the flow diagram |
| `definition` | yes | The operational rule. This is what staleness hashes. |
| `applies_at` | yes | Non-empty subset of configured stages |
| `since_version` | yes | Criteria-set version at which introduced |
| `status` | yes | `retired` criteria stay in the file forever |
| `examples` | no | Strongly recommended; these are the calibration set |

**Per-criterion digest** = `sha256` over the canonical serialisation of
`{id, kind, definition, applies_at}`. Note that `label` and `examples` are
excluded: relabelling is presentationally significant but never semantically
significant, so it cannot make work stale.

**Set digest** = `sha256` over the concatenation of per-criterion digests of
active criteria, sorted by id.

## 4. Moderators — `protocol/moderators.yaml`

```yaml
moderators:
  - name: "mean_age"
    label: "Mean age of sample (years)"
    type: continuous            # continuous | categorical | ordinal | boolean | count
    unit: "years"
    range: [0, 120]
    planned: true               # was this pre-specified, or added post hoc?
    since_version: 1
    prisma_note: "Pre-specified in the registered protocol"

  - name: "design"
    label: "Study design"
    type: categorical
    levels: ["rct", "quasi-experimental", "within-subjects", "observational"]
    reference: "rct"
    planned: true
    since_version: 1
```

`planned: false` moderators MUST be reported as post hoc in generated output.
PRISMA and every methodologist care about this distinction; the tool should make
lying about it require deliberate effort.

## 5. Search — `protocol/searches/S-01-medline.yaml`

```yaml
id: "S-01-medline"
database: "MEDLINE"
platform: "Ovid"                # the interface actually used
executed: "2026-03-04"
executed_by: "ethan"
query: |
  1  exp Learning/
  2  (spac* adj3 (practice or repetition or retrieval)).ti,ab,kf.
  3  1 and 2
  4  limit 3 to (english language and yr="1990 -Current")
limits:
  language: ["English"]
  years: "1990-2026"
  publication_types_excluded: ["Comment", "Editorial"]
hits: 4182
export_files: ["imports/imp_01j9x.../raw/medline-2026-03-04.nbib"]
peer_reviewed_by: "librarian@example.edu"    # PRESS checklist, optional
notes: >
  Search strategy adapted from the protocol; the adj3 proximity operator
  replaced the planned NEAR/3 for Ovid syntax.
supersedes: null                # id of an earlier version of this search
```

`query` MUST be a literal block scalar and MUST round-trip byte-for-byte.
Re-running a search on a later date creates a **new** search file with
`supersedes` set, never an edit — PRISMA requires the full history of what was
actually run, and an update search is a distinct methodological event.

## 6. Extraction schema — `extraction/schema.yaml`

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

Field types: `integer`, `number`, `quantity` (number + unit, normalised),
`categorical`, `multi-categorical`, `boolean`, `text`, `date`, `citation`
(a page/table/figure pointer into the source report).

Every extracted value SHOULD carry a **source locator** (`p. 1098, Table 2`).
The UI MUST make entering one a single keystroke, and `epic report` MUST be able
to emit a per-value provenance table, because "where did this number come from"
is the question a reviewer asks about every number in the forest plot.

Schema changes bump `version`. Adding a required field makes every existing
extraction **incomplete**, not stale — `epic status` reports it as missing data
rather than invalidating prior work.

## 7. Extraction record — `extraction/consensus/std_7x2k....yaml`

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
  - id: "eff_7x2k9m1p3v5r8t0w_0002"
    outcome: "recognition"
    design: "two-group-means"
    timepoint: "1 week"
    n1: 74
    m1: 0.81
    sd1: 0.12
    n2: 74
    m2: 0.77
    sd2: 0.14
    source: "Table 2"
    moderators: {dose: 3, condition: "spaced"}
```

## 8. Risk of bias — `rob/instrument.yaml`

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
  algorithm: "worst-domain"     # worst-domain | custom
```

`epic` MUST ship RoB 2, ROBINS-I, and the Newcastle-Ottawa Scale as built-in
instrument definitions, and MUST allow a custom instrument in the same shape. A
per-study RoB file mirrors the extraction record's structure: judgement plus
free-text support plus a source locator per domain.

## 9. Analysis specification — `analysis/primary.yaml`

See [08 §2](08-analysis.md) for the full field reference and semantics.

## 10. Validation rules that cross schemas *(normative)*

`epic verify` MUST enforce all of the following and report every violation, not
just the first:

| Code | Rule |
|---|---|
| `E_SCHEMA` | Any file fails its JSON Schema |
| `E_DANGLING_REF` | An event names a record, criterion, actor, study, or stage that does not exist |
| `E_ALIAS_CYCLE` | Alias resolution cycles |
| `E_CHAIN` | An event file's hash chain is broken (§[02 §4.2](02-repository-format.md)) |
| `E_DERIVED_DRIFT` | A committed derived file differs from regeneration |
| `E_CRITERION_REUSE` | A criterion id is reused after retirement |
| `E_EXCLUSION_NO_CRITERION` | An `exclude` decision cites no criterion while `require_exclusion_reason` is set |
| `E_CRITERION_STAGE` | A decision cites a criterion that does not apply at that stage |
| `E_ORPHAN_EXTRACTION` | An extraction file exists for a study that is not included |
| `E_MISSING_EXTRACTION` | An included study has no consensus extraction (warning until analysis) |
| `E_COUNT_RECONCILE` | The PRISMA counts do not satisfy the identities in [09 §2](09-reporting.md) |
| `E_UNIT` | A `quantity` value has a unit outside `accepts_units` |
| `E_EFFECT_INPUTS` | An effect lacks the fields its declared design requires |
