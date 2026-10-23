"""The workflow `strata init --ci` installs into a review repository.

Implements openspec:review-repository-ci#installable-review-ci. The installed file is a thin
caller: the checks themselves live in the reusable workflow published from the `strata` repository
(`.github/workflows/review-ci.yml`), so a review repository picks up fixes by moving the ref it
pins, and its own history holds only the one decision that matters, which version to trust.
"""

from __future__ import annotations

from strata import __version__

STRATA_REPOSITORY = "EGuthrieWasTaken/strata"
REUSABLE_WORKFLOW = ".github/workflows/review-ci.yml"
CALLER_PATH = ".github/workflows/strata.yml"
AMENDMENT_LABEL = "protocol-amendment"


def default_ref() -> str:
    """The tag that corresponds to this installation of `strata`."""
    return f"v{__version__}"


def caller_workflow(*, ref: str | None = None, methodologist: str | None = None) -> str:
    """The text of `.github/workflows/strata.yml`.

    `ref` is the tag, branch or commit of the `strata` repository to run the checks from (default:
    the tag of this release); `methodologist` is the GitHub login (or `org/team`) asked to review a
    pull request that changes the criteria.
    """
    pinned = ref or default_ref()
    reviewer = (methodologist or "").lstrip("@")
    return f"""\
name: Strata review checks

# Installed by `strata init --ci` (openspec:review-repository-ci). The checks run from the
# reusable workflow in {STRATA_REPOSITORY} at the ref below; move the ref to take a newer version.
#
# On every pull request: `strata verify` (the check fails on any violation), a comment saying
# what the change does to the review (records entering and leaving, decisions invalidated,
# screening conflicts opened), and, if the criteria changed, the `{AMENDMENT_LABEL}` label and a
# review request to the methodologist. The comment and label need a token that can write to the
# pull request, which pull requests from forks do not get; for those the verify check still runs.
on:
  pull_request:

permissions:
  contents: read

jobs:
  strata:
    permissions:
      contents: read
      pull-requests: write
    uses: {STRATA_REPOSITORY}/{REUSABLE_WORKFLOW}@{pinned}
    with:
      strata-ref: "{pinned}"
      methodologist: "{reviewer}"
"""
