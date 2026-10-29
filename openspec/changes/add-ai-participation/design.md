# Design

## Context

Motivation, the owner's decisions and the table of conflicting rules are in [proposal.md](proposal.md);
the requirements are in `specs/`. The facts that shape the design:

- **The MCP server is read-only by construction.** `mcpserver/server.py` is a thin `RepoTools` class with
  six read methods, and its docstring and `_INSTRUCTIONS` say writes are human-only. Nothing there knows
  who is calling.
- **Actors are people.** `strata.toml` holds `[[actors]]` with a role; events carry only an `actor`
  handle; event files are sharded per actor so two actors never append to one file. The event schema's
  envelope has `additionalProperties: false`, and its key order is part of the canonical serialisation
  and so of every `digest`.
- **The fold counts opinions by actor, not by assignment.** `openspec:event-log#resolving-opinions-to-a-record-state`
  says `opinions = latest event per assigned actor`, but `resolve_screening` reduces *every* actor's
  events and compares `len(opinions) < len(assigned)`. `record_screen_decision` does not check assignment
  either, and `import_decisions_tsv` can write for any actor. So today an unassigned actor's opinion can
  stand in for an assigned reviewer's. For people that is an edge case; for agents it would make an
  unassigned model a free second reviewer, so it must be closed.
- **Generated text asserts a negative.** `report/sections.py` writes "no records were removed by other
  automation tools" and `report/checklist.py` writes "no machine-learning prioritisation was used".
  Both are fixed strings, and both become false the day an agent takes part. `reviewers()` also lists
  every active actor by role, so an agent registered as a screener would read as a person.
- **There is no `strata migrate`.** The schema version is 1 and `CURRENT_SCHEMA_VERSION` is 1; the
  command `openspec:repository-format#format-versioning` requires has never been needed.
- **The write path is being unified.** `add-web-ui-write-surfaces` moves commit assembly out of
  `cli/main.py` into `core/operations.py`. Agent writes are a third caller of exactly those operations.
- **An agent with a shell is outside all of this.** An agent that can run `strata screen --by ada` in a
  terminal does what a person at that terminal could. No server-side design can stop it.

## Goals / Non-Goals

**Goals:**

- A review's reviewers decide whether, where and how far AI takes part, in a file that is part of the
  record and changes only by a person's attributed commit.
- Every AI contribution says which model and which person, is kept apart from people's work, and reaches
  the Methods text without anyone remembering to write it.
- An agent can never widen its own authority.
- Reviews that never enable AI see no behavioural change and no format change.

**Non-Goals:**

- No model, prompt, API key, network call or recommender inside `strata`. Agents are other people's
  software on the far end of MCP.
- No verification of an agent's identity or of its output's quality. The model name is a claim; the
  record says so.
- No policy on whether AI use is *acceptable*. That is the reviewers' call; `strata` makes the call
  visible and reportable.
- No change to `Prioritiser` (reorder-only) and no active-learning feature.
- No stopping an agent that drives the CLI directly (see Risks).
- Remote (HTTP) MCP: `add-hosted-team-deployment` gets the same policy, with the signed-in user as the
  invoker. Nothing here assumes stdio beyond how the invoker is named.

## Decisions

### D1. The policy is a committed file, per kind of work, with three modes and a default of off

`[ai]` and `[ai.policy]` in `strata.toml` hold it. Three modes cover the real range of reviewer
attitudes: `off`; `suggest` (an agent may propose, a person decides); `count` (an agent's work takes
effect, as the agent, and is reported as such). Eleven kinds of work are separate because reviews will not
treat them alike: screening suggestions are common practice, criteria edits by a model are not.
Changing the policy is `strata ai policy`, a normal commit with `Strata-Op: ai-policy`, so the history of
the policy is the history of the review's stance.

*Rejected:* one global on/off (too blunt: a review that accepts screening help may not accept
adjudication); a per-user setting (the other reviewers could not see or object to it); a hook that blocks
agent commits (invisible, and not part of the record).

### D2. Agents are registered actors, and the reported model must match

A lead registers each model with `strata actor add NAME --kind agent --model ID --role screener`. A write
call must carry the model the agent reports, and it is compared exactly with an active agent actor's
`model`. A mismatch is refused with instructions to the human. This is what makes "up to reviewers"
operational: a model nobody registered cannot write, and a provider silently moving `…-latest` to a new
model produces a different string and is refused rather than absorbed.

An agent actor cannot be a `lead`, and its events live in its own files, under its own handle, so
dual-screening independence by file layout (`openspec:screening`) extends to it.

*Rejected:* annotating a person's events with an `agent` block (the person's tally and the model's blur
unless every consumer filters; and it is the shape of "committing it as their own"); auto-registering any
model that reports itself (any string would pass); verifying the model by any means (no MCP mechanism
does it; claiming otherwise would be worse than saying nothing).

### D3. Attribution is an envelope key

