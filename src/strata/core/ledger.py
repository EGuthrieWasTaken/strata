"""The AI ledger: what each agent did in a review, computed from the record.

Implements openspec:ai-participation#the-ai-ledger-and-audit. Every statement the review makes about
AI participation (the Methods text, PRISMA checklist items 8, 9 and 11, `strata ai report`,
`strata status`, `strata audit --ai`) reads this one function, so none of them can say something the
record does not support, and none can go stale: there is nothing to type and nothing to remember to
update (openspec:ai-participation#disclosure-in-generated-text).

The ledger is built from three things the log already holds: the events that carry an `agent`
key (what took effect, as the agent's), the suggestions and what became of them, and the commits an
agent authored for work that writes files rather than events (an analysis, a diagram, a recorded
search). It never reads a model name from anywhere but the record, and the model name is the agent's
own claim, which the text built from it says.

"Changed by a person" is deliberately narrow and exact: an agent's screening opinion that a person's
adjudication superseded, and an agent's retrieval outcome, record correction or criteria change that
a person later set to a different value for the same target. Other kinds are not counted as changed
rather than guessed at.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from strata.core import agents as agents_mod
from strata.core.events import iter_event_files, read_events
from strata.core.fold import sort_events
from strata.core.repo import Repo
from strata.protocol import screening as screening_mod
from strata.protocol import suggestions as sugg

#: The kind of work (policy) an event type belongs to.
KIND_OF_EVENT: dict[str, str] = {
    "screen": "screening",
    "adjudicate": "adjudication",
    "extract": "extraction",
    "reconcile": "extraction",
    "rob": "risk-of-bias",
    "retrieval": "retrieval",
    "study-group": "studies",
    "study-split": "studies",
    "record-amend": "records",
    "note": "records",
    "dedup-merge": "dedup",
    "dedup-distinct": "dedup",
    "dedup-unmerge": "dedup",
    "criteria-change": "criteria",
    "import": "search-import",
    "record-add": "search-import",
}

#: Agent work that writes files and no event: commit operation -> kind of work.
FILE_WORK: dict[str, str] = {
    "analyze": "analysis",
    "prisma": "analysis",
    "search-add": "search-import",
}

#: Kinds whose agent opinions fill a reviewer slot when the agent is assigned.
OPINION_KINDS = agents_mod.OPINION_KINDS


@dataclass(frozen=True)
class KindLedger:
    """One agent's work of one kind."""

    suggested: int = 0
    adopted: int = 0
    rejected: int = 0
    superseded: int = 0
    pending: int = 0
    #: Events that took effect as the agent's own (the `agent` key is on them).
    counted: int = 0
    #: Of those, screening opinions from a record the agent was assigned to (they filled a reviewer
    #: slot) and, for the other opinion kinds, every one of them.
    reviewing: int = 0
    #: Of `counted`, those a person later changed (see the module docstring).
    changed_by_people: int = 0
    #: Commits the agent authored for work that writes files rather than events.
    file_work: int = 0

    @property
    def active(self) -> bool:
        return bool(self.suggested or self.counted or self.file_work)


@dataclass(frozen=True)
class AgentLedger:
    actor: str
    model: str
    #: The agent's role in the manifest; `inactive` once revoked.
    role: str
    kinds: dict[str, KindLedger] = field(default_factory=dict)
    invokers: tuple[str, ...] = ()
    first_active: str | None = None
    last_active: str | None = None
    #: Every client name and version the agent connected through, as it gave them.
    clients: tuple[str, ...] = ()

    @property
    def active_kinds(self) -> dict[str, KindLedger]:
        return {kind: ledger for kind, ledger in self.kinds.items() if ledger.active}

    @property
    def revoked(self) -> bool:
        return self.role == "inactive"


@dataclass(frozen=True)
class Ledger:
    agents: tuple[AgentLedger, ...] = ()

    @property
    def used(self) -> bool:
        """Whether any agent contributed anything: an event, a suggestion or a piece of work."""
        return any(agent.active_kinds for agent in self.agents)

    def active_agents(self) -> list[AgentLedger]:
        return [a for a in self.agents if a.active_kinds]

    @property
    def counted_events(self) -> int:
        return sum(k.counted for a in self.agents for k in a.kinds.values())

    @property
    def suggestions(self) -> int:
        return sum(k.suggested for a in self.agents for k in a.kinds.values())

    def for_kinds(self, kinds: Iterable[str]) -> list[tuple[AgentLedger, dict[str, KindLedger]]]:
        """Each agent that did anything in `kinds`, with just those kinds."""
        wanted = set(kinds)
        found = []
        for agent in self.agents:
            chosen = {k: v for k, v in agent.active_kinds.items() if k in wanted}
            if chosen:
                found.append((agent, chosen))
        return found


def _date(ts: str) -> str:
    return ts[:10]


def _all_events(repo: Repo) -> list[dict[str, Any]]:
    return sort_events(e for path in iter_event_files(repo.root) for e in read_events(path))


