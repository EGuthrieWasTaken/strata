"""Pairwise similarity scoring for deduplication.

Implements openspec:deduplication#scoring exactly, including the DOI
veto. Pure functions only (openspec:architecture#the-fold-is-pure): no
I/O, no thresholds, no merge decisions -- those are sub-objective 6's CLI/
review-queue layer, which decides what to *do* with a `PairScore`.

Every similarity function returns 0.0 when the relevant field is missing on
both sides, never 1.0 -- missing data is not evidence of a match, and this
project weighs a false merge (which destroys data) far more heavily than a
missed duplicate (which only costs screening time). This is a judgement call
the spec text does not make explicit; it is applied consistently everywhere
below rather than left to vary case by case.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from strata.core.ids import (
    normalise_author_family,
    normalise_doi,
    normalise_journal,
    normalise_pages,
    normalise_title,
    normalise_year,
)

TITLE_WEIGHT = 0.50
AUTHOR_WEIGHT = 0.20
YEAR_WEIGHT = 0.15
JOURNAL_WEIGHT = 0.10
LOCATOR_WEIGHT = 0.05


@dataclass(frozen=True)
class PairScore:
    """The result of scoring one candidate pair, per openspec:deduplication#scoring.

    `score` is the value thresholds are compared against
    (openspec:deduplication#thresholds-and-actions): 1.0/0.0 when
    both records have a DOI, the weighted feature sum otherwise. `doi_veto` is
    `True` exactly when both records had a DOI and they differed, forcing
    `score` to 0.0 regardless of how similar everything else is. `features`
    is always populated (even under a DOI veto) so a caller can label a
    high-scoring veto as `doi-conflict` (openspec:deduplication#scoring's explicit carve-out) and so
    `strata why`/the review queue can show the breakdown either way.
    """

    score: float
    doi_veto: bool
    features: dict[str, float]

    @property
    def non_doi_score(self) -> float:
        """The weighted feature sum, ignoring any DOI veto -- what openspec:deduplication#scoring
        calls the
        score to test a `doi_veto`'d pair against `review_threshold` for a
        `doi-conflict` label."""
        return (
            TITLE_WEIGHT * self.features["title"]
            + AUTHOR_WEIGHT * self.features["author"]
            + YEAR_WEIGHT * self.features["year"]
            + JOURNAL_WEIGHT * self.features["journal"]
            + LOCATOR_WEIGHT * self.features["locator"]
        )


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 0.0
    return len(a & b) / len(a | b)


def _levenshtein_distance(a: str, b: str) -> int:
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    previous_row = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        current_row = [i] + [0] * len(b)
        for j, cb in enumerate(b, start=1):
            current_row[j] = min(
                current_row[j - 1] + 1,
                previous_row[j] + 1,
                previous_row[j - 1] + (0 if ca == cb else 1),
            )
        previous_row = current_row
    return previous_row[-1]


def _levenshtein_ratio(a: str, b: str) -> float:
    if not a and not b:
        return 0.0
    return 1.0 - _levenshtein_distance(a, b) / max(len(a), len(b))


def _author_family_set(record: dict[str, Any]) -> set[str]:
    """Normalised family names (or a corporate author's literal name) for Jaccard."""
    families = set()
    for author in record.get("author") or []:
        name = author.get("family") or author.get("literal") if isinstance(author, dict) else author
        if not name:
            continue
        stripped, _unstripped = normalise_author_family(name)
        if stripped:
            families.add(stripped)
    return families


def title_sim(record_a: dict[str, Any], record_b: dict[str, Any]) -> float:
    """Token-set ratio: max(Jaccard on token sets, Levenshtein ratio on sorted tokens)."""
    norm_a, norm_b = normalise_title(record_a.get("title")), normalise_title(record_b.get("title"))
    if not norm_a and not norm_b:
        return 0.0
    tokens_a, tokens_b = set(norm_a.split()), set(norm_b.split())
    jaccard = _jaccard(tokens_a, tokens_b)
    sorted_a, sorted_b = " ".join(sorted(tokens_a)), " ".join(sorted(tokens_b))
    return max(jaccard, _levenshtein_ratio(sorted_a, sorted_b))


def author_sim(record_a: dict[str, Any], record_b: dict[str, Any]) -> float:
    """Jaccard over normalised family-name sets; halved if either side has only one author."""
    families_a, families_b = _author_family_set(record_a), _author_family_set(record_b)
    jaccard = _jaccard(families_a, families_b)
    if len(families_a) == 1 or len(families_b) == 1:
        return 0.5 * jaccard
    return jaccard


def year_sim(record_a: dict[str, Any], record_b: dict[str, Any]) -> float:
    """1.0 if equal, 0.7 if off by one (online-first vs. issue year), 0.0 otherwise."""
    year_a, year_b = normalise_year(record_a.get("issued")), normalise_year(record_b.get("issued"))
    if year_a is None or year_b is None:
        return 0.0
    diff = abs(year_a - year_b)
    if diff == 0:
        return 1.0
    if diff == 1:
        return 0.7
    return 0.0


def journal_sim(record_a: dict[str, Any], record_b: dict[str, Any]) -> float:
    """Normalised container-title ratio, after abbreviation expansion."""
    journal_a = normalise_journal(record_a.get("container-title"))
    journal_b = normalise_journal(record_b.get("container-title"))
    if not journal_a and not journal_b:
        return 0.0
    return _levenshtein_ratio(journal_a, journal_b)


def locator_sim(record_a: dict[str, Any], record_b: dict[str, Any]) -> float:
    """1.0 if volume and first page both match, 0.5 if one does, 0.0 otherwise."""
    # `normalise_pages` is "the first integer run of a value" -- exactly the
    # transformation a volume number needs too, so it is reused rather than
    # duplicated for a value that happens to come from a different field.
    volume_a = normalise_pages(record_a.get("volume"))
    volume_b = normalise_pages(record_b.get("volume"))
    page_a, page_b = normalise_pages(record_a.get("page")), normalise_pages(record_b.get("page"))
    volume_match = bool(volume_a) and volume_a == volume_b
    page_match = bool(page_a) and page_a == page_b
    if volume_match and page_match:
        return 1.0
    if volume_match or page_match:
        return 0.5
    return 0.0


def score_pair(record_a: dict[str, Any], record_b: dict[str, Any]) -> PairScore:
    """Score one candidate pair per openspec:deduplication#scoring.

    Feature scores are always computed (needed for `doi-conflict` labelling
    and for explainability), even when a DOI veto or DOI match decides the
    final `score` outright.
    """
    features = {
        "title": title_sim(record_a, record_b),
        "author": author_sim(record_a, record_b),
        "year": year_sim(record_a, record_b),
        "journal": journal_sim(record_a, record_b),
        "locator": locator_sim(record_a, record_b),
    }

    doi_a, doi_b = normalise_doi(record_a.get("DOI")), normalise_doi(record_b.get("DOI"))
    if doi_a and doi_b:
        if doi_a == doi_b:
            return PairScore(score=1.0, doi_veto=False, features=features)
        return PairScore(score=0.0, doi_veto=True, features=features)

    weighted = (
        TITLE_WEIGHT * features["title"]
        + AUTHOR_WEIGHT * features["author"]
        + YEAR_WEIGHT * features["year"]
        + JOURNAL_WEIGHT * features["journal"]
        + LOCATOR_WEIGHT * features["locator"]
    )
    return PairScore(score=weighted, doi_veto=False, features=features)
