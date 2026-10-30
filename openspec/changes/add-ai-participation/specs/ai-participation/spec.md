# Spec Delta

## Purpose

How a review lets AI agents take part and keeps that participation visible: a policy the reviewers set and
commit, agents as named actors with the person who invoked them, what an agent's work counts for, what an
agent can never do, and how all of it is disclosed. `strata` ships no model; this capability governs the
ones reviewers bring.

## ADDED Requirements

### Requirement: Off by default

A review MUST NOT accept an agent-authored event or a suggestion, and `strata mcp` MUST NOT offer a write
tool, until a lead has enabled AI participation for that review. Enabling MUST be an attributed commit
that carries the lead's rationale.

#### Scenario: A review that never enables AI

- **GIVEN** a repository on which `strata ai enable` has never run
- **WHEN** an agent connected through `strata mcp` lists its tools
- **THEN** it sees read tools only
- **AND** a policy tool tells it that AI participation is not enabled for this review

#### Scenario: Enabling

- **WHEN** a lead runs `strata ai enable` with a rationale
- **THEN** `strata.toml` records `[ai] enabled = true` with every kind of work set to `off`
- **AND** the commit carries `Strata-Op: ai-enable` and the lead's rationale

#### Scenario: Agent events in a review that has not enabled AI

- **GIVEN** an event carrying an `agent` key in a repository where AI is not enabled
- **WHEN** `strata verify` runs
- **THEN** it reports the event as invalid

### Requirement: A policy for each kind of work

`[ai.policy]` MUST give each kind of work one of `off`, `suggest` or `count`, and each MUST default to
`off`. The kinds are `screening`, `extraction`, `risk-of-bias`, `retrieval`, `studies`, `dedup`, `records`,
`search-import`, `criteria`, `adjudication` and `analysis`.

#### Scenario: Setting a mode

- **WHEN** a lead sets `screening` to `suggest` with a rationale
- **THEN** `strata.toml` records it and the commit carries `Strata-Op: ai-policy` and the previous and new modes

#### Scenario: Unknown kind

- **WHEN** a policy is set for a kind that is not listed
- **THEN** it is refused and the valid kinds are named

#### Scenario: A kind that is off

- **GIVEN** `extraction` is `off`
- **WHEN** an agent calls an extraction write tool
- **THEN** the call is refused with a message naming the policy and nothing is recorded

### Requirement: Policy changes are for people

Changing the AI policy, enabling or disabling AI participation, and registering, deactivating or changing
the role of an actor MUST be possible only by a person using the command line or web interface, and MUST
NOT be reachable through any MCP tool or suggestion.

#### Scenario: Agent tries to widen its own policy

- **WHEN** an agent attempts any call that would change `[ai.policy]`
- **THEN** no such tool exists and the policy is unchanged

### Requirement: Agents are registered actors

A lead MUST register each model a review accepts as an actor with `kind = "agent"`, a `model`, and a
`role`, and an agent actor MUST NOT hold the `lead` role. An agent's events MUST be written under its own
handle and MUST NEVER be written under a person's handle.

#### Scenario: Registering a model

- **WHEN** a lead runs `strata actor add claude-opus --kind agent --model claude-opus-5-5 --role screener`
- **THEN** the manifest lists an agent actor `claude-opus` for that model

#### Scenario: Agent as lead

- **WHEN** an agent actor is registered with the `lead` role
- **THEN** it is refused

#### Scenario: Events keep to their author

- **GIVEN** `ada` invoked the agent `claude-opus`
- **WHEN** the agent records a screening decision
- **THEN** the event's `actor` is `claude-opus`, not `ada`

### Requirement: The reported model must match

Every write call MUST include the model name as the agent reports it, and MUST be refused unless that name
equals the registered model of an active agent actor of the review. The refusal MUST say how a lead can
accept the model.

#### Scenario: Unregistered model

- **WHEN** an agent reports `claude-opus-5-6` and only `claude-opus-5-5` is registered
- **THEN** the call is refused, nothing is recorded, and the message names `strata actor add` as the way to accept it

#### Scenario: No model reported

- **WHEN** a write call omits the model
- **THEN** it is refused as invalid

#### Scenario: Deactivated agent

- **GIVEN** the agent `claude-opus` was deactivated
- **WHEN** it reports its registered model on a write call
- **THEN** the call is refused

### Requirement: Every agent event is attributed

Every event an agent causes MUST carry an `agent` envelope key holding the model as reported, the client
name and version from the MCP handshake when the client gave them, and `invoked_by`, the handle of the
person who started the server. The model name MUST be described as self-reported wherever it is shown,
because `strata` cannot verify it.

#### Scenario: Screening event written by an agent

- **WHEN** an agent invoked by `ada` records a screening decision
- **THEN** the event carries `agent.model`, `agent.client` and `agent.invoked_by` equal to `ada`

#### Scenario: Showing provenance

- **WHEN** `strata why` lists that decision
- **THEN** the entry reads as an AI decision by the agent, shows the reported model and `ada` as the person who invoked it, and says the model name is self-reported

### Requirement: Commits do not pass an agent's work off as a person's

A commit created by an agent write MUST be authored as the agent and committed by the person who invoked
it, and MUST carry the trailers `Strata-Agent`, `Strata-Invoked-By` and `Strata-Via: mcp`. The author
address MUST be one that cannot be delivered to or matched to a hosting account.

#### Scenario: Commit identities

