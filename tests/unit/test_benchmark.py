"""Unit tests for strata.dedup.benchmark, per
openspec:deduplication#validation-against-a-labelled-benchmark."""

from __future__ import annotations

from strata.dedup.benchmark import compute_metrics, final_cluster_ids


def _record(record_id: str, *, canonical: bool, absorbed: list[str] | None = None) -> dict:
    strata: dict = {"canonical_key": f"sig:{record_id}", "canonical": canonical, "sources": []}
    if absorbed is not None:
        strata["absorbed"] = absorbed
    return {"id": record_id, "type": "article-journal", "title": "T", "strata": strata}


def test_final_cluster_ids_canonical_maps_to_itself() -> None:
    records = [_record("rec_a", canonical=True)]
    assert final_cluster_ids(records) == {"rec_a": "rec_a"}


def test_final_cluster_ids_absorbed_maps_to_canonical() -> None:
    records = [
        _record("rec_a", canonical=True, absorbed=["rec_b"]),
        _record("rec_b", canonical=False),
    ]
    assert final_cluster_ids(records) == {"rec_a": "rec_a", "rec_b": "rec_a"}


def test_final_cluster_ids_chain_of_three() -> None:
    # A absorbed B then C -- `absorbed` is flattened by `_apply_merge`, so
    # both B and C map straight to A, not to each other.
    records = [
        _record("rec_a", canonical=True, absorbed=["rec_b", "rec_c"]),
        _record("rec_b", canonical=False),
        _record("rec_c", canonical=False),
    ]
    assert final_cluster_ids(records) == {"rec_a": "rec_a", "rec_b": "rec_a", "rec_c": "rec_a"}


def test_final_cluster_ids_records_not_yet_touched_by_dedup_are_absent() -> None:
    records = [_record("rec_a", canonical=True), _record("rec_untouched", canonical=True)]
    mapping = final_cluster_ids(records)
    assert mapping == {"rec_a": "rec_a", "rec_untouched": "rec_untouched"}


def test_compute_metrics_perfect_run() -> None:
    metrics = compute_metrics(
        duplicate_pairs={("rec_a", "rec_b")},
        auto_merged_pairs={("rec_a", "rec_b")},
        final_cluster_of={"rec_a": "rec_a", "rec_b": "rec_a"},
    )
    assert metrics.total_duplicate_pairs == 1
    assert metrics.resolved_duplicate_pairs == 1
    assert metrics.true_positive_events == 1
    assert metrics.false_positive_events == 0
    assert metrics.precision == 1.0
    assert metrics.recall == 1.0
    assert metrics.f1 == 1.0
    assert metrics.false_merge_rate == 0.0


def test_compute_metrics_credits_transitive_chain_resolution() -> None:
    # (rec_b, rec_c) has no direct auto-merge event -- both were absorbed
    # into rec_a -- but recall must still count it as resolved.
    metrics = compute_metrics(
        duplicate_pairs={("rec_a", "rec_b"), ("rec_a", "rec_c"), ("rec_b", "rec_c")},
        auto_merged_pairs={("rec_a", "rec_b"), ("rec_a", "rec_c")},
        final_cluster_of={"rec_a": "rec_a", "rec_b": "rec_a", "rec_c": "rec_a"},
    )
    assert metrics.recall == 1.0
    assert metrics.resolved_duplicate_pairs == 3


def test_compute_metrics_pair_order_is_normalised() -> None:
    metrics = compute_metrics(
        duplicate_pairs={("rec_b", "rec_a")},
        auto_merged_pairs={("rec_a", "rec_b")},
        final_cluster_of={"rec_a": "rec_a", "rec_b": "rec_a"},
    )
    assert metrics.recall == 1.0
    assert metrics.true_positive_events == 1


def test_compute_metrics_missed_pair_lowers_recall_not_precision() -> None:
    metrics = compute_metrics(
        duplicate_pairs={("rec_a", "rec_b"), ("rec_c", "rec_d")},
        auto_merged_pairs={("rec_a", "rec_b")},
        final_cluster_of={"rec_a": "rec_a", "rec_b": "rec_a"},  # c/d never merged
    )
    assert metrics.recall == 0.5
    assert metrics.precision == 1.0
    assert metrics.false_merge_rate == 0.0


def test_compute_metrics_false_merge_lowers_precision_and_false_merge_rate() -> None:
    metrics = compute_metrics(
        duplicate_pairs={("rec_a", "rec_b")},
        auto_merged_pairs={("rec_a", "rec_b"), ("rec_x", "rec_y")},  # x/y a wrongful merge
        final_cluster_of={"rec_a": "rec_a", "rec_b": "rec_a", "rec_x": "rec_x", "rec_y": "rec_x"},
    )
    assert metrics.recall == 1.0
    assert metrics.true_positive_events == 1
    assert metrics.false_positive_events == 1
    assert metrics.precision == 0.5
    assert metrics.false_merge_rate == 0.5
    assert 0.0 < metrics.f1 < 1.0


def test_compute_metrics_empty_ground_truth_defaults_recall_to_one() -> None:
    metrics = compute_metrics(duplicate_pairs=set(), auto_merged_pairs=set(), final_cluster_of={})
    assert metrics.total_duplicate_pairs == 0
    assert metrics.recall == 1.0
    assert metrics.precision == 1.0
    assert metrics.false_merge_rate == 0.0
    assert metrics.f1 == 1.0


def test_compute_metrics_no_auto_merges_at_all() -> None:
    metrics = compute_metrics(
        duplicate_pairs={("rec_a", "rec_b")},
        auto_merged_pairs=set(),
        final_cluster_of={},
    )
    assert metrics.recall == 0.0
    assert metrics.precision == 1.0  # no merge actions taken, so none were wrong
    assert metrics.false_merge_rate == 0.0
    assert metrics.f1 == 0.0
