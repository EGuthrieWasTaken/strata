"""CI for review repositories: openspec:review-repository-ci.

The pull-request comment and protocol-amendment detection that the reusable workflow
(`.github/workflows/review-ci.yml`) and the `strata verify` action (`actions/verify`) use, and the
caller workflow `strata init --ci` installs. Everything here is built on `strata status --json` and
the committed criteria file, so it needs nothing private from `strata`.
"""