```json
{"ev":"screen","id":"ev_01m62y4n2etk2j22640hhrn4z8","ts":"2026-11-02T09:14:07Z","actor":"claude-opus",
 "agent":{"model":"claude-opus-5-5","client":{"name":"claude-code","version":"2.1.3"},"invoked_by":"ada"},
 "seq":41,"body":{"stage":"title-abstract","record":"rec_0000000000000042","decision":"include"},
 "tool":"strata 0.4.0","prev":"sha256:0000000000000000000000000000000000000000000000000000000000000000",
 "digest":"sha256:1111111111111111111111111111111111111111111111111111111111111111"}
```

The key sits between `actor` and `seq` and is covered by the digest, so it cannot be edited out by hand
without `strata verify` noticing, as for any field. It is an envelope key, not a body field, so there is
exactly one place to look for every event type and the fold can tell agent events apart without knowing
the type. `client` comes from the MCP `initialize` handshake and is recorded as given; `invoked_by` comes
from `--as`.

*Rejected:* a body field on each event type (eleven places to forget, and inside the part of the event
that types define); commit trailers alone (they are not in the event log, so `strata why`, the fold and the
ledger could not use them, and a sync that rewrites commits would lose them).

### D4. Commits: authored by the agent, committed by the person

`gitio` commits with `--author "<agent name> (via <person>) <handle@agents.invalid>"` and leaves the
committer as the person's configured identity. `.invalid` is reserved and can never be delivered or matched
to a hosting account, so nothing is credited to a stranger or to the person. Trailers `Strata-Agent`,
`Strata-Invoked-By`, `Strata-Via: mcp` make `strata log` filters work. The person who started the server
still pushes and is still the committer: responsibility stays where it was, credit does not move.

*Rejected:* authoring as the person (the exact behaviour this change exists to avoid); committing as the
agent (nobody accountable to a remote); a `Co-authored-by` trailer only (GitHub shows the human as the
sole author).

### D5. Suggestions are events outside the fold; adoption is an ordinary human operation

A `suggestion` event holds the operation and its exact arguments; it is validated by running the real
operation's validation without its write. A `suggestion-resolve` event records the outcome. Neither enters
any fold, count or view, so `suggest` mode is safe by construction: it cannot change a result. Adopting
re-runs the operation as the person against current state, so the resulting event is a person's opinion,
with their rationale, and the link from the suggestion lets `strata why` show where it came from.

This is also what keeps blinding workable. A suggestion is *information a reviewer might be influenced
by*, so by default it is hidden until the reviewer has decided (`show_suggestions =
"after-own-decision"`). Reviews that want AI-first workflows set `always`, and strata then marks those
opinions as informed and keeps them out of independent agreement, using the first-opinion machinery that
already exists.

*Rejected:* a `status: suggested` flag on every event type (the fold would need to understand it
everywhere); making adoption a countersignature of the agent's own event (the person's act would not be
their own opinion, which is the failure this change avoids); suggestions as branches or pull requests
(appealing for hosted use, far heavier, and not available to a solo reviewer).

### D6. `count` mode: assigned agents fill reviewer slots and nothing else

The fold resolves a record from assigned actors' opinions only, which is what the spec already says. That
closes the gap above for everyone, not just agents. An agent counts as a second reviewer only if a person
has assigned it, and assignment stays human-only, so a model cannot enlist itself. Agreement is reported
per pair with agent pairs labelled; Methods and counts name people and models separately.

For work that has no reviewer slot (retrieval, studies, dedup, record corrections, searches and imports,
criteria, analysis) `count` simply means the event takes effect, as the agent's. For criteria and
adjudication the consequences are large; the safeguards are those the project already has: the criteria
impact preview is returned in the tool result and recorded, a criteria change by an agent is still a
`protocol-amendment` pull request under `add-review-repository-ci`, and `strata ai revoke` can undo an
agent's standing.

Changing the fold to ignore unassigned opinions changes results for any existing repository that contains
one (for example, decisions imported for an unassigned actor). That is a correction toward the written
specification and is listed in the changelog; `strata verify` gains a warning naming affected records.

### D7. Revocation reuses the staleness engine

`strata ai revoke AGENT` deactivates the actor and marks the decisions it contributed as stale with the
reason `agent-revoked` through the same mechanism as `strata rescreen --mark`. The records then appear in
the re-screening queue for people, with the prior (agent) decision displayed, exactly as after a criteria
change. "Changing your mind is cheap and safe" (G2) applies to deciding AI was a mistake.

### D8. What an agent cannot do is enforced by a table, and the table is tested

The MCP layer builds its tool list from an explicit map of operation to tool. A separate list names the
operations reserved for people. A test enumerates every mutating CLI command and fails unless each is in
exactly one of the two. A new command therefore cannot become reachable by agents, or silently
unreachable, by omission.

### D9. How the MCP server gets its facts

- `--as` names the invoker; without it, the only active non-observer person is used, otherwise writes are
  not offered.
- The client's name and version are read from the handshake's `clientInfo`.
- Every write tool takes `model` and `rationale` as required parameters. Tool schemas are generated from
  the method signatures, as today, so this is declared once.
- Policy is checked per call, not once at registration, so a lead changing it mid-session takes effect.
  All write tools are listed whenever AI is enabled; refusals say which policy refused.