- **WHEN** an agent invoked by `ada` records a retrieval outcome
- **THEN** the commit's author is the agent and its committer is `ada`'s configured git identity
- **AND** the trailers name the agent, `ada` and the MCP route

### Requirement: Suggest and count modes

In `suggest` mode a write MUST be recorded as a suggestion and MUST change no review state. In `count`
mode a write MUST take effect directly, as the agent, and be reported as an agent's.

#### Scenario: Suggest

- **GIVEN** `screening` is `suggest`
- **WHEN** an agent records a screening decision
- **THEN** a suggestion is recorded, and the pool, conflicts, PRISMA counts and staleness are unchanged

#### Scenario: Count

- **GIVEN** `retrieval` is `count`
- **WHEN** an agent records that a report was retrieved
- **THEN** the retrieval event takes effect as the agent's, with the agent key

### Requirement: Agents count toward a record only when assigned

An opinion from an agent on screening, extraction or risk of bias MUST count toward a record's resolution
only when that agent is assigned to it at that stage. An agent opinion from an unassigned agent MUST be
kept and shown but MUST NOT contribute to the record's state.

#### Scenario: Unassigned agent

- **GIVEN** a record assigned to `ada` and `sam`, and an agent that is not assigned
- **WHEN** `ada` and the agent record `include`
- **THEN** the record's state is partial, awaiting `sam`

#### Scenario: Assigned agent as second reviewer

- **GIVEN** a record assigned to `ada` and `claude-opus` in `count` mode
- **WHEN** both record `include`
- **THEN** the record resolves to `include`

#### Scenario: Agent and person disagree

- **GIVEN** the same assignment
- **WHEN** `claude-opus` records `include` and `ada` records `exclude`
- **THEN** the record is in conflict and goes to an adjudicator

### Requirement: People and agents are counted apart

Agreement statistics MUST be reported per pair and label every pair involving an agent. Generated text and
counts MUST give the number of reviewers who are people and the number of agents separately, and an agent
MUST NOT be called a reviewer without being named as an AI tool.

#### Scenario: Agreement with an agent

- **WHEN** `derived/irr.json` is regenerated for a stage screened by `ada`, `sam` and `claude-opus`
- **THEN** it reports the pairs `ada`/`sam`, `ada`/`claude-opus` and `sam`/`claude-opus`, the last two marked as involving an agent

#### Scenario: Reviewer count in the Methods

- **WHEN** Methods text is generated for a dual review with one agent as a counted reviewer
- **THEN** it says the record was screened by two people and one AI model, naming the model

### Requirement: Operations an agent cannot perform

No MCP tool or suggestion MUST exist for changing the policy, registering, deactivating or re-roling an
actor, assigning reviewers, changing configuration, creating or cloning a review, repairing hooks or
merge drivers, or synchronising with a remote.

#### Scenario: Complete list of tools

- **WHEN** a client lists the tools of a server for a review with every kind set to `count`
- **THEN** none of them performs any of those operations

#### Scenario: A command is added later

- **GIVEN** a new mutating command
- **WHEN** the test suite runs
- **THEN** it fails until the command is classified as available to agents or as reserved for people

### Requirement: Revoking an agent

`strata ai revoke <agent>` MUST deactivate the agent actor, mark every still-counted decision it
contributed as stale for re-screening with the reason `agent-revoked`, and record both with the lead's
rationale. The agent's history MUST remain.

#### Scenario: Revoking after a screening round

- **GIVEN** `claude-opus` counted as second reviewer on 800 records
- **WHEN** a lead revokes it
- **THEN** those 800 decisions appear in the stale queue with the reason `agent-revoked`, the agent is inactive, and its events are still in the log

### Requirement: Disclosure in generated text

Whenever a review contains an agent-authored event or a suggestion, generated Methods text and PRISMA 2020
checklist items 8, 9 and 11 MUST name each model used, the kinds of work and the mode it was used in, and
the numbers of its suggestions adopted and rejected and of its decisions counted. Generated text MUST NOT
state that no automation tools were used when any were.

#### Scenario: Suggestions only

- **GIVEN** an agent made 1,200 screening suggestions, 1,050 adopted and 150 rejected
- **WHEN** Methods text is generated
- **THEN** the selection-process paragraph names the model, says its suggestions were reviewed by a person before any took effect, and gives 1,050 and 150

#### Scenario: Counted reviewer

- **GIVEN** an agent counted as a reviewer at title/abstract
- **WHEN** checklist item 8 is generated
- **THEN** it names the model and states that it acted as a reviewer

#### Scenario: No AI

- **GIVEN** a review with no agent events and no suggestions
- **WHEN** Methods text is generated
- **THEN** its wording about automation is the wording it has today

### Requirement: The AI ledger and audit

`strata ai report` MUST give, for each agent and kind of work, the suggestions made, adopted and rejected,
the events counted, the events later changed by a person, the people who invoked it and the dates it was
active. `strata audit --ai` MUST re-present a random sample of agent decisions that no person has
independently decided, reproducibly from a seed.

#### Scenario: Ledger

- **WHEN** `strata ai report` runs on a review with one agent
- **THEN** it reports that agent's figures per kind of work and invoker

#### Scenario: Sampling for verification

- **WHEN** `strata audit --ai --sample 20 --seed 7` runs twice
- **THEN** both runs present the same 20 agent decisions

#### Scenario: Status

- **WHEN** `strata status` runs on a review with AI enabled
- **THEN** it shows that AI participation is on, the policy in force and the number of agent events
