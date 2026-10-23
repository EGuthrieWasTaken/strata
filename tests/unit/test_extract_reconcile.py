"""Dual extraction and reconciliation: openspec:data-extraction."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from strata.core.events import read_events
from strata.extract import reconcile as rc
from strata.extract import records as rec_mod
from tests.unit.test_extract_records import MEANS, _review, study

S = study(1)


def _dual(tmp_path: Path):  # type: ignore[no-untyped-def]
    repo = _review(tmp_path, mode="dual", studies=2)
    for handle, interval, source in (
        ("ethan", "1 week", "p. 1097 -- 1 week retention interval"),
        ("sam", "24 h", "Table 2 -- the 1-day condition"),
    ):
        rec_mod.set_field(repo, study=S, handle=handle, name="n_total", raw="148 @ p. 1097")
        rec_mod.set_field(repo, study=S, handle=handle, name="design", raw="rct", source="p. 1096")
        rec_mod.set_field(
            repo, study=S, handle=handle, name="retention_interval", raw=interval, source=source
        )
    return repo


def _events(repo, actor: str = "ethan") -> list[dict[str, Any]]:  # type: ignore[no-untyped-def]
    return read_events(repo.path("events", "reconcile", f"{actor}.ndjson"))


def test_comparison_lists_agreements_and_the_retention_interval_disagreement(
    tmp_path: Path,
) -> None:
    repo = _dual(tmp_path)
    comparison = rc.compare(repo, S)
    assert comparison.handles == ["ethan", "sam"]
    by_id = {i.id: i for i in comparison.items}
    assert by_id["field:n_total"].agree and by_id["field:design"].agree
    interval = by_id["field:retention_interval"]
    assert not interval.agree
    assert interval.candidates == {"ethan": "168 hours", "sam": "24 hours"}
    assert interval.sources["ethan"].startswith("p. 1097")
    assert [i.id for i in comparison.disagreements] == ["field:retention_interval"]
    assert len(comparison.unresolved) == 3


def test_reconciling_needs_two_reviewers(tmp_path: Path) -> None:
    repo = _review(tmp_path, mode="dual")
    rec_mod.set_field(repo, study=S, handle="ethan", name="n_total", raw="1")
    with pytest.raises(rc.ReconcileError, match="at least two"):
        rc.compare(repo, S)
    assert rc.all_comparisons(repo) == []


def test_agreements_are_confirmed_with_an_event_each_and_the_consensus_is_started(
    tmp_path: Path,
) -> None:
    repo = _dual(tmp_path)
    assert rc.accept_agreements(repo, study=S, reconciler="ethan") == 2
    assert rc.accept_agreements(repo, study=S, reconciler="ethan") == 0  # idempotent
    events = _events(repo)
    assert [e["body"]["field"] for e in events] == ["n_total", "design"]
    assert all(e["body"]["from"] == "agreement" and e["body"]["rationale"] for e in events)
    consensus = rec_mod.read_record(rec_mod.consensus_path(repo, S))
    assert consensus is not None
    assert consensus["fields"]["n_total"] == {"value": 148, "source": "p. 1097"}
    assert consensus["extracted_by"] == ["ethan", "sam"] and consensus["reconciled_by"] == "ethan"
    assert "retention_interval" not in consensus["fields"]


def test_choosing_a_reviewers_value_records_both_candidates_the_source_and_the_rationale(
    tmp_path: Path,
) -> None:
    """openspec scenario: ethan 168 h vs sam 24 h; the reconciler chooses ethan with a rationale."""
    repo = _dual(tmp_path)
    event = rc.resolve(
        repo,
        study=S,
        reconciler="ethan",
        item_id="field:retention_interval",
        choice="ethan",
        rationale="The paper states a one-week retention interval in the Methods.",
    )
    body = event["body"]
    assert (body["field"], body["chosen"], body["from"]) == ("retention_interval", 168, "ethan")
    assert body["candidates"] == {"ethan": "168 hours", "sam": "24 hours"}
    assert body["source"].startswith("p. 1097")
    assert body["rationale"].startswith("The paper states")
    consensus = rec_mod.read_record(rec_mod.consensus_path(repo, S))
    assert consensus is not None
    assert consensus["fields"]["retention_interval"]["entered"] == "1 week"
    item = {i.id: i for i in rc.compare(repo, S).items}["field:retention_interval"]
    assert item.resolved


def test_a_third_value_can_be_entered_and_is_coerced_like_any_other(tmp_path: Path) -> None:
    repo = _dual(tmp_path)
    event = rc.resolve(
        repo,
        study=S,
        reconciler="sam",
        item_id="field:retention_interval",
        choice="other",
        other_value="2 days",
        rationale="Neither value matched the table; the author confirmed two days.",
        source="Author email",
    )
    assert event["body"]["chosen"] == 48 and event["body"]["from"] == "other"
    consensus = rec_mod.read_record(rec_mod.consensus_path(repo, S))
    assert consensus is not None
    assert consensus["fields"]["retention_interval"]["source"] == "Author email"
    assert _events(repo, "sam")[0]["actor"] == "sam"


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"choice": "ethan", "rationale": " "}, "rationale"),
        ({"choice": "agreement", "rationale": "x"}, "disagreement"),
        ({"choice": "nobody", "rationale": "x"}, "choose one of"),
        ({"choice": "other", "rationale": "x"}, "needs a value"),
        ({"choice": "other", "rationale": "x", "other_value": "soon"}, "E_UNIT|number|unit"),
    ],
)
def test_bad_resolutions_are_refused_and_change_nothing(
    tmp_path: Path, kwargs: dict[str, str], message: str
) -> None:
    repo = _dual(tmp_path)
    with pytest.raises((rc.ReconcileError, rec_mod.ExtractionError), match=message):
        rc.resolve(repo, study=S, reconciler="ethan", item_id="field:retention_interval", **kwargs)
    assert not rec_mod.consensus_path(repo, S).exists() and _events(repo) == []


def test_resolving_an_unknown_item_is_an_error(tmp_path: Path) -> None:
    repo = _dual(tmp_path)
    with pytest.raises(rc.ReconcileError, match="nothing to reconcile"):
        rc.resolve(
            repo, study=S, reconciler="ethan", item_id="field:nope", choice="ethan", rationale="x"
        )


# --- effects ---------------------------------------------------------------------------------


def _add_effect(repo, handle: str, **inputs: Any) -> None:  # type: ignore[no-untyped-def]
    rec_mod.add_effect(
        repo,
        study=S,
        handle=handle,
        outcome="recall",
        design="two-group-means",
        inputs={**MEANS, **inputs},
        timepoint="1 week",
        source="Table 2",
    )


def test_effect_inputs_are_compared_individually_and_get_ids_in_the_consensus(
    tmp_path: Path,
) -> None:
    repo = _review(tmp_path, mode="dual")
    _add_effect(repo, "ethan")
    _add_effect(repo, "sam", sd2=0.25)
    items = {i.id: i for i in rc.compare(repo, S).items}
    assert not items["effect-input:recall|1 week|:sd2"].agree
    assert items["effect-input:recall|1 week|:n1"].agree
    assert rc.accept_agreements(repo, study=S, reconciler="ethan") == 5
    rc.resolve(
        repo, study=S, reconciler="ethan", item_id="effect-input:recall|1 week|:sd2",
        choice="sam", rationale="Table 2 prints 0.25; ethan transposed the digits.",
    )  # fmt: skip
    consensus = rec_mod.read_record(rec_mod.consensus_path(repo, S))
    assert consensus is not None
    [effect] = consensus["effects"]
    assert effect["id"] == f"eff_{S[4:]}_0001"
    assert (effect["outcome"], effect["design"], effect["timepoint"]) == (
        "recall",
        "two-group-means",
        "1 week",
    )
    assert effect["sd2"] == 0.25 and effect["n1"] == 74
    assert any(e["body"]["field"] == "effects.recall|1 week|.sd2" for e in _events(repo))


def test_an_effect_only_one_reviewer_found_can_be_kept_or_dropped(tmp_path: Path) -> None:
    repo = _review(tmp_path, mode="dual")
    rec_mod.set_field(repo, study=S, handle="ethan", name="n_total", raw="9")
    rec_mod.set_field(repo, study=S, handle="sam", name="n_total", raw="9")
    _add_effect(repo, "ethan")
    items = {i.id: i for i in rc.compare(repo, S).items}
    only = items["effect:recall|1 week|"]
    assert only.candidates == {"ethan": "extracted", "sam": "not extracted"} and not only.agree
    with pytest.raises(rc.ReconcileError, match="did not extract"):
        rc.resolve(repo, study=S, reconciler="ethan", item_id=only.id, choice="sam", rationale="x")
    event = rc.resolve(
        repo, study=S, reconciler="sam", item_id=only.id, choice="ethan", rationale="Table 2 has it"
    )
    assert event["body"]["chosen"]["n1"] == 74
    consensus = rec_mod.read_record(rec_mod.consensus_path(repo, S))
    assert consensus is not None and consensus["effects"][0]["id"].endswith("_0001")
    assert rc.compare(repo, S).items[-1].resolved


def test_dropping_an_effect_is_a_recorded_decision(tmp_path: Path) -> None:
    repo = _review(tmp_path, mode="dual")
    rec_mod.set_field(repo, study=S, handle="ethan", name="n_total", raw="9")
    rec_mod.set_field(repo, study=S, handle="sam", name="n_total", raw="9")
    _add_effect(repo, "sam")
    item = next(i for i in rc.compare(repo, S).items if i.kind == "effect")
    event = rc.resolve(
        repo, study=S, reconciler="ethan", item_id=item.id, choice="dropped",
        rationale="A pilot condition outside the protocol.",
    )  # fmt: skip
    assert event["body"]["from"] == "dropped" and event["body"]["chosen"] is None
    assert next(i for i in rc.compare(repo, S).items if i.kind == "effect").resolved
    consensus = rec_mod.read_record(rec_mod.consensus_path(repo, S))
    assert consensus is not None and not consensus.get("effects")


def test_agreement_rate_counts_independent_agreement(tmp_path: Path) -> None:
    repo = _dual(tmp_path)
    rate = rc.agreement_rate(rc.all_comparisons(repo))
    assert (rate["compared"], rate["agreed"]) == (3, 2)
    assert rate["rate"] == pytest.approx(2 / 3)
    assert rc.agreement_rate([])["rate"] == 1.0


def test_fields_only_one_reviewer_filled_in_are_disagreements(tmp_path: Path) -> None:
    repo = _dual(tmp_path)
    rec_mod.set_field(repo, study=S, handle="ethan", name="mean_age", raw="20.4 @ Table 1")
    item = {i.id: i for i in rc.compare(repo, S).items}["field:mean_age"]
    assert not item.agree and item.candidates == {"ethan": 20.4, "sam": None}
    rec_mod.set_field(repo, study=S, handle="sam", name="mean_age", raw="NR")
    item = {i.id: i for i in rc.compare(repo, S).items}["field:mean_age"]
    assert item.candidates["sam"] == "NR" and not item.agree
    rc.resolve(
        repo,
        study=S,
        reconciler="ethan",
        item_id=item.id,
        choice="ethan",
        rationale="Table 1 reports it",
    )
    consensus = rec_mod.read_record(rec_mod.consensus_path(repo, S))
    assert consensus is not None and consensus["fields"]["mean_age"]["value"] == 20.4