- Paths are confined to the repository and `--allow-dir` after resolving links.
- Read tools use the agent's structural view: its queue is `stage_queue` for the agent actor, so blinding
  comes from the same data layout the web and CLI use, and a write result returns only the new event id
  and mode, never agreement.

### D10. Disclosure is computed

Facts about AI use come from one function over the event log (`core/agents.py`: events by agent and mode,
suggestions and their outcomes, invokers and dates). Methods text, checklist items 8, 9 and 11, the
ledger, `strata status` and `strata audit --ai` all read it. The fixed "no automation tools" sentences are
replaced by text that depends on it; with no AI the wording is unchanged and a golden test pins that. The
generated text always says the model name is self-reported.

### D11. Schema version 2, entered deliberately

Three things change that older tools would mishandle: a new envelope key, new event types, and the fold's
treatment of agents. An older tool opening such a repository would, at best, fail validation and, at
worst, count an agent as a person. A bump makes it refuse (`E_SCHEMA_TOO_NEW`) instead. The bump is
entered only by `strata ai enable` (via `strata migrate`), so repositories that never enable AI stay at 1
and are not nagged.

This is the first bump in the format's life, which is why `strata migrate` is built here; it is small
(one forward-only, idempotent step that rewrites `.strata/schema-version`), but it is the framework the
next bump will use. The tool supports versions 1 and 2, which relaxes the old wording "offer migrate for
any lower version" to "offer it in `strata status` and wherever a feature needs it".

*Rejected:* no bump, relying on the new envelope key to make old tools fail (it would, but only where
`verify` runs, and not for the fold change); bumping every repository on upgrade (forces migration on
people who never asked for AI).

### D12. Order of landing

Group 1 (identity, policy, schema) and 2 (suggestions) are independent of the write operations and ship
first, so reviews can register agents and see the machinery before any tool writes. Group 3 (MCP writes)
needs the shared operations of `add-web-ui-write-surfaces`; where that change has not moved an operation
yet (screening, adjudication, extraction, risk of bias, dedup, criteria, analysis), this change moves it
with the same snapshot-first discipline. Group 4 (disclosure) can land alongside group 1 and is where
the false sentences are removed.

## Risks / Trade-offs

- **[An agent with shell access bypasses all of it]** → Stated plainly in the wiki and in
  `Known-Limitations`: MCP is the attributed route, not an enforcement boundary; a person who lets an agent
  type `strata screen --by ada` has made the choice the old rules also allowed. Open question below.
- **[The model name is the agent's own claim]** → The registered-model match, the exact-string rule and
  the "self-reported" wording; no stronger claim is made anywhere.
- **[`--as` is the person's own statement]** → On a hosted instance the invoker comes from the signed-in
  account instead.
- **[Prompt injection through record text]** → Abstracts and notes are untrusted input to the agent. The
  damage is bounded by the policy, by the reserved list, by `suggest` being what the wiki recommends, and
  by the usual MCP client confirmation of tool calls. Tool results never carry instructions of their own.
- **[`count` on criteria or adjudication is powerful]** → Reviewers can choose it; it is visible in
  `strata.toml`, in the log, in Methods text and in the pull-request label; revocation undoes its
  standing. A reviewer who thinks that is too much sets `suggest`.
- **[Two machines invoking one model append to one agent file]** → Handled by the existing same-actor
  union merge and `relink` at sync, at the cost of more `relink` events for agents.
- **[The fold fix changes results for repositories with unassigned opinions]** → Listed in the changelog
  and flagged by `verify`.
- **[This change is large]** → It is staged (D12) with each group safe with AI off.
- **[Overlap with `add-web-ui-write-surfaces`]** → Both add requirements to `web-ui` and use the
  operations layer; their requirement names do not collide, and the order is stated.

## Migration Plan

1. Land group 1 and the false-sentence fixes of group 4: no behaviour change for any existing review.
2. Land suggestions, then MCP writes family by family. Each family ships off.
3. Existing reviews are untouched until a lead runs `strata ai enable`, which migrates to version 2 in
   one commit. There is no downgrade, as for any forward-only migration; abandoning AI means revoking the
   agents and setting every kind to `off`.
4. Rule and doc changes (`openspec/config.yaml`, overview N5, `mcp-server` design and docstring) land
   with group 3, when the behaviour they describe exists.

## Open Questions

- **Agents that drive the CLI.** A harness could set an environment variable such as
  `STRATA_AGENT_MODEL` and have the CLI treat the invocation as an agent's (same policy, same
  attribution). It is opt-in and unenforceable, but it would give honest harnesses a way to take part
  openly without MCP. Deferred; nothing here depends on it.
- **Extra friction for `count` on `criteria` and `adjudication`.** Whether those two should need a
  second explicit acknowledgement in `strata.toml`. The current design relies on visibility and
  revocation; a reviewer may reasonably want more.
- **The default for `show_suggestions`.** `after-own-decision` protects independence; some teams will
  want `always`. It is a setting, so the default can change.
- **Where the unassigned-opinion correction is announced.** The changelog is certain; whether a release
  needs a migration note too depends on how many repositories contain such opinions.
