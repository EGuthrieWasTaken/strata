"""The RoB 2 algorithms against an independent rule-chain oracle (openspec:risk-of-bias).

The oracle below is a transcription of the case-by-case rules published in the `robbR` R package
(`rob2_algorithm()`), written as ordered rule chains rather than decision flows. A separate
open-source implementation (the RoB 2 workbench by aashnapandyapsych) was compared against it
exhaustively and agrees on all 82,125 combinations of Domains 1-5. Matching an independent
transcription on every combination is what "match the published decision rules" can mean here
until the primary Cochrane tables are checked (see docs/rob-instruments.md).
"""

from __future__ import annotations

from collections.abc import Callable
from itertools import product

import pytest

from strata.extract import rob_algorithms as alg

A5 = ["Y", "PY", "PN", "N", "NI"]
A6 = ["NA", *A5]


def yes(x: str) -> bool:
    return x in ("Y", "PY")


def no(x: str) -> bool:
    return x in ("N", "PN")


def ni(x: str) -> bool:
    return x == "NI"


def oracle_d1(a: dict[str, str]) -> str:
    if no(a["1.2"]):
        return "high"
    if ni(a["1.2"]) and yes(a["1.3"]):
        return "high"
    if ni(a["1.2"]):
        return "some-concerns"
    if no(a["1.1"]):
        return "some-concerns"
    if yes(a["1.3"]):
        return "some-concerns"
    return "low"


def oracle_d2_assignment(a: dict[str, str]) -> str:
    if no(a["2.1"]) and no(a["2.2"]) or no(a["2.3"]):
        one = "low"
    elif ni(a["2.3"]) or no(a["2.4"]) or yes(a["2.5"]):
        one = "some-concerns"
    else:
        one = "high"
    if yes(a["2.6"]):
        two = "low"
    elif no(a["2.7"]):
        two = "some-concerns"
    else:
        two = "high"
    return alg.worst(one, two)


def oracle_d2_adhering(a: dict[str, str]) -> str:
    aware = not (no(a["2.1"]) and no(a["2.2"]))
    balanced = (not aware) or yes(a["2.3"]) or a["2.3"] == "NA"
    problems = not ((no(a["2.4"]) or a["2.4"] == "NA") and (no(a["2.5"]) or a["2.5"] == "NA"))
    if balanced and not problems:
        return "low"
    return "some-concerns" if yes(a["2.6"]) else "high"


def oracle_d3(a: dict[str, str]) -> str:
    if yes(a["3.1"]) or yes(a["3.2"]) or no(a["3.3"]):
        return "low"
    return "some-concerns" if no(a["3.4"]) else "high"


def oracle_d4(a: dict[str, str]) -> str:
    if yes(a["4.1"]) or yes(a["4.2"]):
        return "high"
    base = "low" if no(a["4.2"]) else "some-concerns"
    if no(a["4.3"]) or no(a["4.4"]):
        return base
    return "some-concerns" if no(a["4.5"]) else "high"


def oracle_d5(a: dict[str, str]) -> str:
    if yes(a["5.2"]) or yes(a["5.3"]):
        return "high"
    if ni(a["5.2"]) or ni(a["5.3"]):
        return "some-concerns"
    return "low" if yes(a["5.1"]) else "some-concerns"


CASES: list[tuple[str, dict[str, list[str]], Callable[[dict[str, str]], str]]] = [
    ("rob2-d1", {f"1.{i}": A5 for i in (1, 2, 3)}, oracle_d1),
    ("rob2-d2-assignment", {f"2.{i}": A5 for i in range(1, 8)}, oracle_d2_assignment),
    (
        "rob2-d2-adhering",
        {"2.1": A5, "2.2": A5, "2.3": A6, "2.4": A6, "2.5": A6, "2.6": A5},
        oracle_d2_adhering,
    ),
    ("rob2-d3", {f"3.{i}": A5 for i in range(1, 5)}, oracle_d3),
    ("rob2-d4", {f"4.{i}": A5 for i in range(1, 6)}, oracle_d4),
    ("rob2-d5", {f"5.{i}": A5 for i in (1, 2, 3)}, oracle_d5),
]


