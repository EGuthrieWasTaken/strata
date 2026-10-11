"""The workflow `strata init --ci` installs into a review repository.

It is a thin caller of the reusable workflow in this project's own repository
(`.github/workflows/review-ci.yml`), pinned to the strata version that ran `init`. See
openspec:review-repository-ci#installable-review-ci.
"""

from __future__ import annotations

REVIEW_CI_WORKFLOW_PATH = ".github/workflows/strata.yml"

VERSION_PLACEHOLDER = "@@STRATA_VERSION@@"

REVIEW_CI_CALLER = f"""\
name: strata

# Installed by `strata init --ci`. Runs `strata verify` on every pull request, comments with the
# effect on the review's records, decisions and conflicts, and labels protocol amendments.
# To have a methodologist asked for review on those, set the repository variable
# STRATA_METHODOLOGIST to their GitHub login (Settings > Secrets and variables > Actions).
on:
  pull_request:

permissions:
  contents: read

jobs:
  review:
    uses: EGuthrieWasTaken/strata/.github/workflows/review-ci.yml@v{VERSION_PLACEHOLDER}
    with:
      strata-spec: strata-review=={VERSION_PLACEHOLDER}
      methodologist: ${{{{ vars.STRATA_METHODOLOGIST }}}}
    permissions:
      contents: read
      pull-requests: write
"""