def _changed_by_people(
    events: list[dict[str, Any]], agent_events: list[dict[str, Any]]
) -> set[str]:
    """Ids of agent events a person later changed, by the rules in the module docstring."""
    changed: set[str] = set()
    superseded = {
        str(i) for e in events if e["ev"] == "adjudicate" for i in e["body"].get("supersedes", [])
    }
    keyed: dict[tuple[str, ...], list[dict[str, Any]]] = defaultdict(list)

    def key_of(event: dict[str, Any]) -> tuple[str, ...] | None:
        body, ev = event["body"], event["ev"]
        if ev == "retrieval":
            return ("retrieval", body["report"])
        if ev == "record-amend":
            return ("record-amend", body["record"], body["field"])
        if ev == "criteria-change":
            return ("criteria", *sorted(str(d["id"]) for d in body.get("deltas", [])))
        return None

    for event in events:
        key = key_of(event)
        if key is not None:
            keyed[key].append(event)
    for event in agent_events:
        if event["id"] in superseded:
            changed.add(event["id"])
            continue
        key = key_of(event)
        if key is None:
            continue
        later_by_person = [
            other
            for other in keyed[key]
            if "agent" not in other and (other["ts"], other["id"]) > (event["ts"], event["id"])
        ]
        if later_by_person:
            changed.add(event["id"])
    return changed


def _file_work(repo: Repo) -> dict[tuple[str, str], int]:
    """Commits an agent authored for file-only work: (agent, kind) -> count. Needs git."""
    from strata.core import logcmd

    counts: dict[tuple[str, str], int] = defaultdict(int)
    try:
        commits = logcmd.domain_log(repo)
    except Exception:  # noqa: BLE001 - a repository without usable history has no file work to count
        return counts
    for commit in commits:
        agent = commit.trailers.get("Agent")
        kind = FILE_WORK.get(commit.trailers.get("Op", ""))
        if agent and kind:
            counts[(agent, kind)] += 1
    return counts


def compute_ledger(repo: Repo) -> Ledger:
    """What every registered agent did, from the event log, the suggestions and the commits."""
    registered = {str(a["handle"]): a for a in agents_mod.agent_actors(repo)}
    if not registered:
        return Ledger()
    events = _all_events(repo)
    agent_events = [e for e in events if e.get("agent") and e["actor"] in registered]
    changed = _changed_by_people(events, agent_events)
    assignments = screening_mod.all_assign_events(repo)

    kinds: dict[str, dict[str, dict[str, int]]] = defaultdict(
        lambda: defaultdict(lambda: defaultdict(int))
    )
    invokers: dict[str, set[str]] = defaultdict(set)
    clients: dict[str, set[str]] = defaultdict(set)
    stamps: dict[str, list[str]] = defaultdict(list)

    def note_identity(actor: str, agent: dict[str, Any], ts: str) -> None:
        invokers[actor].add(str(agent.get("invoked_by", "")))
        client = agent.get("client") or {}
        if client.get("name"):
            clients[actor].add(f"{client['name']} {client.get('version', '')}".strip())
        stamps[actor].append(_date(ts))

    for event in agent_events:
        kind = KIND_OF_EVENT.get(event["ev"])
        if kind is None:
            continue  # suggestions and their resolutions are counted below
        actor = event["actor"]
        entry = kinds[actor][kind]
        entry["counted"] += 1
        if event["id"] in changed:
            entry["changed_by_people"] += 1
        if event["ev"] == "screen":
            body = event["body"]
            assigned = screening_mod.assigned_actors(
                repo, body["stage"], body["record"], assign_events=assignments
            )
            if actor in assigned:
                entry["reviewing"] += 1
        elif kind in OPINION_KINDS:
            entry["reviewing"] += 1
        note_identity(actor, event["agent"], event["ts"])

    for suggestion in sugg.suggestions(repo):
        if suggestion.actor not in registered:
            continue
        entry = kinds[suggestion.actor][suggestion.kind or "unknown"]
        entry["suggested"] += 1
        entry[suggestion.status] += 1
        note_identity(suggestion.actor, suggestion.agent, suggestion.ts)

    for (actor, kind), count in _file_work(repo).items():
        if actor in registered:
            kinds[actor][kind]["file_work"] += count

    agents = []
    for actor, record in registered.items():
        per_kind = {
            kind: KindLedger(
                suggested=n["suggested"],
                adopted=n["adopted"],
                rejected=n["rejected"],
                superseded=n["superseded"],
                pending=n["pending"],
                counted=n["counted"],
                reviewing=n["reviewing"],
                changed_by_people=n["changed_by_people"],
                file_work=n["file_work"],
            )
            for kind, n in sorted(kinds[actor].items())
        }
        days = sorted(stamps[actor])
        agents.append(
            AgentLedger(
                actor=actor,
                model=str(record.get("model", "")),
                role=str(record.get("role", "")),
                kinds=per_kind,
                invokers=tuple(sorted(i for i in invokers[actor] if i)),
                first_active=days[0] if days else None,
                last_active=days[-1] if days else None,
                clients=tuple(sorted(clients[actor])),
            )
        )
    return Ledger(agents=tuple(agents))
