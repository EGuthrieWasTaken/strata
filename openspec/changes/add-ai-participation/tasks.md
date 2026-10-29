# Tasks

Every group is safe to ship with AI participation off, which is the default, and each lands its own tests
and wiki changes (`openspec:test-suite#every-change-carries-its-tests`). Groups 1 and 2 need nothing
from the write path; group 3 uses the shared operations that `add-web-ui-write-surfaces` introduces and
moves any it has not moved yet.

## 1. Identity, policy and schema version 2

- [ ] 1.1 Raise the supported schema range to versions 1 and 2 in `core/repo.py` and add `strata migrate` (forward-only, idempotent, one commit with a generated message and the person's rationale); verify that a version 1 repository still runs every command unchanged, that `strata status` mentions format 2 is available, that migrating twice makes no second commit, and that a build limited to version 1 refuses a version 2 repository with `E_SCHEMA_TOO_NEW`
- [ ] 1.2 Add `kind`, `model`, `[ai]` and `[ai.policy]` to the manifest schema and `core/manifest.py`, with the `E_CONFIG` rules; verify with a unit test per scenario in `data-schemas` (agent without model, person with model, policy without enabling, agent as lead)
- [ ] 1.3 Extend `strata actor add` with `--kind agent --model`, refusing at version 1 or without `[ai] enabled`, and make deactivation of an agent point to `strata ai revoke`; verify with CLI tests for registration, each refusal message, and removal being refused once the agent has history
- [ ] 1.4 Add the optional `agent` envelope key to `event.schema.json`, event append and canonical serialisation, in the position and with the digest coverage the spec defines; verify with a golden line for an agent event, round-trip and stability properties (P3, P4) extended to agent events, a golden showing a person's event is byte-identical to before, and the determinism job on all three platforms
- [ ] 1.5 Add `core/agents.py` with policy lookup, registered-model matching, invoker resolution and the `AgentContext` the write path will carry; verify with a unit test for every refusal in `ai-participation` (off, unknown model, deactivated agent, no invoker, observer invoker) including the message that tells a lead how to accept a model
- [ ] 1.6 Add `strata ai enable` and `strata ai policy`, each a rationale-bearing commit with `Strata-Op: ai-enable` / `ai-policy` and the old and new modes; verify with CLI tests for enabling, setting, showing, an unknown kind, setting before enabling, and the `strata log` entry
- [ ] 1.7 Teach `strata verify` that an `agent` key is valid only at version 2 with AI enabled, with a registered agent actor and an active-person `invoked_by`; verify with a test for each way an agent event can be invalid
- [ ] 1.8 Make the fold resolve a record from assigned actors' opinions only, keeping unassigned ones in the log and provenance, and have `strata verify` warn about records an existing unassigned opinion used to help resolve; verify with the scenarios in `event-log`, P1 and P2 extended to include unassigned and agent opinions, and the 100% branch floor on `core/fold.py`; record the change in the CHANGELOG
- [ ] 1.9 Label every agreement pair that involves an agent in `derived/irr.json` and the IRR view; verify with a test that three screeners (one an agent) give three labelled pairs and that person-to-person figures are unchanged
- [ ] 1.10 Start the wiki page "Using AI in a review" (the policy, registering a model, what `migrate` does, what is and is not recorded) and link it from `Working-with-Others`; verify `scripts/check_wiki.py` passes

## 2. Suggestions

- [ ] 2.1 Add the `suggestion` and `suggestion-resolve` event types, their schemas and sharding, and exclude them from every fold, count and view; verify with a property test that adding any number of suggestion events leaves the folded state and all of `derived/` identical
- [ ] 2.2 Add `protocol/suggestions.py`: record a suggestion after running the real operation's validation without its write, supersede an earlier one by the same agent for the same target, and list pending ones; verify that an invalid suggestion is refused for the real reason, that a valid one leaves `derived/` byte-identical, and that a criteria suggestion carries its impact preview
- [ ] 2.3 Add adopt and reject: adoption re-validates against current state, runs the operation as the person with their rationale, writes the link, and leaves the resulting events without an agent key; verify the adopt, state-moved, wrong-role and reject scenarios, and that `strata why` shows the suggestion and the person's event together
- [ ] 2.4 Apply blinding to suggestions (hidden until the reviewer has decided unless `show_suggestions = "always"`), and mark opinions recorded after seeing a suggestion as informed and exclude them from independent agreement; verify with the three scenarios in `ai-suggestions` and an IRR test
- [ ] 2.5 Add `strata suggestions list|show|adopt|reject` with `--json`; verify with CLI tests for each subcommand and the JSON shape
- [ ] 2.6 Add the web `/suggestions` screen, the AI label (icon plus text, never colour alone) on timelines, adjudication and history, and the dashboard line; verify with `TestClient` tests for adopt, reject without a reason, blinded listing, and that a hostile rationale is escaped
- [ ] 2.7 Extend the wiki page with suggestions (adopting, rejecting, blinding, `show_suggestions`) and `The-Web-Interface` with the suggestions screen; verify `scripts/check_wiki.py` passes

## 3. MCP write tools

- [ ] 3.1 Move the judgement operations (screen, adjudicate, extract, reconcile, risk of bias) onto `core/operations.py`, snapshot tests first, unless `add-web-ui-write-surfaces` has already done so; verify each command's stdout, exit code, files and commit message are unchanged
- [ ] 3.2 Move the remaining operations (criteria add, edit and retire; dedup decisions; analyze, prisma and report generation) onto `core/operations.py` the same way; verify the same snapshots
- [ ] 3.3 Add `strata mcp --as` and `--allow-dir`, capture the client's name and version from the handshake, and build the `AgentContext`; verify with an in-process MCP client for each scenario in `mcp-server` (named invoker, several people without `--as`, observer, no write tools when AI is off)
- [ ] 3.4 Add write tools for retrieval, studies, record correction and notes, and dedup decisions, each requiring `model` and `rationale` and obeying `off`, `suggest` and `count`; verify per family that `off` refuses and records nothing, `suggest` records only a suggestion, `count` records an agent-keyed event, and the tool and the command give the same event body
- [ ] 3.5 Add write tools for screening, extraction and risk of bias; verify the same three modes, that an unassigned agent's opinion is recorded but does not resolve a record, that an assigned agent in `count` mode does, and that a conflict with a person goes to an adjudicator
- [ ] 3.6 Add write tools for searches and imports (paths confined, links resolved), criteria (impact preview in the result and recorded), adjudication, and analysis; verify path escape attempts are refused, a criteria change in `count` mode stales exactly what the command stales, and `suggest` mode changes nothing
- [ ] 3.7 Add the read tools an agent needs (its own queue, active criteria, extraction and risk-of-bias forms, retrieval queue, study suggestions, the policy tool) built on the structural blinding the screening layer already has; verify with the `mcp-server` blinding scenarios, that a write result never reports agreement, and parity of each read with its CLI counterpart
- [ ] 3.8 Add the reserved-operations test: enumerate every mutating CLI command and fail unless it is mapped to a write tool or listed as reserved for people (policy, actors, assignment, config, init, clone, doctor, sync, merge); verify it fails when a new command is added unclassified
- [ ] 3.9 Author agent commits as the agent and commit as the person, with `Strata-Agent`, `Strata-Invoked-By` and `Strata-Via` trailers and an undeliverable author address; verify with a real `git` repository that author and committer differ as specified and `strata log --actor` finds the agent's commits
- [ ] 3.10 Rewrite the `mcp-server` docstring and instructions to state the policy, the `mcp-server` design's "Why read-only" section, overview non-goal N5, `docs/roadmap.md`, and the `openspec/config.yaml` proposal rule that forbids MCP paths that record decisions without a human (replacing it with the attribution and reserved-operations rule); verify `scripts/check_docs.py` passes and the instructions test matches the spec scenarios
- [ ] 3.11 Add an end-to-end test: enable AI, register an agent, assign it, suggest and adopt, count as a second reviewer, produce a conflict, adjudicate, then revoke; verify counts, agreement pairs, trailers, the stale queue and the Methods text at each step
- [ ] 3.12 Complete the wiki: the MCP section of `Commands-Sharing-and-Tools`, the full "Using AI in a review" page (policy examples, what each mode does, reading the ledger), and `Known-Limitations` stating that MCP is an attributed route and not an enforcement boundary against an agent that drives the CLI; verify `scripts/check_wiki.py` passes

## 4. Disclosure and audit

- [ ] 4.1 Add the ledger function in `core/agents.py` (events by agent, kind and mode; suggestions and outcomes; invokers; active dates; events later changed by people); verify with a fixture repository whose figures are known
- [ ] 4.2 Replace the fixed "no automation tools" sentences in `report/sections.py` and `report/checklist.py` with text computed from the ledger, make `reviewers()` list people only, and cover checklist items 8, 9 and 11; verify golden Methods and checklist output with and without AI, that the no-AI wording is unchanged, and that suggestion-only and counted-reviewer cases read correctly
- [ ] 4.3 Add `strata ai report`, `strata ai revoke` (deactivate, mark counted decisions stale with the reason `agent-revoked`) and `strata audit --ai` (seeded sample of agent decisions no person has decided independently); verify the ledger output, that revoking puts the right records in the stale queue, and that a seed reproduces the sample
- [ ] 4.4 Add the AI line to `strata status` and `status --json`; verify the human and JSON output on a review with and without AI
- [ ] 4.5 Confirm byte-identical agent-event serialisation and generated output across the platform matrix; verify the determinism job passes on Linux, macOS and Windows

## 5. Close-out

- [ ] 5.1 Verify `openspec validate add-ai-participation --strict` passes and that no `openspec:` reference in code, tests or docs fails `scripts/check_docs.py`
- [ ] 5.2 Update `README.md`, the CHANGELOG, `docs/roadmap.md` and `docs/m6-plan.md`, and add coordination notes to `add-web-ui-write-surfaces` (shared operations), `add-prisma-reporting` (the amended Methods and checklist code) and `add-hosted-team-deployment` (remote MCP and the signed-in invoker); verify the documentation checks pass
- [ ] 5.3 Run the full local gate (`ruff`, `mypy --strict`, `pytest` with the coverage floors and diff coverage, determinism) and verify it is green on Linux, macOS and Windows in CI
- [ ] 5.4 Have a methodologist read the generated AI disclosure for a review that used suggestions and for one that used a counted reviewer and judge it accurate and sufficient, and record the outcome in `docs/m6-plan.md` (a manual gate; it is not claimed until a person has done it)

## Workflow follow-up

- At archive, edit the `mcp-server` capability's Purpose, which still says the server never records a decision, to describe attributed, policy-governed writes.
- Revisit the open questions in `design.md` once a review has used this for real: the CLI environment marker for agents, extra friction for `count` on criteria and adjudication, and the default for `show_suggestions`.
