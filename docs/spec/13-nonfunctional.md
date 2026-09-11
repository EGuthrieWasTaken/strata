# 13 — Non-functional requirements *(normative)*

## 1. Scale targets

Sized against a large but ordinary review: four databases, 50,000 raw records,
40,000 after deduplication, 400 full texts, 60 included studies, 120 effects.

| Operation | Target | Hard limit |
|---|---|---|
| `epic import` of a 20,000-record RIS file | < 30 s | 60 s |
| `epic dedup` over 50,000 records | < 120 s | 300 s |
| `epic status` | < 1 s | 3 s |
| Staleness computation over 50,000 decisions | < 2 s | 5 s |
| Fold from cold (no cache) | < 5 s | 15 s |
| Derived-view regeneration | < 10 s | 30 s |
| `epic verify --fast` (pre-commit) | < 2 s | 5 s |
| `epic verify` (full) | < 60 s | 180 s |
| Screening decision round trip | < 100 ms p95 | 250 ms |
| `epic analyze` (60 studies, RE + moderators + diagnostics) | < 5 s | 20 s |
| Peak RSS, any operation at 50k records | < 2 GB | 4 GB |
| Repository size at 50k records | < 200 MB | 500 MB |

Reference hardware: a 2020 laptop, 4 cores, 16 GB RAM, SSD. Benchmarks are part
of CI ([14 §7](14-testing.md)) and a regression above the hard limit fails the
build.

## 2. Reliability

- **No silent data loss, ever.** Every mutation is an append to a log that is
  fsynced before the user sees confirmation. A power failure mid-session loses at
  most the uncommitted tail, which `epic status` detects and offers to commit.
- **Crash safety.** Interrupting any command leaves the repository in a valid
  state. A partially written NDJSON line has no valid digest and is skipped by
  readers and truncated by `epic verify --fix`.
- **Recoverability.** `epic verify --fix` regenerates every derived artefact and
  re-links event chains after arbitrary manual git surgery.
- **No destructive defaults.** Nothing is deleted. Deduplication absorbs;
  retirement retains; exclusion records. The only command that removes data is
  `epic gc --imports`, which prunes raw import files, requires confirmation, and
  is documented as breaking reproducibility.

## 3. Portability

- Linux, macOS (Intel and Apple Silicon), Windows 10+. All three are tested in
  CI on every commit, not just at release.
- Windows specifics that MUST be handled: path length limits (use extended paths
  or keep generated paths short), `CRLF` in git's `core.autocrlf` (forced to LF
  via `.gitattributes`), case-insensitive filesystems (never rely on two paths
  differing only by case), and reserved filenames (`CON`, `PRN`, `NUL`, `AUX`) —
  which a record id or a study slug must never become.
- Unicode throughout: non-Latin author names, titles, and abstracts are ordinary
  input, not edge cases. Filenames derived from user data MUST be sanitised, and
  ids are already restricted to `[a-z0-9_]`.
- Git 2.23+ required (for `git switch` and modern merge-driver behaviour);
  checked by `epic doctor`.

## 4. Privacy and network use *(normative)*

- **No telemetry.** None. Not anonymous usage statistics, not crash reporting,
  not a version check. If the project later wants usage data, it asks users to
  send it deliberately.
- **Offline by default.** With `enrichment.enabled = false` (the default), `epic`
  makes no network request except those the user explicitly initiates
  (`epic sync`, which talks only to the configured git remote).
- **Enrichment is opt-in, per-provider, and logged.** When enabled, every
  outbound request MUST be recorded in `.epic/network.log` with timestamp,
  endpoint, and purpose, so a user can audit exactly what left the machine.
- **Polite API use.** Crossref, OpenAlex, and PubMed provide free APIs with
  published etiquette. `epic` MUST send a descriptive `User-Agent` including the
  configured `contact_email`, MUST respect `Retry-After` and rate limits, MUST
  back off exponentially on 429/503, and MUST cache responses locally keyed by
  DOI so a re-run does not re-query. Abusing a free scholarly API on behalf of
  thousands of users would be both wrong and self-defeating.
- **No credentials stored by `epic`.** Git remote authentication is delegated
  entirely to the user's git credential helper or SSH agent.

## 5. Security

The threat model is modest — a local, single-user tool — but not empty.