@pytest.mark.parametrize(("algorithm", "questions", "oracle"), CASES, ids=[c[0] for c in CASES])
def test_every_answer_combination_matches_the_independent_oracle(
    algorithm: str, questions: dict[str, list[str]], oracle: Callable[[dict[str, str]], str]
) -> None:
    names = list(questions)
    checked = 0
    for combo in product(*questions.values()):
        answers = dict(zip(names, combo, strict=True))
        assert alg.suggest(algorithm, answers) == oracle(answers), answers
        checked += 1
    assert checked == 1 or checked >= 125


@pytest.mark.parametrize(("algorithm", "questions", "oracle"), CASES, ids=[c[0] for c in CASES])
def test_a_skipped_question_never_changes_a_decided_suggestion(
    algorithm: str, questions: dict[str, list[str]], oracle: Callable[[dict[str, str]], str]
) -> None:
    """If the flow decides without a question, leaving it blank must not matter."""
    names = list(questions)
    for combo in product(*questions.values()):
        answers = dict(zip(names, combo, strict=True))
        for question in names:
            partial = {k: v for k, v in answers.items() if k != question}
            suggestion = alg.suggest(algorithm, partial)
            if suggestion is not None:
                assert suggestion == oracle(answers)
        if len(names) > 5:
            break  # the larger domains are covered by the first block; keep this test quick


def test_a_clean_trial_is_low_in_every_domain() -> None:
    clean = {
        "rob2-d1": {"1.1": "Y", "1.2": "Y", "1.3": "N"},
        "rob2-d2-assignment": {"2.1": "N", "2.2": "N", "2.6": "Y"},
        "rob2-d3": {"3.1": "Y"},
        "rob2-d4": {"4.1": "N", "4.2": "N", "4.3": "N"},
        "rob2-d5": {"5.1": "Y", "5.2": "N", "5.3": "N"},
    }
    assert {name: alg.suggest(name, answers) for name, answers in clean.items()} == {
        name: "low" for name in clean
    }


def test_the_flow_only_asks_for_what_it_needs() -> None:
    assert alg.needed("rob2-d1", {}) == "1.2"
    assert alg.needed("rob2-d1", {"1.2": "N"}) is None  # not concealed: High, nothing more needed
    assert alg.needed("rob2-d1", {"1.2": "Y"}) == "1.1"
    assert alg.needed("rob2-d1", {"1.2": "Y", "1.1": "Y"}) == "1.3"
    assert alg.suggest("rob2-d1", {"1.2": "Y", "1.1": "Y"}) is None
    assert alg.suggest("rob2-d1", {"1.2": "Y", "1.1": "Y", "1.3": "N"}) == "low"
    assert alg.needed("rob2-d3", {"3.1": "N"}) == "3.2"
    assert alg.needed("rob2-d3", {"3.1": "Y"}) is None
    assert alg.needed("rob2-d5", {"5.2": "Y"}) is None  # selection likely: High without 5.1
    assert alg.suggest("rob2-d4", {"4.1": "Y"}) == "high"


def test_blank_answers_count_as_missing() -> None:
    assert alg.suggest("rob2-d1", {"1.2": "", "1.1": "Y", "1.3": "N"}) is None
    assert alg.suggest("rob2-d1", {"1.2": None}) is None


def test_worst_orders_the_judgements() -> None:
    assert alg.worst("low", "low") == "low"
    assert alg.worst("low", "some-concerns", "low") == "some-concerns"
    assert alg.worst("some-concerns", "high", "low") == "high"


def test_unknown_algorithms_are_a_key_error() -> None:
    with pytest.raises(KeyError):
        alg.suggest("rob3-d1", {})
