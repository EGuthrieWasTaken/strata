# Known limitations

An honest list of what does not work yet, what has not been verified, and the workaround where there is one.
Nothing here is hidden elsewhere: the project's own plan documents say the same, and this page is updated as
items are fixed.

## Things that behave differently from what you might expect

| Limitation | What to do |
|---|---|
| **`strata config` does not commit.** It changes `strata.toml` and leaves the change uncommitted, so `strata sync` will refuse until you commit it | `git commit -am "settings: ..."` after `strata config` |
| **A command run without a reason, in a script, does its work and then fails.** In a non-interactive run without `--why`, some commands (`actor add`, `dedup`, `criteria add`, `extract init`, ...) change files and only then discover that no reason was given, leaving the tree uncommitted. (A fix is queued.) | Always pass `--why "..."` in scripts. If it happens, `git checkout . && git clean -fd` discards the uncommitted work, then run the command again with `--why` |
| **`strata verify --fast` (the pre-commit hook) does not check that derived files are up to date, and `strata verify --fix` repairs only those.** The full `strata verify` reports `E_DERIVED_DRIFT` for a file under `derived/` that regeneration would write differently, and `--fix` regenerates it. The fast check skips this (regenerating the views does not yet fit the two seconds it is allowed), and `--fix` does not yet re-link a broken hash chain or truncate a half-written line | Run the full `strata verify` before you share (`strata sync` and the review-repository CI do); repair a broken chain as in [Recovery](Recovery-and-Troubleshooting) |
| **The screening-state filter fields are not available.** `tiab`, `fulltext`, `stale`, `criteria` and `actor_decision.<handle>` are part of the [filter language](Filter-Language) but report "not available yet". As a result `strata assign --filter` and `strata screen --filter` cannot select by screening state, and **the full-text queue is not narrowed to records that passed title-abstract**: it lists every record, and `strata status` shows the never-assessed remainder as "unscreened" at full text | Select by `id in [...]` using the ids in `derived/pool.tsv` ([Screening](Screening#moving-to-full-text)) |
| **Hooks need `strata` on the PATH.** The git hooks call `strata` by name; run through an absolute path or a different environment, a commit can fail with `strata: not found` | Run `strata` from your normal terminal; `uv tool update-shell` if the command is not found ([Installation](Installation)) |
| **Imported screening is not told apart in agreement statistics.** `strata irr` uses everyone's first opinions, including decisions imported from another tool | Only report agreement for screening done independently in `strata` |
| **The write lock needs a local disk.** Commands that write take an operating-system lock on `.strata/lock` so a terminal and `strata serve` cannot write at the same moment. Some network file systems do not honour such locks (git itself warns about the same for a working copy) | Keep the review on a local disk, and share it with `strata sync` rather than a shared drive |
| **Uploads have a size limit and no progress bar.** The web interface refuses a file over 100 MB (`strata serve --max-upload-mb`), and a browser upload of a large export shows nothing until the whole file has been sent and read. Reviewing a large file takes about as long as importing it, because the review runs the real parser | For a very large export, import it from the terminal with `strata import`, or raise the limit |
| **Some record fields cannot be corrected with `strata fix`** (authors and dates are structured) | Correct the source export and re-import, or fix the plain-text fields |
| **Several stages are command-line only.** The web interface has no screens for `strata sync`, running analyses or writing reports, and cannot dismiss a study-grouping suggestion ("keep separate") | Use `strata sync`, `analyze` and `report`, and the interactive `strata studies --by <you>` to dismiss a suggestion. Searches and importing, correcting a record, adding a criterion, assigning reviewers, retrieval outcomes and study grouping are in the web interface |

## Not yet verified, or verified only partly

- **The generated Methods have not been read by a methodologist.** The checklist wording is PRISMA 2020's
  Table 1, word for word, and the numbers come from the log, but the prose should be read against the statement
  before you rely on it ([Reporting](Reporting)).
- **The RoB 2 algorithm** follows two independent open-source transcriptions of Cochrane's decision rules, which
  agree on every combination of answers; it has not been compared with Cochrane's own tables. The official
  question wording is not bundled, for licensing reasons ([Risk of bias](Risk-of-Bias)).
- **One published worked example is outstanding** for the effect-size code: the Hedges & Olkin and Cochrane
  Handbook values could not be reproduced because their tables were not available. Every estimator is checked
  against `metafor` to 1e-8; see [Statistical methods](Statistical-Methods).
- **The deduplication benchmark is synthesised.** It is a stand-in for the public benchmarks, not a copy of
  them. Watch the review queue on your own data.
- **Containers.** The image is built and smoke-tested in CI on amd64 and arm64 and published to GitHub's
  registry, but not yet tried on Docker Desktop for macOS or Windows, with an SSH agent for `strata sync`, or
  with `compose.yaml`. It is not signed yet ([Running in a container](Running-in-a-Container)).
- **Checks on pull requests** (`strata init --ci`): the workflow and the code behind it are tested, but the
  workflow has not yet run in a real review repository on GitHub.
- **Performance** targets (50,000 records imported in about 20 seconds and deduplicated in about two minutes)
  are met on the project's reference machine; very large reviews on slow disks have not been measured.

## Not built yet (planned)

- Packaging on PyPI, Homebrew and conda-forge.
- A hosted multi-user instance with sign-in (OpenID Connect) for teams that would rather not run anything
  themselves.
- Import from Zotero and a Covidence/Rayyan migration path.
- Screening-state filters, as above.

## Reporting a problem

Open an issue at <https://github.com/EGuthrieWasTaken/strata/issues> with the command you ran, what you
expected, what happened, and the output of `strata --version` and `strata verify`. If a review is involved,
the output of `strata status` helps; do not paste anything confidential.