| Threat | Mitigation |
|---|---|
| Malicious import file | Parsers are memory-bounded, never `eval`, and are fuzzed ([14 §6](14-testing.md)). XML parsing MUST disable external entity resolution and DTD processing (defusedxml or equivalent) |
| Zip bomb / billion laughs in `.xlsx` or EndNote XML | Decompression ratio and absolute size caps, enforced before parsing |
| Path traversal via a record field used in a filename | Ids are `[a-z0-9_]` only; user strings are never used as paths without sanitisation |
| Localhost server reachable from a web page | Origin/Host validation, session token, CSRF tokens, `SameSite=Strict` ([11 §7](11-web-ui.md)) |
| XSS from an abstract containing HTML | Escape on output; never render raw HTML from record data |
| Regex denial of service in `--filter matches` | Linear-time engine or a hard timeout |
| Supply chain | Pinned, hash-locked dependencies; reproducible builds; signed release artefacts; a published SBOM |

Security issues are reported privately per `SECURITY.md` and fixed before
disclosure.

## 6. Copyright and legal posture *(normative)*

This matters more than is usual for a research tool, because the natural workflow
involves mass-downloading copyrighted articles.

- **Full-text PDFs MUST NOT be committed by default.** `.gitignore` excludes
  `fulltext/`, and `epic` MUST refuse to `git add` a PDF from that directory
  without an explicit override. Committing 400 publisher PDFs to a GitHub
  repository is copyright infringement at scale, and the tool must not lead
  users there casually.
- **Hashes, not files.** `fulltext/manifest.ndjson` preserves the provenance
  chain (which document was assessed) without redistributing the document.
- **`epic` MUST NOT retrieve articles from unauthorised sources.** No Sci-Hub, no
  LibGen, no institutional-proxy credential handling. Unpaywall integration is
  limited to surfacing links to legally open copies.
- **Database terms of service.** `epic` does not scrape or automate queries
  against subscription databases ([00 §4](00-overview.md), N1); it consumes the
  exports those platforms provide for exactly this purpose.
- **Third-party content in generated output.** PRISMA materials are CC BY 4.0;
  generated diagrams and checklists MUST carry the required attribution. RoB 2
  and ROBINS-I are used under their respective terms, which MUST be checked and
  documented before shipping those instrument definitions.
- **The review's own data.** `project.license` in `epic.toml` declares the licence
  for the review data, and `epic export package` includes it. Bibliographic
  metadata is generally not copyrightable; abstracts generally are, which is
  worth a note in the documentation for users planning to publish their
  screening dataset.

## 7. Internationalisation

- All user-facing strings externalised from v1, even though only English ships
  initially. Retrofitting i18n is far more expensive than designing for it.
- UTF-8 throughout; no assumption that text is Latin script or left-to-right.
- Dates in output are ISO 8601. Dates in prose follow the locale.
- Numbers in *generated files* use `.` as the decimal separator always; numbers
  in *displayed prose* follow the locale. Mixing these is a classic source of
  corrupted CSV exports in European locales, and import MUST detect and handle
  `,`-decimal CSVs.
- Screening reviewers working in non-English literature are a normal case;
  nothing in the UI may assume English text.

## 8. Documentation

Documentation is a release requirement, not an afterthought. A tool aimed at
people who are not developers fails without it.

| Document | Audience |
|---|---|
| Quickstart: first review in 30 minutes | Priya |
| "I have never used git" guide | Sam |
| Methods-text cookbook (what to write in the manuscript, with generated examples) | All |
| Statistical methods reference, with the formulae from [08](08-analysis.md) and their sources | Dr. Okafor |
| Repository format reference | Implementers, data archivists |
| Recovery guide: what to do when something goes wrong | All |
| Contributing guide, including how to add a parser | Contributors |

Every CLI command's `--help` MUST include at least one worked example.

## 9. Licensing

- `epic` itself: **GNU General Public License v3.0 or later**, as committed.
- The repository-format specification ([02](02-repository-format.md),
  [03](03-schemas.md)): licensed permissively (CC0 or Apache-2.0) at release, so
  that other tools can read and write `epic` repositories without licence
  friction. A format that only one implementation can legally use is not a
  format. **OPEN** — see [16](16-open-questions.md).
- Test fixtures derived from published datasets retain their original licences
  and MUST be attributed in `tests/fixtures/SOURCES.md`.
