"""Disclosure of AI participation, written from the ledger: openspec:ai-participation.

The Methods text and PRISMA 2020 checklist items 8, 9 and 11 ask for "details of automation tools
used". Those used to be fixed sentences saying none were; they become false the day an AI agent
takes part. Everything here is computed from `strata.core.ledger`, so what the text says is exactly
what the record holds, and a review that used no AI gets the wording it always had (the callers
pass through unchanged when `Ledger.used` is false).

Every sentence says the model's name is its own report, which `strata` cannot verify, and that a
person reviewed every suggestion before it could take effect.
"""

from __future__ import annotations

from strata.core.ledger import AgentLedger, KindLedger, Ledger

#: The areas the report describes, and the kinds of work that belong to each.
SELECTION = (
    "screening",
    "adjudication",
    "dedup",
    "retrieval",
    "studies",
    "records",
    "criteria",
    "search-import",
)
COLLECTION = ("extraction",)
RISK_OF_BIAS = ("risk-of-bias",)
SYNTHESIS = ("analysis",)

_NOUN = {
    "screening": "screening decision",
    "adjudication": "adjudication",
    "extraction": "data extraction entry",
    "risk-of-bias": "risk-of-bias judgement",
    "retrieval": "retrieval outcome",
    "studies": "study grouping",
    "dedup": "deduplication decision",
    "records": "record correction or note",
    "criteria": "criteria change",
    "search-import": "search or import",
    "analysis": "analysis run or report",
}

_NUMBERS = {1: "one", 2: "two", 3: "three", 4: "four", 5: "five"}


def count_word(n: int) -> str:
    """`one`, `two` ... for small counts, else the digits."""
    return _NUMBERS.get(n, str(n))


def plural(n: int, noun: str) -> str:
    return f"{n:,} {noun}" if n == 1 else f"{n:,} {noun}s"


def join(items: list[str]) -> str:
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + " and " + items[-1]


def model_phrase(agent: AgentLedger) -> str:
    """The AI model, as the record names it, with the caveat that the name is its own claim."""
    return (
        f"the AI model {agent.model} (registered as {agent.actor}; the model name is the model's "
        "own report and has not been verified)"
    )


def _kind_clause(kind: str, k: KindLedger) -> str:
    noun = _NOUN.get(kind, kind)
    parts = []
    if k.suggested:
        outcome = f"{k.adopted:,} adopted and {k.rejected:,} rejected by a person"
        left = k.pending + k.superseded
        if left:
            outcome += f", {left:,} not acted on"
        parts.append(
            f"in suggest mode made {plural(k.suggested, kind + ' suggestion')}, of which "
            f"{outcome}; a person reviewed every suggestion before any took effect"
        )
    if k.counted or k.file_work:
        took = (
            f"in count mode {plural(k.counted or k.file_work, noun)} took effect as the "
            "model's own work"
        )
        if k.reviewing:
            took += (
                f", {k.reviewing:,} of them as a reviewer whose opinion counted toward a "
                "record's resolution"
            )
        if k.changed_by_people:
            took += f", and {k.changed_by_people:,} were later changed by a person"
        parts.append(took)
    return f"{kind}: " + "; ".join(parts)


def paragraph(ledger: Ledger, kinds: tuple[str, ...]) -> str:
    """What the AI did in these kinds of work, or `""` when it did nothing there."""
    sentences = []
    for agent, chosen in ledger.for_kinds(kinds):
        who = join(sorted({*agent.invokers})) or "an unnamed person"
        clauses = "; ".join(_kind_clause(kind, k) for kind, k in chosen.items())
        phrase = model_phrase(agent)
        sentences.append(f"{phrase[0].upper() + phrase[1:]}, run by {who}, took part ({clauses}).")
    return " ".join(sentences)


def area_text(ledger: Ledger, kinds: tuple[str, ...], area: str) -> str:
    """The disclosure for one area of the report; `""` for a review that used no AI at all.

    When AI took part elsewhere but not here, says so for this area, so that the reader is told
    rather than left to infer it.
    """
    if not ledger.used:
        return ""
    text = paragraph(ledger, kinds)
    return text or f"No AI model took part in {area}."


def reviewing_agents(ledger: Ledger, kind: str) -> list[AgentLedger]:
    """Agents whose opinions counted as a reviewer's in `kind`."""
    return [a for a in ledger.agents if a.kinds.get(kind, KindLedger()).reviewing]


def reviewer_clause(people: list[str], ledger: Ledger, kind: str = "screening") -> str:
    """`two people (a, b) and one AI model (m)`: people and models counted apart, model named."""
    agents = reviewing_agents(ledger, kind)
    names = join(people)
    if not agents:
        return ""
    models = join([a.model for a in agents])
    return (
        f"{count_word(len(people))} {'person' if len(people) == 1 else 'people'} ({names}) and "
        f"{count_word(len(agents))} AI model{'s' if len(agents) != 1 else ''} ({models})"
    )


def automation_sentence(ledger: Ledger, kinds: tuple[str, ...]) -> str | None:
    """What to say about automation instead of the fixed "none was used", or `None` to keep it.

    The fixed sentence stays whenever no AI took part in these kinds of work.
    """
    if not ledger.for_kinds(kinds):
        return None
    return (
        "Automation: strata's deduplication, and the AI model(s) described in the paragraph on AI "
        "participation. No other automation tools are recorded"
    )
