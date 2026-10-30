# Proposal: Open, attributed AI participation, with MCP write tools (M6)

## Why

People are already using AI assistants on systematic reviews, and a tool that offers them no honest way to
do it does not stop them: it only guarantees they do it outside the record, paste the output in, and
commit it as their own. `strata`'s whole point is that every decision stays legible, including the ones
you would rather have quietly rewritten. AI help is the largest remaining place where that promise fails
silently.

`strata` is not AI-first and this change does not make it so. It makes `strata` **AI-open**: a review's
reviewers decide whether, where and how much AI may take part, and wherever it does, the repository says
so, names the model and the person who invoked it, keeps its work apart from the humans', and carries that
into the Methods text. The MCP server is the natural doorway, but today it is read-only by rule.

Roadmap: not on the roadmap today. Proposed for M6 ("Hardening and adoption"); it does not gate `1.0.0`.
Overview non-goal N5 ("Not an AI screening product (in v1)") is reworded, not removed: `strata` still ships
no model and no recommender, and a `Prioritiser` still only reorders.

## What Changes

- **A per-review AI policy**, committed in `strata.toml` and off by default. Each kind of work (screening,
  extraction, risk of bias, full-text retrieval, study grouping, deduplication, record corrections,
  searches and imports, criteria, adjudication, analysis and reports) is `off`, `suggest` or `count`.
  Changing it is a human-only, attributed, rationale-bearing commit.
- **Agents are actors in their own right.** An actor gains `kind = "agent"` and a `model`; a lead registers
  the models the review accepts, as they register people. An agent's events are in its own files, never
  under a person's handle, and an agent whose self-reported model is not registered is refused.
- **Every agent event says who, what and through what.** A new optional envelope key records the
  self-reported model, the MCP client's name and version from the handshake, and the human who started
  the server. The model name is the agent's own claim and is recorded as such: `strata` cannot verify it.
  Commits are authored as the agent and committed by the person.
- **MCP write tools** for every operation the CLI can write, except those that confer standing (below),
  each requiring the agent's `model` and a rationale. `strata mcp --as <handle>` names the invoking human.
  Read tools grow to match (criteria, queues, extraction and risk-of-bias forms), and all reads keep the
  review's blinding.
- **Suggestions.** In `suggest` mode a write is validated exactly as a real one but recorded as a
  `suggestion` that touches no state. A person adopts it (the operation then runs as that person, linked
  to the suggestion) or rejects it. A person adopting is a person deciding, and the record says whose idea
  it was.
- **Counting.** In `count` mode an agent's event takes effect directly, as the agent: it fills a reviewer
  slot only when assigned, is reported apart in agreement statistics, and never counts as a person.
  Revoking an agent marks its counted decisions stale through the existing re-screening queue.
- **Disclosure that cannot go stale.** Generated Methods text and PRISMA 2020 checklist items 8, 9 and 11
  ("details of automation tools") are computed from the record. Today they assert that no automation
  tools were used, which becomes false the moment an agent participates. `strata ai report` gives the
  ledger; `strata audit --ai` samples agent decisions for human verification.
- **Not delegable to an agent**, whatever the policy: changing the policy, registering or deactivating
  actors, assigning reviewers (assignment decides who counts), `config`, `init`, `clone`, `doctor`,
  `sync` and the merge commands. An agent must never be able to grant itself standing or publish a review.
- **A schema bump to version 2, entered only by enabling AI.** Repositories that never enable it stay at 1
  and behave as today. `strata migrate`, required by `openspec:repository-format#format-versioning` but
  never built, arrives with it.

### Conflicts with current rules, and how each is resolved

| Where | What it says | Resolution |
|---|---|---|
| `mcp-server` requirement "No autonomous decisions" | A write tool may only produce a proposal | Replaced. Proposals are one policy mode (`suggest`); `count` lets a review accept direct agent work, attributed. |
| `mcp-server` design "Why read-only" | An unsupervised agent undermines provenance | Rewritten: the risk was *unattributed* agent work, and attribution is what this change adds. |
| `mcp-server/server.py` docstring and `_INSTRUCTIONS` | Say writes are human-only | Updated to describe the policy. |
| `docs/overview.md` N5 | Not an AI screening product in v1 | Reworded to "ships no model; open to the ones reviewers choose". |
| `architecture` "Plugin boundaries" | A `Prioritiser` only reorders | **Unchanged.** |
| `openspec/config.yaml` proposal rule | Never propose an MCP path that records a decision without a human | **This change reverses it at the project owner's direction.** The compromise kept: no write without a named invoking human, a registered model, a policy that is off by default, and the human-only list above. A task rewrites the rule. |

### Owner decisions recorded

Per-review policy rather than one fixed mode; write tools for everything the CLI can write apart from
standing-conferring operations; agents as their own actors rather than annotations on a person's.

## Capabilities

### New Capabilities

- `ai-participation`: the policy, agent actors and registration, attribution, what counts and what does
  not, the operations an agent can never perform, revocation, and disclosure.
- `ai-suggestions`: recording, listing, adopting and rejecting suggestions, and how they interact with
  blinding.

### Modified Capabilities

- `mcp-server`: write tools, the invoking human, blinded reads, and the removal of "no autonomous
  decisions".
- `event-log`: the optional `agent` envelope key; the suggestion event types.
- `data-schemas`: agent actors and the `[ai]` tables.
- `repository-format`: schema version 2, entered through `strata ai enable`; `strata migrate`.
- `cli`: `strata ai`, `strata suggestions`, `strata migrate`, `strata mcp --as`, `strata audit --ai`.
- `web-ui`: a suggestions screen and visible labelling of agent work.

## Impact

- Changes **canonical serialisation** (a new optional envelope key with a defined position) and the
  **fold** (agent-authored events, suggestions); identity, normalisation and the staleness rules are not
  changed. **Schema version 1 to 2 is required**, and only for repositories that enable AI.
- New: `core/agents.py` (policy and identity checks), `protocol/suggestions.py`, `core/migrate.py`, the
  shared write operations the MCP tools call (the same ones `add-web-ui-write-surfaces` introduces; the
  two changes should land in the order stated in the design), the `strata ai`, `suggestions` and `migrate`
  commands, and report sections.
- Changed: `mcpserver/server.py`, `core/events.py` and `event.schema.json`, `core/fold.py`
  (agent opinions count only when assigned), `protocol/irr.py`, `report/sections.py` and
  `report/checklist.py` (both currently hard-code "no automation tools"), `core/manifest.py`,
  `core/repo.py` (version range), `gitio`/commit construction (author).
- No new runtime dependency and no model, key or network call in `strata`: the agent and its provider
  are the user's own, on the other end of MCP.
- Wiki: a new "Using AI in a review" page, plus the pages for MCP, reporting, and working with others.
- Documentation to correct: `docs/overview.md` (N5), `docs/roadmap.md`, the `mcp-server` design, and the
  `openspec/config.yaml` rule.
- Related changes: `add-web-ui-write-surfaces` (shared operations, the suggestions screen's conventions),
  `add-prisma-reporting` (still open; its Methods and checklist code is amended here),
  `add-hosted-team-deployment` (remote MCP gets the same policy; the invoking human is the signed-in
  user).
