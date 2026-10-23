# M6 ("Hardening and adoption") — implementation notes

Modelled on [`m5-plan.md`](m5-plan.md). M6 is ongoing; this file records what has been built so far and
what is deliberately partial.

## Status

| Change | What | Status |
|---|---|---|
| `add-review-repository-ci` | `strata init --ci`, the reusable workflow `.github/workflows/review-ci.yml`, the `actions/verify` composite action, `strata ci amendment` and `strata ci comment` | written and tested locally; 5 of 8 tasks open until it runs on GitHub (see below) |
| `add-zotero-integration` | | not started |
| `add-distribution-and-adoption` | task 2.4: EndNote XML, Excel and plain-text citation-list import | done; the rest (PyPI/binaries/Homebrew, Covidence/Rayyan/EPPI imports, worked example, translations) not started |

## add-review-repository-ci

- **What a review team gets.** `strata init my-review --ci [--ci-ref REF] [--methodologist LOGIN]` writes
  `.github/workflows/strata.yml` into the first commit. On every pull request that workflow runs
  `strata verify` (the check fails on any violation), comments what the change does to the review
  (records entering and leaving the pool, decisions invalidated, screening conflicts opened, analyses made
  stale) and, when `protocol/criteria.yaml` changed as data, labels the pull request `protocol-amendment`
  and asks the methodologist to review it.
- **`status --json` grew two fields per stage** (`included`, `stale_included`), additive, so the comment can
  say how many *included* papers sit behind invalidated decisions. It says "could leave the pool": what
  re-screening decides is not known until it happens.
- **Fork pull requests** get the verify check but not the comment, label or review request, because the
  trigger is `pull_request` (a read-only token for forks), not `pull_request_target`.
- **How it was checked.** Unit tests render the comment from fixture status documents; integration tests
  run `strata init --ci`, `strata ci amendment` and `strata ci comment` on real repositories, check the
  generated workflow against the reusable workflow's inputs and permissions, require third-party actions to
  be pinned to commits, and execute the reusable workflow's `run:` steps with a fake `gh`. actionlint 1.7.12
  accepts both workflow files.

### Partial or deliberately left for later

- **Never run on GitHub.** Nothing here has run on an Actions runner: the real `gh` behaviour, the
  permissions the called workflow gets from the caller, `GITHUB_ACTION_PATH` in the composite action and the
  `uv tool install git+https://…@<ref>` line are as written, not as observed. Open a pull request against a
  scratch review repository with `--ci-ref <branch>` to try it.
- **Nothing is tagged.** The default ref in an installed workflow is `v<version>`, which exists only after a
  release is tagged (`release.yml`); until then pass `--ci-ref`.
- **Required check.** Making `strata verify` a required status check is a branch-protection setting in the
  review repository; `init --ci` does not (and cannot) set it.
- **GitHub only.** The helper commands are provider-neutral; only the workflow files are GitHub Actions.

## add-distribution-and-adoption, task 2.4: the three deferred parsers

- **EndNote XML** (`ingest/parsers/endnote_xml.py`): each `<record>` is parsed on its own (it runs to the
  next `<record>`, so one that never closes cannot swallow its neighbours); an `&` that starts no valid
  entity is escaped and HTML entities are unescaped afterwards; a record containing a DOCTYPE or entity
  declaration is rejected and declarations outside the records are never applied.
- **Excel** (`ingest/parsers/xlsx.py`): standard library only. Caps: 50 MB file, 200 MB unpacked, 250,000
  rows, 512 columns, 100,000 characters per cell. A formula's cached value is read, never evaluated; dates
  stored as numbers arrive as Excel's serial numbers. The sheet becomes TSV text and goes through the TSV
  column mapping, so `--map` and the platform profiles work unchanged. Encrypted workbooks and legacy
  `.xls` are refused with advice.
- **Plain-text citation list** (`ingest/parsers/citation_list.py`): numbered or paragraph-separated
  references in Vancouver (`Authors. Title. Journal. 2019;12(3):45-67.`) and APA (`Authors (2019). Title.
  Journal, 12(3), 45-67.`) layouts, plus DOI and PMID wherever they appear. Anything else is rejected with
  its entry. Records carry `strata.flags: ["best-effort-parse"]` and are never auto-merged.
- **Found by fuzzing**: a corrupt member header made `zipfile` raise `BadZipFile`/`ValueError`; a row
  number of a billion would have yielded a billion blank rows; both now end in a clean refusal.
- **Not done**: the Covidence, Rayyan and EPPI-Reviewer migration imports (2.1-2.3), which need real export
  samples this project does not have; the XLS (legacy) format; reading dates formatted as dates.
