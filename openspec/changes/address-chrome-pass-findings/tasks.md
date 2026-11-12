# Tasks

## 1. Specification

- [x] 1.1 `git-integration#batched-screening-commits`: the triggers in the browser, startup recovery, and the rationale for a changed decision
- [x] 1.2 `web-ui#screening-surface-requirements`: S3 reworded, S15 to S17 added
- [x] 1.3 `web-ui`: a session cookie per server; refusals in the reviewer's words; counts that say what they count; history and provenance with reason and date
- [x] 1.4 `prisma-reporting` (in `add-prisma-reporting`): reports counted once each, the bound on studies allows for splits

## 2. Implementation

- [x] 2.1 #84: `report/counts.py` identities, `studies_from_split_reports`, failures in words
- [x] 2.2 #85: `session_cookie_name`, hosted cookie names on a port of their own, the 403 text
- [x] 2.3 #83: `BatchTracker`, the triggers in `web/app.py` and `web/server.py`, `/session/finish`, changed decisions listed in the batch message, the command line's subject
- [x] 2.4 #86: `keyboard.js`, the screening routes and templates
- [x] 2.5 #87: `web/timeline.py`, `domain_log` date and reason, record counts
- [x] 2.6 #88: stale count labels, the assignment summary, analysis freshness
- [x] 2.7 #89: stacked tables, named scroll boxes, tab stop only when overflowing
- [x] 2.8 #90: `web/messages.py` and the codes on the domain errors
- [x] 2.9 #91: `scripts/seed_hosted.py`, the `hosted` scenario, Part H of `docs/chrome-pass.md`

## 3. Tests

- [x] 3.1 Each fix has a test that fails without it (unit and integration, named for the issue)
- [x] 3.2 Property P11 generates split reports, before and after a grouping
- [x] 3.3 `tests/browser`: the screening keys and Finish session, scroll boxes, stacked tables, and the hosted instance, in Chromium

## Notes

- The command line still asks for a rationale at the end of a `strata screen` session when the review requires
  one. That is stricter than the requirement (a routine batch needs none) and is left as it is: `--why` is how
  a script supplies it, and changing what a non-interactive run is refused for is a change of its own.
- `docs/chrome-pass.md` now expects the fixed behaviour, but nobody has run the pass again, and Part H (the
  hosted instance by hand, with two Chrome profiles) has never been run. The scripted browser tests cover the
  same ground.
