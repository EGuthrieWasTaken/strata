# Methods-text cookbook

Which command produces which part of a methods section, and what to check before the words go into a
manuscript. Every generated text is a **draft that reads from the repository**: it states what was done and
found, with the numbers taken from the event log and `analysis/results/`, and it says which commit it came
from. `strata` does not write a Discussion or Conclusion, and it does not say that a result is "significant"
or that anything "causes" anything outside text you quote yourself.

| For this | Run | You get |
|---|---|---|
| PRISMA 2020 flow diagram (item 16a) | `strata prisma --columns both --format svg` (or `pdf`, `png`, `json`) | `reports/prisma.svg`; every count reconciled first, marked DRAFT while screening is unfinished or decisions are stale |
| Information sources (item 6) | `strata report methods` | each database, platform and the date it was searched, and other methods (citation searching, websites, registers) with the date they were added |
| Search strategy (item 7) | `strata report checklist`, `strata export package` | item 7 of the checklist carries the verbatim query of every search; the supplement carries them for the manuscript to point at (the Methods text refers to it) |
| Selection and data collection (items 8, 9) | `strata report methods` | how many reviewers screened and whether independently, and their agreement (Cohen's kappa) |
| Eligibility criteria and **protocol amendments** (items 5, 24c) | `strata report methods`, `strata report amendments` | the current criteria with the stages they apply at, and each change made after screening began: what changed, why, which decisions it made stale and what became of them |
| Risk of bias (items 11, 18) | `strata report rob` (`--format svg` for the traffic-light plot) | the assessment table and plot, from the extraction of each reviewer pair |
| Study characteristics (item 17) | `strata report characteristics --format csv` | one row per included study |
| Results of syntheses (items 20a–d, 21) | `strata analyze --all`, then `strata report results` | pooled estimates, heterogeneity, prediction intervals, sensitivity and bias analyses, as run |
| The whole draft | `strata report manuscript --format docx` (also `md`, `html`, `latex`; needs `pandoc` for the last three) | Methods and Results together with the figures |
| The PRISMA 2020 checklist | `strata report checklist` and `strata report checklist --status` | each of the 42 items as auto-filled, auto-located or yours to write, with where in the repository each comes from |
| The reference list | `strata export bibliography --set included` (also `excluded-at-fulltext`, `all-screened`, `not-retrieved`; BibTeX, CSL-JSON, RIS) | a file for your reference manager |
| A supplement for item 27 | `strata export package --out supplement.zip` | the protocol, records, decisions, extractions and analyses, with no full text in it; needs `project.license` set in `strata.toml` |

## Before you paste anything

- **Read the draft against your methods.** The generated text describes what was *recorded*; if you did
  something the repository does not know about (a hand search that was never entered), it is not in the text.
- **Items marked "yours" in the checklist are yours:** the certainty of the evidence (item 15), limitations
  and the discussion (22, 23), registration and protocol (24a, 24b) unless you have recorded them in
  `strata.toml`, funding and competing interests (25, 26) likewise, and anything about code and data
  availability beyond the repository address.
- **A DRAFT watermark or a banner about uncommitted changes means exactly that.** Finish screening, run
  `strata rescreen` until nothing is stale, commit, and generate again. `--allow-stale` produces a draft you
  must not publish.
- **The statistics.** Name the method as the output does (for example "random-effects model, REML for
  tau-squared, Knapp–Hartung adjustment"); the formulae and sources are in [`statistics.md`](statistics.md).
  Report the prediction interval with its `k - 2` degrees of freedom convention if a reader will compare it with
  another package's.
- **The generated Methods have not yet had a methodologist's review** (see [`m5-plan.md`](m5-plan.md)); read
  them against the PRISMA 2020 statement (Page et al., *BMJ* 2021;372:n71) before you rely on them. The
  checklist's item wording is that statement's Table 1, word for word.
