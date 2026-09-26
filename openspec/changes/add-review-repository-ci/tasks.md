# Tasks

## 1. Action and workflow

- [ ] 1.1 Publish a `strata verify` GitHub Action
- [ ] 1.2 Publish a reusable workflow running verify, the status comment, and criteria-change detection
- [ ] 1.3 Implement `strata init --ci` to install it into a review repository

## 2. Pull-request checks

- [ ] 2.1 Fail the check when `strata verify` fails
- [ ] 2.2 Post a comment from `strata status --json` summarising records entering and leaving, decisions invalidated, and conflicts opened
- [ ] 2.3 Label criteria-changing pull requests `protocol-amendment` and request review from the configured methodologist

## 3. Tests

- [ ] 3.1 An integration test of `strata init --ci` output
- [ ] 3.2 A test of the status-comment rendering from a fixture `status --json`
