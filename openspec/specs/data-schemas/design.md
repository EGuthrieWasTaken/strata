# Design: data-schemas

*Informative.* The requirements are in [spec.md](spec.md); the shipped JSON
Schemas under `src/strata/schemas/` are the machine-readable contract.

## Why CSL-JSON for records

CSL-JSON is the data model of Zotero, pandoc, and citeproc. Using it with a
single namespaced `strata` extension buys interoperability for free:
`strata export --format csl` feeds pandoc directly and Zotero libraries import
without a translation layer. Unknown CSL fields are preserved because a tool
that silently drops metadata cannot be trusted with a review.

## Why label and examples are excluded from criterion digests

Relabelling a criterion is presentationally significant but never semantically
significant, so it must not be able to make work stale. The per-criterion digest
covers exactly `{id, kind, definition, applies_at}`.

## Why post hoc moderators are labelled

PRISMA and every methodologist care whether a moderator was pre-specified. The
tool should make lying about it require deliberate effort, so `planned: false`
is carried into all generated output.

## Why a re-run search is a new file

PRISMA requires the full history of what was actually run. An update search is
a distinct methodological event, so it gets its own file with `supersedes`
rather than an edit that would erase what was run the first time.

## Why enrichment requires a contact address

The open scholarly APIs `strata` can use (Crossref, OpenAlex, PubMed, Unpaywall)
ask callers to identify themselves for their polite pools. Sending requests
without one is abuse of a free service, so it is a configuration error.

## Reference examples

`strata.toml`:

```toml
schema_version = 1
created_with   = "strata/0.4.1"

[project]
id       = "prj_01j9x7m2q4h8s0v3n5k1t6w2yb"
title    = "Effects of spaced retrieval practice on long-term retention"
slug     = "spaced-retrieval"
created  = "2026-02-11"
registry = { name = "PROSPERO", id = "CRD42026512345", url = "https://..." }
license  = "CC-BY-4.0"

[[actors]]
handle = "ethan"
name   = "Ethan Guthrie"
email  = "ethan@example.edu"
orcid  = "0000-0002-1825-0097"
role   = "lead"

[[actors]]
handle = "sam"
name   = "Sam Okonkwo"
email  = "sam@example.edu"
role   = "screener"

[screening]
stages        = ["title-abstract", "full-text"]
mode          = "dual"
adjudicators  = ["ethan"]
blind_reviewers = true
blind_metadata  = false
require_exclusion_reason = true

[screening.assignment]
"title-abstract" = ["ethan", "sam"]
"full-text"      = ["ethan", "sam"]

[dedup]
auto_merge_threshold   = 0.95
review_threshold       = 0.80
source_trust           = ["crossref", "pubmed", "scopus", "wos", "embase", "ebsco", "manual"]

[git]
commit_style   = "structured"
require_rationale = true
sync_strategy  = "merge"
remote         = "origin"

[enrichment]
enabled = false
providers = []
contact_email = ""

[analysis]
engine = "native"
```

A record line (pretty-printed here):

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
  "language": "en",
  "strata": {
    "canonical_key": "doi:10.1111/j.1467-9280.2008.02209.x",
    "canonical": true,
    "absorbed": ["rec_9m2p0000000000ab"],
    "sources": [
      {"import": "imp_01j9x", "search": "S-01-medline", "database": "medline",
       "platform": "ovid", "native_id": "19076480", "row": 412,
       "retrieved": "2026-03-04"}
    ],
    "field_provenance": {"abstract": "scopus", "DOI": "crossref"},
    "flags": ["no-abstract"]
  }
}
```

`protocol/criteria.yaml`:

```yaml
version: 4
digest: "sha256:9f1c..."
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
    status: active
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

`protocol/moderators.yaml`:

```yaml
moderators:
  - name: "mean_age"
    label: "Mean age of sample (years)"
    type: continuous
    unit: "years"
    range: [0, 120]
    planned: true
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

`protocol/searches/S-01-medline.yaml`:

```yaml
id: "S-01-medline"
database: "MEDLINE"
platform: "Ovid"
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
export_files: ["imports/imp_01j9x/raw/medline-2026-03-04.nbib"]
peer_reviewed_by: "librarian@example.edu"
notes: >
  Search strategy adapted from the protocol; the adj3 proximity operator
  replaced the planned NEAR/3 for Ovid syntax.
supersedes: null
```
