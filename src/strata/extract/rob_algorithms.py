"""The RoB 2 algorithms: signalling-question answers -> a suggested domain judgement.

Implements openspec:risk-of-bias#algorithmic-suggestion-with-recorded-override. Pure: answers in,
a suggestion out. A suggestion is only ever a *proposal* the reviewer accepts or overrides with a
recorded justification; it is never written as a judgement on its own.

Each function follows the decision flow of the RoB 2 domain algorithms (parallel-group trials):
it reads the answers in the order the flow needs them, so a question the flow never reaches is
never required. If a needed answer is missing, `suggest` returns `None` and `needed` names it.

Provenance, stated plainly: these rules were implemented from two independent open-source
transcriptions of the Cochrane algorithms (the `robbR` R package and the RoB 2 workbench by
aashnapandyapsych), which agree on all 82,125 answer combinations of Domains 1-5 (the effect of
assignment). The primary Cochrane tables could not be fetched when this was written, so the test
suite pins these results (`tests/unit/test_rob_algorithms.py`) and the document
`docs/rob-instruments.md` lists the rules worth checking against the official guidance before
a release.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping

LOW = "low"
SOME = "some-concerns"
HIGH = "high"
_SEVERITY = (LOW, SOME, HIGH)
ANSWERS = ("Y", "PY", "PN", "N", "NI")
ANSWERS_WITH_NA = ("NA", *ANSWERS)


class Incomplete(Exception):
    """The flow needs an answer that has not been given (`question` names it)."""

    def __init__(self, question: str) -> None:
        self.question = question
        super().__init__(question)


class _Answers:
    def __init__(self, answers: Mapping[str, str | None]) -> None:
        self._answers = answers

    def __getitem__(self, question: str) -> str:
        value = self._answers.get(question)
        if not value:
            raise Incomplete(question)
        return value

    def optional(self, question: str) -> str | None:
        return self._answers.get(question) or None


def _yes(answer: str | None) -> bool:
    return answer in ("Y", "PY")


def _no(answer: str | None) -> bool:
    return answer in ("N", "PN")


def worst(*judgements: str) -> str:
    """The most severe judgement (low < some concerns < high)."""
    return max(judgements, key=_SEVERITY.index)


def _d1(a: _Answers) -> str:
    """Randomisation process."""
    concealed = a["1.2"]
    if _no(concealed):
        return HIGH
    if concealed == "NI":
        return HIGH if _yes(a["1.3"]) else SOME
    if _no(a["1.1"]):
        return SOME
    return SOME if _yes(a["1.3"]) else LOW


def _d2_assignment(a: _Answers) -> str:
    """Deviations from intended interventions, effect of assignment (intention to treat)."""
    if _no(a["2.1"]) and _no(a["2.2"]) or _no(a["2.3"]):
        part_one = LOW
    elif a["2.3"] == "NI" or _no(a["2.4"]):
        part_one = SOME
    else:
        part_one = SOME if _yes(a["2.5"]) else HIGH
    part_two = LOW if _yes(a["2.6"]) else SOME if _no(a["2.7"]) else HIGH
    return worst(part_one, part_two)


def _d2_adhering(a: _Answers) -> str:
    """Deviations from intended interventions, effect of adhering to intervention."""
    aware = not (_no(a["2.1"]) and _no(a["2.2"]))
    if aware and not (_yes(a["2.3"]) or a["2.3"] == "NA"):
        return SOME if _yes(a["2.6"]) else HIGH
    q24, q25 = a["2.4"], a["2.5"]
    if (_no(q24) or q24 == "NA") and (_no(q25) or q25 == "NA"):
        return LOW
    return SOME if _yes(a["2.6"]) else HIGH


def _d3(a: _Answers) -> str:
    """Missing outcome data."""
    if _yes(a["3.1"]) or _yes(a["3.2"]) or _no(a["3.3"]):
        return LOW
    return SOME if _no(a["3.4"]) else HIGH


def _d4(a: _Answers) -> str:
    """Measurement of the outcome."""
    if _yes(a["4.1"]) or _yes(a["4.2"]):
        return HIGH
    base = SOME if a["4.2"] == "NI" else LOW
    if _no(a["4.3"]) or _no(a["4.4"]):
        return base
    return SOME if _no(a["4.5"]) else HIGH


def _d5(a: _Answers) -> str:
    """Selection of the reported result."""
    if _yes(a["5.2"]) or _yes(a["5.3"]):
        return HIGH
    if _no(a["5.2"]) and _no(a["5.3"]):
        return LOW if _yes(a["5.1"]) else SOME
    return SOME


ALGORITHMS: dict[str, Callable[[_Answers], str]] = {
    "rob2-d1": _d1,
    "rob2-d2-assignment": _d2_assignment,
    "rob2-d2-adhering": _d2_adhering,
    "rob2-d3": _d3,
    "rob2-d4": _d4,
    "rob2-d5": _d5,
}


def suggest(algorithm: str, answers: Mapping[str, str | None]) -> str | None:
    """The suggested judgement for one domain, or `None` while a needed answer is missing."""
    try:
        return ALGORITHMS[algorithm](_Answers(answers))
    except Incomplete:
        return None


def needed(algorithm: str, answers: Mapping[str, str | None]) -> str | None:
    """The next signalling question the flow needs an answer to, or `None` when it is decided."""
    try:
        ALGORITHMS[algorithm](_Answers(answers))
    except Incomplete as exc:
        return exc.question
    return None
