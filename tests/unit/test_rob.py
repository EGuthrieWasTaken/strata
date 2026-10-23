"""Risk-of-bias instruments, assessments, overrides, moderators (openspec:risk-of-bias)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from strata.core.canon import dump_yaml_str
from strata.core.events import read_events
from strata.extract import rob
from tests.unit.test_extract_records import _review, study

S1, S2 = study(1), study(2)


def _ready(tmp_path: Path, instrument: str = "rob2", **kwargs: Any):  # type: ignore[no-untyped-def]
    repo = _review(tmp_path, **kwargs)
    rob.init_instrument(repo, instrument)
    return repo


def _answer_d1(repo, handle: str = "ethan", study_id: str = S1, **answers: str) -> None:  # type: ignore[no-untyped-def]
    values = {"1.1": "Y", "1.2": "Y", "1.3": "N", **answers}
    for question, answer in values.items():
        rob.answer_question(
            repo, study=study_id, handle=handle, domain="D1", question=question, answer=answer
        )


def _events(repo, actor: str = "ethan") -> list[dict[str, Any]]:  # type: ignore[no-untyped-def]
    return read_events(repo.path("events", "rob", f"{actor}.ndjson"))


# --- instruments -----------------------------------------------------------------------------


@pytest.mark.parametrize("instrument_id", rob.BUILTIN_IDS)
def test_every_shipped_instrument_is_valid(instrument_id: str) -> None:
    instrument = rob.builtin_instrument(instrument_id)
    assert instrument.doc["id"] == instrument_id and instrument.domains


def test_rob2_has_the_five_domains_and_a_worst_domain_overall() -> None:
    instrument = rob.builtin_instrument("rob2")
    assert [d["id"] for d in instrument.domains] == ["D1", "D2", "D3", "D4", "D5"]
    assert instrument.overall_algorithm == "worst-domain"
    assert instrument.overall_judgements == ["low", "some-concerns", "high"]
    assert instrument.domain("D2")["algorithm"] == "rob2-d2-assignment"  # type: ignore[index]
    adhering = rob.builtin_instrument("rob2-adhering")
    assert adhering.domain("D2")["algorithm"] == "rob2-d2-adhering"  # type: ignore[index]
    assert "adhering" in adhering.domain("D2")["label"]  # type: ignore[index]


def test_shipped_instruments_do_not_reproduce_the_official_question_wording() -> None:
    for instrument_id in rob.BUILTIN_IDS:
        for domain in rob.builtin_instrument(instrument_id).domains:
            for question in domain.get("signalling_questions", []):
                assert "text" not in question and question["topic"]


def test_robins_i_has_seven_reviewer_judged_domains() -> None:
    instrument = rob.builtin_instrument("robins-i")
    assert len(instrument.domains) == 7 and all("algorithm" not in d for d in instrument.domains)
    assert instrument.overall_judgements == ["low", "moderate", "serious", "critical"]


def test_nos_awards_stars_and_sums_them() -> None:
    for instrument_id, last in (("nos-cohort", "outcome"), ("nos-case-control", "exposure")):
        instrument = rob.builtin_instrument(instrument_id)
        assert [d["id"] for d in instrument.domains] == ["selection", "comparability", last]
        assert instrument.overall_algorithm == "sum"


def test_a_custom_instrument_in_the_documented_shape_validates() -> None:
    """openspec scenario: a project defines a custom instrument -> it validates and is usable."""
    custom = {
        "instrument": "House checklist",
        "version": "1",
        "applies_to": ["rct"],
        "domains": [
            {
                "id": "A",
                "label": "Blinding",
                "judgements": ["ok", "not-ok"],
                "signalling_questions": [{"id": "A.1", "options": ["Y", "N"], "text": "Blinded?"}],
            }
        ],
        "overall": {"algorithm": "custom"},
    }
    assert rob.parse_instrument(custom).domain("A") is not None


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda d: d["domains"].append(dict(d["domains"][0])), "unique"),
        (lambda d: d["domains"][0].update(id="overall"), "unique"),
        (lambda d: d["domains"][0].update(algorithm="rob9-d9"), "no built-in algorithm"),
        (lambda d: d["domains"][0]["signalling_questions"].append(
            dict(d["domains"][0]["signalling_questions"][0])), "duplicate signalling"),
        (lambda d: d["overall"].update(algorithm="sum"), "numeric"),
        (lambda d: d.pop("version"), "version"),
        (lambda d: d["domains"][0].update(judgements=["only-one"]), "too short"),
    ],
)  # fmt: skip
def test_invalid_instruments_are_rejected(mutate: Any, message: str) -> None:
    doc = rob.builtin_instrument("rob2").doc
    mutate(doc)
    with pytest.raises(rob.RobError, match=message):
        rob.parse_instrument(doc)


def test_init_writes_the_instrument_once(tmp_path: Path) -> None:
    repo = _review(tmp_path)
    with pytest.raises(rob.RobError, match="strata rob init"):
        rob.load_instrument(repo)
    rob.init_instrument(repo, "robins-i")
    assert rob.load_instrument(repo).name == "ROBINS-I"
    with pytest.raises(rob.RobError, match="already exists"):
        rob.init_instrument(repo, "rob2")
    assert rob.init_instrument(repo, "rob2", overwrite=True).name == "RoB 2"
    with pytest.raises(rob.RobError, match="no built-in"):
        rob.builtin_instrument("rob9")


# --- answers, suggestions, judgements --------------------------------------------------------


def test_answering_questions_produces_a_suggestion_and_names_the_next_question(
    tmp_path: Path,
) -> None:
    repo = _ready(tmp_path)
    state = rob.answer_question(
        repo, study=S1, handle="ethan", domain="D1", question="1.2", answer="Y"
    )
    assert (state.suggested, state.needed) == (None, "1.1")
    state = rob.answer_question(
        repo, study=S1, handle="ethan", domain="D1", question="1.1", answer="Y"
    )
    assert state.needed == "1.3"
    state = rob.answer_question(
        repo, study=S1, handle="ethan", domain="D1", question="1.3", answer="N"
    )
    assert (state.suggested, state.needed) == ("low", None)
    assert state.answers == {"1.2": "Y", "1.1": "Y", "1.3": "N"}


def test_answers_are_validated(tmp_path: Path) -> None:
    repo = _ready(tmp_path)
    for kwargs, message in (
        ({"domain": "D9", "question": "1.1", "answer": "Y"}, "no domain"),
        ({"domain": "D1", "question": "9.9", "answer": "Y"}, "no signalling question"),
        ({"domain": "D1", "question": "1.1", "answer": "Maybe"}, "answer must be one of"),
    ):
        with pytest.raises(rob.RobError, match=message):
            rob.answer_question(repo, study=S1, handle="ethan", **kwargs)
    with pytest.raises(rob.RobError, match="no included study"):
        rob.answer_question(
            repo, study="std_" + "9" * 16, handle="ethan", domain="D1", question="1.1", answer="Y"
        )


def test_a_domain_judgement_is_a_rob_event_with_its_support(tmp_path: Path) -> None:
    """openspec scenario: Domain 1 judged low with support -> study, domain, judgement, support."""
    repo = _ready(tmp_path)
    _answer_d1(repo)
    event = rob.record_judgement(
        repo, study=S1, handle="ethan", domain="D1", judgement="low",
        support="Computer-generated sequence; central allocation.", source="p. 3, Methods",
    )  # fmt: skip
    body = event["body"]
    assert (body["study"], body["domain"], body["judgement"]) == (S1, "D1", "low")
    assert body["support"].startswith("Computer-generated") and body["source"] == "p. 3, Methods"
    assert body["suggested"] == "low" and body["signalling"] == {"1.1": "Y", "1.2": "Y", "1.3": "N"}
    assert "override_justification" not in body and body["scope"] == "consensus"
    saved = rob.read_assessment(rob.consensus_path(repo, S1))
    assert saved is not None and saved["domains"]["D1"]["judgement"] == "low"


def test_overriding_the_suggestion_needs_a_justification_and_records_both(tmp_path: Path) -> None:
    """openspec scenario: suggests LOW; the reviewer judges SOME CONCERNS with a justification."""
    repo = _ready(tmp_path)
    _answer_d1(repo)
    with pytest.raises(rob.RobError, match="justification"):
        rob.record_judgement(repo, study=S1, handle="ethan", domain="D1", judgement="some-concerns")
    assert _events(repo) == []
    event = rob.record_judgement(
        repo, study=S1, handle="ethan", domain="D1", judgement="some-concerns",
        override_justification="The trial registry shows the sequence was changed mid-trial.",
    )  # fmt: skip
    assert event["body"]["suggested"] == "low" and event["body"]["judgement"] == "some-concerns"
    assert event["body"]["override_justification"].startswith("The trial registry")
    saved = rob.read_assessment(rob.consensus_path(repo, S1))
    assert saved is not None
    assert saved["domains"]["D1"]["suggested"] == "low"
    assert "justification" not in saved["domains"]["D1"]


def test_agreeing_with_the_suggestion_clears_an_earlier_override(tmp_path: Path) -> None:
    repo = _ready(tmp_path)
    _answer_d1(repo)
    rob.record_judgement(
        repo,
        study=S1,
        handle="ethan",
        domain="D1",
        judgement="high",
        override_justification="Seen it.",
    )
    rob.record_judgement(repo, study=S1, handle="ethan", domain="D1", judgement="low")
    saved = rob.read_assessment(rob.consensus_path(repo, S1))
    assert saved is not None and "override_justification" not in saved["domains"]["D1"]


def test_judging_without_a_suggestion_is_allowed(tmp_path: Path) -> None:
    repo = _ready(tmp_path)  # no answers yet, so no suggestion to override
    event = rob.record_judgement(repo, study=S1, handle="ethan", domain="D3", judgement="high")
    assert "suggested" not in event["body"]


def test_judgements_are_validated(tmp_path: Path) -> None:
    repo = _ready(tmp_path)
    with pytest.raises(rob.RobError, match="must be one of"):
        rob.record_judgement(repo, study=S1, handle="ethan", domain="D1", judgement="fine")
    with pytest.raises(rob.RobError, match="no domain"):
        rob.record_judgement(repo, study=S1, handle="ethan", domain="D9", judgement="low")
    with pytest.raises(rob.RobError, match="no included study"):
        rob.record_judgement(
            repo, study="std_" + "9" * 16, handle="ethan", domain="D1", judgement="low"
        )


# --- overall ---------------------------------------------------------------------------------


def _judge_all(repo, judgements: dict[str, str], study_id: str = S1) -> None:  # type: ignore[no-untyped-def]
    for domain, judgement in judgements.items():
        rob.record_judgement(
            repo, study=study_id, handle="ethan", domain=domain, judgement=judgement
        )


def test_overall_is_suggested_once_every_domain_is_judged(tmp_path: Path) -> None:
    repo = _ready(tmp_path)
    instrument = rob.load_instrument(repo)
    _judge_all(repo, {"D1": "low", "D2": "low", "D3": "low", "D4": "low"})
    assert (
        rob.overall_suggestion(instrument, rob.read_assessment(rob.consensus_path(repo, S1)))
        is None
    )
    _judge_all(repo, {"D5": "some-concerns"})
    assessment = rob.read_assessment(rob.consensus_path(repo, S1))
    assert rob.overall_suggestion(instrument, assessment) == "some-concerns"
    _judge_all(repo, {"D2": "high"})
    assert (
        rob.overall_suggestion(instrument, rob.read_assessment(rob.consensus_path(repo, S1)))
        == "high"
    )


def test_the_overall_can_be_overridden_with_a_justification(tmp_path: Path) -> None:
    repo = _ready(tmp_path)
    _judge_all(repo, {d: "some-concerns" for d in ("D1", "D2", "D3", "D4", "D5")})
    with pytest.raises(rob.RobError, match="justification"):
        rob.record_judgement(repo, study=S1, handle="ethan", domain="overall", judgement="high")
    event = rob.record_judgement(
        repo, study=S1, handle="ethan", domain="overall", judgement="high",
        override_justification="Some concerns in all five domains together.",
    )  # fmt: skip
    assert event["body"]["suggested"] == "some-concerns" and event["body"]["domain"] == "overall"


def test_robins_i_overall_is_the_most_severe_domain_or_no_information(tmp_path: Path) -> None:
    repo = _ready(tmp_path, "robins-i")
    instrument = rob.load_instrument(repo)

    def overall(judgements: dict[str, str]) -> str | None:
        return rob.overall_suggestion(
            instrument, {"domains": {d: {"judgement": j} for d, j in judgements.items()}}
        )

    ids = [f"D{i}" for i in range(1, 8)]
    assert overall({d: "low" for d in ids}) == "low"
    assert overall({**{d: "low" for d in ids}, "D3": "serious"}) == "serious"
    assert overall({**{d: "low" for d in ids}, "D3": "critical", "D5": "moderate"}) == "critical"
    assert overall({**{d: "moderate" for d in ids}, "D6": "no-information"}) == "no-information"
    assert (
        overall({**{d: "low" for d in ids}, "D6": "serious", "D2": "no-information"}) == "serious"
    )
    assert overall({d: "low" for d in ids[:-1]}) is None


def test_nos_overall_is_the_star_total(tmp_path: Path) -> None:
    repo = _ready(tmp_path, "nos-cohort")
    _judge_all(repo, {"selection": "4", "comparability": "1", "outcome": "2"})
    event = rob.record_judgement(repo, study=S1, handle="ethan", domain="overall", judgement="7")
    assert event["body"]["suggested"] == "7"
    with pytest.raises(rob.RobError, match="justification"):
        rob.record_judgement(repo, study=S1, handle="ethan", domain="overall", judgement="9")
    with pytest.raises(rob.RobError, match="number"):
        rob.record_judgement(repo, study=S1, handle="ethan", domain="overall", judgement="good")


def test_a_custom_overall_has_no_suggestion(tmp_path: Path) -> None:
    repo = _review(tmp_path)
    custom = {
        "instrument": "House",
        "version": "1",
        "applies_to": ["rct"],
        "domains": [{"id": "A", "label": "A", "judgements": ["ok", "bad"]}],
        "overall": {"algorithm": "custom"},
    }
    repo.path("rob", "instrument.yaml").write_text(dump_yaml_str(custom), encoding="utf-8")
    instrument = rob.load_instrument(repo)
    _judge_all(repo, {"A": "ok"})
    assert (
        rob.overall_suggestion(instrument, rob.read_assessment(rob.consensus_path(repo, S1)))
        is None
    )
    rob.record_judgement(repo, study=S1, handle="ethan", domain="overall", judgement="ok")


# --- moderators ------------------------------------------------------------------------------


def test_consensus_judgements_become_moderators(tmp_path: Path) -> None:
    repo = _ready(tmp_path, studies=3)
    assert rob.moderators(repo) == {}
    _judge_all(repo, {d: "low" for d in ("D1", "D2", "D3", "D4", "D5")}, S1)
    rob.record_judgement(repo, study=S1, handle="ethan", domain="overall", judgement="low")
    _judge_all(repo, {"D1": "high"}, S2)
    found = rob.moderators(repo)
    assert found[S1]["rob_overall"] == "low" and found[S1]["rob.D1"] == "low"
    assert found[S2] == {
        "rob_overall": None, "rob.D1": "high", "rob.D2": None, "rob.D3": None,
        "rob.D4": None, "rob.D5": None,
    }  # fmt: skip
    low_risk = [s for s, m in found.items() if m["rob_overall"] == "low"]
    assert low_risk == [S1]  # the "low-risk sensitivity analysis" subset


def test_moderators_need_an_instrument_and_ignore_excluded_studies(tmp_path: Path) -> None:
    repo = _review(tmp_path)
    assert rob.moderators(repo) == {}
    rob.init_instrument(repo, "rob2")
    _judge_all(repo, {"D1": "low"}, S1)
    stray = rob.consensus_path(repo, "std_" + "9" * 16)
    stray.write_text(
        dump_yaml_str({"study": "std_" + "9" * 16, "instrument": "rob2", "instrument_version": "x",
                       "assessed_by": ["ethan"], "domains": {"D1": {"judgement": "low"}}}),
        encoding="utf-8",
    )  # fmt: skip
    assert set(rob.moderators(repo)) == {S1}


# --- validation ------------------------------------------------------------------------------


def test_validate_assessment_flags_each_kind_of_problem() -> None:
    instrument = rob.builtin_instrument("rob2")
    good = {"domains": {"D1": {"answers": {"1.1": "Y"}, "judgement": "low", "suggested": "low"}}}
    assert rob.validate_assessment(instrument, good) == []
    bad = {
        "domains": {
            "D1": {"answers": {"1.1": "Maybe", "9.9": "Y"}, "judgement": "fine"},
            "D9": {"judgement": "low"},
            "D2": {"judgement": "high", "suggested": "low"},
        }
    }
    problems = rob.validate_assessment(instrument, bad)
    assert len(problems) == 5
    assert any("not in the instrument" in p for p in problems)
    assert any("without a justification" in p for p in problems)


# --- dual-mode reconciliation ----------------------------------------------------------------


def _dual(tmp_path: Path):  # type: ignore[no-untyped-def]
    repo = _ready(tmp_path, mode="dual", studies=2)
    for handle, judgement in (("ethan", "low"), ("sam", "some-concerns")):
        _answer_d1(repo, handle)
        why = None if judgement == "low" else "Allocation unclear in registry."
        rob.record_judgement(
            repo, study=S1, handle=handle, domain="D1", judgement=judgement,
            override_justification=why,
        )  # fmt: skip
        rob.record_judgement(repo, study=S1, handle=handle, domain="D3", judgement="high")
    return repo


def test_dual_reviewers_assess_independently_into_their_own_files(tmp_path: Path) -> None:
    repo = _dual(tmp_path)
    assert not rob.consensus_path(repo, S1).exists()
    assert rob.reviewer_handles(repo, S1) == ["ethan", "sam"]
    assert _events(repo, "sam")[0]["body"]["scope"] == "reviewer"


def test_comparison_shows_agreements_and_disagreements(tmp_path: Path) -> None:
    repo = _dual(tmp_path)
    by_domain = {i.domain: i for i in rob.compare(repo, S1)}
    assert by_domain["D3"].agree and not by_domain["D1"].agree
    assert by_domain["D1"].candidates == {"ethan": "low", "sam": "some-concerns"}
    assert set(by_domain) == {"D1", "D3"}


def test_reconciling_records_both_a_reconcile_and_a_consensus_rob_event(tmp_path: Path) -> None:
    repo = _dual(tmp_path)
    rob.resolve(
        repo, study=S1, reconciler="ethan", domain="D3", choice="agreement", rationale="Both high."
    )
    event = rob.resolve(
        repo, study=S1, reconciler="ethan", domain="D1", choice="sam",
        rationale="The registry entry settles it.",
    )  # fmt: skip
    assert event["body"]["field"] == "rob.D1" and event["body"]["chosen"] == "some-concerns"
    consensus = rob.read_assessment(rob.consensus_path(repo, S1))
    assert consensus is not None and consensus["reconciled_by"] == "ethan"
    assert consensus["domains"]["D1"]["judgement"] == "some-concerns"
    assert consensus["domains"]["D1"]["override_justification"].startswith("Allocation unclear")
    kinds = [(e["ev"], e["body"].get("scope")) for e in _all_events(repo)]
    assert ("rob", "consensus") in kinds and ("reconcile", None) in kinds
    assert all(i.resolved for i in rob.compare(repo, S1))


def _all_events(repo) -> list[dict[str, Any]]:  # type: ignore[no-untyped-def]
    return _events(repo) + read_events(repo.path("events", "reconcile", "ethan.ndjson"))


def test_another_judgement_can_be_entered_for_the_consensus(tmp_path: Path) -> None:
    repo = _dual(tmp_path)
    event = rob.resolve(
        repo, study=S1, reconciler="ethan", domain="D1", choice="other",
        other_judgement="high", rationale="Both missed the allocation problem.",
    )  # fmt: skip
    assert event["body"]["chosen"] == "high" and event["body"]["from"] == "other"


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"choice": "sam", "rationale": " "}, "rationale"),
        ({"choice": "agreement", "rationale": "x"}, "disagreement"),
        ({"choice": "nobody", "rationale": "x"}, "choose one of"),
        ({"choice": "other", "rationale": "x"}, "needs a judgement"),
        ({"choice": "other", "rationale": "x", "other_judgement": "meh"}, "must be one of"),
        ({"choice": "sam", "rationale": "x", "domain": "D9"}, "nothing to reconcile"),
    ],
)
def test_bad_reconciliations_are_refused(
    tmp_path: Path, kwargs: dict[str, str], message: str
) -> None:
    repo = _dual(tmp_path)
    kwargs = {"domain": "D1", **kwargs}
    with pytest.raises(rob.RobError, match=message):
        rob.resolve(repo, study=S1, reconciler="ethan", **kwargs)
    assert not rob.consensus_path(repo, S1).exists()


def test_reconciling_needs_two_reviewers(tmp_path: Path) -> None:
    repo = _ready(tmp_path, mode="dual")
    rob.record_judgement(repo, study=S1, handle="ethan", domain="D1", judgement="low")
    with pytest.raises(rob.RobError, match="at least two"):
        rob.compare(repo, S1)
    assert rob.reviewer_handles(_review(tmp_path / "other"), S1) == []


# --- strata verify, filters ------------------------------------------------------------------


def _codes(repo) -> dict[str, list[str]]:  # type: ignore[no-untyped-def]
    from strata.core.verify import verify_repository

    found: dict[str, list[str]] = {}
    for issue in verify_repository(repo).issues:
        if issue.severity == "error":
            found.setdefault(issue.code, []).append(issue.message)
    return found


def test_verify_accepts_well_formed_assessments(tmp_path: Path) -> None:
    repo = _ready(tmp_path)
    _answer_d1(repo)
    rob.record_judgement(repo, study=S1, handle="ethan", domain="D1", judgement="low")
    assert _codes(repo) == {}


def test_verify_reports_an_instrument_that_does_not_validate(tmp_path: Path) -> None:
    repo = _ready(tmp_path)
    repo.path("rob", "instrument.yaml").write_text("instrument: broken\n", encoding="utf-8")
    assert "E_SCHEMA" in _codes(repo)


def test_verify_reports_invalid_assessments_and_keeps_orphans(tmp_path: Path) -> None:
    repo = _ready(tmp_path)
    rob.record_judgement(repo, study=S1, handle="ethan", domain="D1", judgement="low")
    path = rob.consensus_path(repo, S1)
    assessment = rob.read_assessment(path)
    assert assessment is not None
    assessment["domains"]["D1"].update(judgement="fine", suggested="high")
    assessment["overall"] = {"judgement": "terrible"}
    path.write_text(dump_yaml_str(assessment), encoding="utf-8")
    messages = _codes(repo)["E_SCHEMA"]
    assert any("'fine'" in m for m in messages) and any("overall" in m for m in messages)

    orphan = rob.consensus_path(repo, "std_" + "9" * 16)
    orphan.write_text(dump_yaml_str({"study": "std_" + "9" * 16, "domains": {}}), encoding="utf-8")
    (rob.consensus_path(repo, S2)).write_text("- not\n- a mapping\n", encoding="utf-8")
    found = _codes(repo)
    assert any("not an included study" in m for m in found["E_ORPHAN_EXTRACTION"])
    assert any("not a mapping" in m for m in found["E_SCHEMA"]) and orphan.exists()


def test_filters_see_the_studies_risk_of_bias(tmp_path: Path) -> None:
    """openspec scenario: `rob_overall == 'low'` includes only low-risk studies."""
    from strata.core import filters
    from strata.core.ids import record_id_for_report
    from strata.core.records import record_field_resolver
    from tests.unit._m3 import rpt

    repo = _ready(tmp_path, studies=3)
    _judge_all(repo, {d: "low" for d in ("D1", "D2", "D3", "D4", "D5")}, S1)
    rob.record_judgement(repo, study=S1, handle="ethan", domain="overall", judgement="low")
    _judge_all(repo, {"D1": "high"}, S2)
    by_record = rob.moderators_by_record(repo)
    assert set(by_record) == {record_id_for_report(rpt(1)), record_id_for_report(rpt(2))}

    def keep(expression: str, n: int) -> bool:
        fields = by_record.get(record_id_for_report(rpt(n)), {})
        resolver = record_field_resolver({"id": "x"}, study_fields=fields)
        return filters.matches_filter(expression, resolver)

    assert [keep("rob_overall == 'low'", n) for n in (1, 2, 3)] == [True, False, False]
    assert [keep("rob.D1 == 'high'", n) for n in (1, 2, 3)] == [False, True, False]
    assert [keep("rob_overall != 'low'", n) for n in (1, 2, 3)] == [False, True, True]
    assert rob.moderators_by_record(_review(tmp_path / "none")) == {}
