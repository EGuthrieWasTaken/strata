# Tasks

## 1. Action and workflow

- [ ] 1.1 Publish a `strata verify` GitHub Action
- [ ] 1.2 Publish a reusable workflow running verify, the status comment, and criteria-change detection
- [x] 1.3 Implement `strata init --ci` to install it into a review repository

## 2. Pull-request checks

- [ ] 2.1 Fail the check when `strata verify` fails
- [ ] 2.2 Post a comment from `strata status --json` summarising records entering and leaving, decisions invalidated, and conflicts opened
- [ ] 2.3 Label criteria-changing pull requests `protocol-amendment` and request review from the configured methodologist

## 3. Tests

- [x] 3.1 An integration test of `strata init --ci` output
- [x] 3.2 A test of the status-comment rendering from a fixture `status --json`

## Notes

Written and tested locally, not yet run on GitHub: tasks 1.1, 1.2 and 2.1-2.3 stay open for that.

- 1.1 / 1.2: `actions/verify/action.yml` and `.github/workflows/review-ci.yml` exist; "published" means
  merged to the default branch and tagged (the caller `strata init --ci` writes points at
  `v<version>`, which does not exist until a release is tagged; `--ci-ref main` works meanwhile).
- 2.1: the `verify` job runs `strata verify`; a failing exit code fails the job. Not seen failing on a
  runner.
- 2.2 / 2.3: the rendering, the amendment detection and the `gh` calls (post or edit one comment,
  label, request review, remove the label when the criteria are untouched) are tested with a fake `gh`;
  the real `gh` and the GitHub permissions model were not exercised. actionlint 1.7.12 reports no errors for the
  reusable workflow and the generated caller; it was not run with shellcheck.

