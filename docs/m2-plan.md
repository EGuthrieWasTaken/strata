# M2 ("Screening and staleness") — sub-objective plan

Not part of the specification in `docs/spec/` (design content executed once)
— this is a working implementation-tracking note for whichever agent or
session picks up M2 next, kept outside `docs/spec/` deliberately so it isn't
subject to that tree's own document-map/link-integrity checks
(`scripts/check_docs.py`). Modelled on `docs/m1-plan.md`; read that file
first for the conventions this one assumes rather than re-derives.

## Why this file exists

Per `docs/spec/15-roadmap.md`, M2 is a 6-8 week milestone and **the
flagship**: criteria management with direction classification, the
staleness engine, CLI and web screening surfaces, dual screening, blinding,
IRR, adjudication, `strata rescreen`/`audit`/`irr`, and `strata serve`. Too
large for one sitting — broken into sub-objectives below, each scoped to be
completable (implemented, tested, lint/type clean, committed) in a single
sitting. Update the status table as work lands.

## M1 status (verified before M2 work started)

M1 is complete per `docs/m1-plan.md`: all 8 sub-objectives done except the
explicitly-deferred EndNote XML / Excel / PRISMA-text parsers (sub-objective
3, "partial" — out of M2's scope, revisit whenever a session picks up parser
work). All M1 acceptance criteria met (golden fixtures, dedup benchmark
recall 1.000 / false-merge 0.0000, 50k import 20.1s, 50k dedup 126.0s,
`strata why` provenance chain). `strata.core.fold` already ships
`resolve_screening`/`ScreeningState`/`fold_first_write` built in
anticipation of M2 — read `src/strata/core/fold.py` before writing
`protocol/screening.py`; the state-resolution logic mostly already exists,
this milestone's job is the repo I/O, events, staleness, and CLI/web layers
around it.

## Conventions established so far (follow these, don't re-derive them)

All of `docs/m1-plan.md`'s conventions still apply verbatim (rationale flow,
structured commits, schema validation on write+load, canonical serialisation
via `strata.core.canon`, thin CLI, coverage bar, global option ordering, no
`Strata-` trailers on strata's own source commits). Additions specific to
M2:

- **New protocol modules live in `src/strata/protocol/`** alongside
  `searches.py` — `criteria.py`, `screening.py`, `staleness.py`,
  `adjudication.py`, `irr.py`. Each following `searches.py`'s shape: a
  `*Error` exception, path helpers, `add_*`/`list_*`/`get_*` functions, schema
  validation via `strata.core.validate.validate(name, instance)` before
  every write.
- **`protocol/staleness.py` is one of the five 100%-branch-coverage modules**
  named in `docs/spec/14-testing.md` §1 (alongside `core/fold.py`,
  `core/ids.py`, `core/canon.py`, `stats/escalc.py`). Every branch, no
  exceptions, no `# pragma: no cover` without a reviewed justification. This
  is the module the entire project's credibility rests on — see
  `docs/spec/15-roadmap.md`'s "if the staleness engine does not work... the
  project has no reason to exist."
- **P10's brute-force reference lives in the test file, not in shipped
  code** (`tests/property/test_staleness_properties.py`), written
  independently of `protocol/staleness.py`'s implementation so it can catch
  a shared bug. Follow `tests/property/test_dedup_properties.py`'s existing
  P8 pattern (hypothesis-generated records, `@pytest.mark.req("P8")`) for
  structure; use `@pytest.mark.req("P10")`.
- **Event sharding for new domains**: `events/screen/<stage>.<actor>.ndjson`,
  `events/adjudication/<actor>.ndjson` (dir already scaffolded by
  `core/init.py`'s `DIRECTORIES`), `events/assign/<actor>.ndjson` (not yet
  scaffolded — `append_event`'s `mkdir(parents=True)` creates it on first
  write, same as `events/fix/` did in M1's `records.amend_field`, so this is
  fine, but add it to `DIRECTORIES` too for a repo that never assigns before
  its first `strata verify`/`doctor` run expects the directory. Actually not
  required — `iter_event_files` globs `events/**/*.ndjson` and tolerates a
  missing subdirectory; only add it if it turns out to matter for a test).
  `protocol/criteria.yaml` changes emit `criteria-change` from
  `events/criteria/<actor>.ndjson`.
- **`criteria.yaml` is declarative config, not an event-sourced file** (like
  `strata.toml`): authoritative, hand-editable, rewritten in full on every
  change — same treatment as `protocol/searches/*.yaml` gets on creation, but
  criteria are mutable in place (a `retire` sets `status: retired` on the
  existing entry rather than creating a new file). The `criteria-change`
  event is what makes history auditable and staleness computable; the YAML
  file is only ever the *current* state.
- **No per-event-type body JSON Schema** — M0/M1 never added one (`event`
  schema's `body` is `{"type": "object"}`, unconstrained); `screen`,
  `adjudicate`, `assign`, `criteria-change` follow the same precedent rather
  than introducing a new validation mechanism this milestone doesn't need to
  invent. Structure is enforced by the producing/consuming code and tests,
  as `dedup-merge`/`record-amend` already are.
- **`strata.toml [screening]` config is already fully specified** in
  `docs/spec/03-schemas.md` §1 and already round-trips through
  `core/manifest.py`/`manifest.schema.json` (`stages`, `mode`,
  `adjudicators`, `blind_reviewers`, `blind_metadata`,
  `require_exclusion_reason`, `screening.assignment`). No new manifest
  schema work needed unless a gap is found.
- **Blinding is structural, not a runtime check**: per
  `docs/spec/06-workflow-screening.md` §2, each reviewer's screen events live
  in their own file and the CLI/web layer simply never reads another actor's
  event file to render the *current* screening prompt. There is no
  "blind mode" branch to test for leaking data — the leak would have to be a
  positive act of reading the wrong file, which is easy to review for.

## Sub-objectives

| # | Sub-objective | Status |
|---|---|---|
| 1 | Criteria management: schema, CRUD, versioning, direction classification, digests | **done** |
| 2 | Staleness engine: `protocol/staleness.py`, P10 + brute-force reference | **done** |
| 3 | Screening core + CLI: `protocol/screening.py`, `screen`/`assign` events, `strata screen`/`strata assign` | **done** |
| 4 | Rescreen + cascading staleness: `strata rescreen`, `derived/stale.tsv`, upstream-stale cascade | **done** |
| 5 | Adjudication: `strata adjudicate`, `adjudicate` event, role/rationale enforcement | **done** |
| 6 | IRR: `derived/irr.json`, Cohen's kappa/PABAK, `strata irr` | **done** |
| 7 | `strata status` full dashboard + `derived/pool.tsv`/`conflicts.tsv` regeneration | **done** |
| 8 | `strata audit --criteria` sampling workflow | **done** |
| 9 | E2E scenarios: E2E-01 (origin), E2E-04, E2E-05, E2E-06, E2E-09 | **done** |
| 10 | Screening-latency benchmark (<100ms p95 @ 50k) | **done** |
| 11a | Web UI, sitting 1: `strata serve` scaffold, security baseline, dashboard, screening surface | **done** |
| 11b | Web UI, sitting 2: criteria editor w/ live, non-mutating impact preview (M2 acceptance bullet) | **done** |
| 11c | Web UI, sitting 3: rescreen + adjudicate + records/history + dedup screens | **done** |
| 12 | Traceability updates, roadmap acceptance pass, docs polish | **done** |

### 1. Criteria management — done

Spec: `docs/spec/06-workflow-screening.md` §3, `docs/spec/03-schemas.md` §3,
`docs/spec/10-cli.md` §"Protocol" (`criteria list/add/edit/retire/diff`).

Delivered: `src/strata/schemas/criteria.schema.json`,
`src/strata/protocol/criteria.py` (`add_criterion`/`edit_criterion`/
`retire_criterion`/`list_criteria`/`get_criterion`/`next_criterion_id`/
`reconstruct_at_version`/`diff_versions`, `per_criterion_digest`/
`set_digest`), `strata criteria add|edit|retire|list|diff` in
`cli/main.py` (new `criteria_app` sub-typer), `E_CRITERION_REUSE` +
criteria-schema validation added to `core/verify.py`, and
`tests/unit/test_criteria.py` / `tests/integration/test_cli_criteria.py` /
additions to `tests/unit/test_verify.py` (100% line+branch on
`criteria.py`).

- **Version numbering**: `strata init` now seeds `criteria.yaml` at
  `version: 0` (was `1`) and every `add`/`edit`/`retire` bumps the version
  by exactly one, per §3.1's literal normative text ("*any* change...
  increments `criteria.version` by one") — see the long comment at the top
  of `criteria.py` for why this was chosen over the informative §9 worked
  example's "6 criteria, version 1" phrasing, which this implementation
  treats as a narrative simplification rather than a literal constraint.
  `tests/unit/test_status.py::test_compute_status_on_freshly_initialised_repo`
  was updated from asserting `criteria_version == 1` to `== 0` accordingly.
- **Digests**: per-criterion digest is `sha256` over canonical JSON of
  `{id, kind, definition, applies_at}` (applies_at sorted for stability);
  set digest is `sha256` over the newline-joined per-criterion digests of
  *active* criteria sorted by id. Both match §3's spec text exactly
  (`label`/`examples` excluded so relabelling can never create staleness).
- **The editorial guard** (§3.2) distinguishes a truly no-op edit (nothing
  at all changed — rejected regardless of direction) from a
  whitespace/label/examples-only edit (`editorial` is allowed) from a
  meaning-changing edit (`editorial` is refused, `tightened`/`loosened`/
  `both` are not). "Meaning changed" compares `definition` after whitespace
  normalisation and `applies_at` as an unordered set; raw (non-normalised)
  equality is what decides "no-op" vs "something changed", so a
  whitespace-only cleanup is a real, recordable edit but never a
  staleness-causing one.
- **History without snapshot storage**: `criteria.yaml` holds only the
  *current* state (declarative config, like `strata.toml` — rewritten in
  full on every change, never event-sourced itself). Each `criteria-change`
  event's `deltas[]` carries a full post-change snapshot of the touched
  criterion (`id`, `origin`, `direction`, `kind`, `label`, `definition`,
  `applies_at`, `since_version`, `status`), so `reconstruct_at_version`
  rebuilds the set as of any past version by folding deltas
  last-write-wins per criterion id (the same fold shape as everything else
  in this codebase) — no separate snapshot file needed, and
  `strata criteria diff <v1> <v2>` is just "every delta with `to_version`
  in `(v1, v2]`". Does not yet compute *what a change invalidated* (needs
  sub-objective 4's `compute_stale_records`); `diff` currently only shows
  what changed.
- **Rationale is unconditional for criteria changes**, unlike the general
  `--why`/`git.require_rationale` flow other commands use: `cli/main.py`'s
  `_get_rationale` was refactored into a shared
  `_prompt_and_validate_rationale` helper plus two callers —
  `_get_rationale` (config-driven, existing behaviour, unchanged) and the
  new `_get_required_rationale` (always required, no escape hatch) — since
  the `criteria-change` event schema stores `rationale` in its own body
  (per the event catalog in docs/spec/02-repository-format.md §4.4), not
  just in the commit message, and because §3.2's "Why did you make this
  change?" prompt is unconditional in the spec's own worked example.
  `strata adjudicate` (sub-objective 5) will reuse `_get_required_rationale`
  too, per §8's identical "rationale REQUIRED, no config escape" wording.
- **`E_CRITERION_REUSE`** is driven by the event log, not by
  `criteria.yaml`'s current content (our own `add_criterion` already
  refuses to reuse an id still present in the file, retired or not) — it
  scans every `criteria-change` event's deltas for more than one
  `origin: added` on the same criterion id, which only fires against a
  hand-edited/corrupted repository where an entry was deleted and its id
  reissued. Caught a real ordering bug during development: the check must
  run even when `protocol/criteria.yaml` is missing or blank, which the
  first draft's early-return skipped.

### 2. Staleness engine — done

Spec: `docs/spec/06-workflow-screening.md` §4-§5, `docs/spec/14-testing.md`
P10.

Delivered: `src/strata/protocol/staleness.py` (`CriterionChange`,
`StaleInfo`, `relevant_changes`, `evaluate_staleness`) — pure, no I/O, 100%
line+branch coverage. `tests/unit/test_staleness.py` pins every row of
§5's reason table by name (including the §4.3 residual-risk "miscited
criterion" scenario) and `tests/property/test_staleness_properties.py`
implements P10: an independently-written, deliberately naive brute-force
reference (explicit loops, no shared helpers with the production code,
re-derives `effective_direction` inline rather than calling the property)
checked against `evaluate_staleness` over `hypothesis`-generated random
decisions/criteria-change sets, `@pytest.mark.req("P10")`.

- **`CriterionChange.effective_direction`** maps `origin: added` ->
  `tightened` and `origin: retired` -> `loosened` per §3.2, otherwise
  passes through the stored `direction` (including `editorial` for a
  no-op-meaning edit) — the one piece of interpretation this module adds
  on top of a literal transcription of §4.2's three-clause rule.
- **Reason priority when causes overlap**: §5's table doesn't rank what
  happens when more than one criterion change would independently stale
  the same decision (e.g. one `added` criterion and one `both`-direction
  edit both apply). This implementation picks `criterion-both` first (most
  conservative/informative), then the origin-specific reason
  (`criterion-added`/`criterion-retired`), then the generic direction
  reason — documented in `evaluate_staleness`'s docstring as this
  implementation's own deterministic tie-break, not a spec requirement.
- **What this module deliberately does not do**: cross-stage cascading
  (`upstream-stale`, §4.4) and manual invalidation (`manual`, §6) both need
  context (a record's other stage decisions, or an explicit user action)
  a pure per-decision function can't have — layered on by sub-objective 4's
  `compute_stale_records`, which calls `evaluate_staleness` per resolved
  decision and adds those two reasons around it.

### 3. Screening core + CLI — done

Spec: `docs/spec/06-workflow-screening.md` §1-§2, §7,
`docs/spec/02-repository-format.md` §4.3 (fold resolution — already
implemented in `core/fold.py`), `docs/spec/10-cli.md` §"Screening".

Delivered: `src/strata/protocol/screening.py` (`assigned_actors`,
`resolve_record_state`, `stage_queue`, `record_screen_decision`,
`import_decisions_tsv`, `assign_reviewers`), `strata screen`/`strata assign`
in `cli/main.py`, `E_EXCLUSION_NO_CRITERION`/`E_CRITERION_STAGE` added to
`core/verify.py`, `tests/unit/test_screening.py` /
`tests/integration/test_cli_screen.py` / additions to `tests/unit/
test_verify.py` (100% line+branch on `screening.py`).

- **Assignment resolution**: `assigned_actors(repo, stage, record_id)`
  checks the most recent `assign` event naming that record at that stage
  first (last-write-wins, same shape as every other fold here), falling
  back to `[screening.assignment]` in `strata.toml`, and finally to every
  configured `screener`/`lead` actor if neither is set — so a fresh repo
  with two screeners and no explicit assignment config works out of the box
  in dual mode, matching the manifest's own default.
- **`stage_queue`** (an actor's remaining work at a stage) reads every
  `screen` event for the stage *once* and groups by record in memory,
  rather than calling `resolve_record_state` (which would re-read per
  record) in a loop — the same O(n²)-avoidance shape M1's
  `append_new_events` fix already established for this codebase. This is a
  one-time per-session cost, not per-decision, so it doesn't bear on the
  <100ms decision-latency target (sub-objective 10) at all — that target
  is about `record_screen_decision`, which is a single `append_new_event`
  call, O(1) regardless of repository size.
- **Validation order in `_validate_and_build_body`**: stage exists, decision
  is valid, the record exists, every cited criterion is active *and*
  applies at this stage (one combined check, one error message — a
  criterion that's merely inactive and one that's merely wrong-stage are
  both just "not usable here right now," and splitting the message in two
  didn't seem worth the complexity), then the exclusion-needs-a-criterion
  rule: **full-text stage requires a citation unconditionally** (§7, no
  config escape), other stages only when `screening.
  require_exclusion_reason` is set. Both the single-decision path
  (`record_screen_decision`) and the bulk TSV path (`import_decisions_tsv`)
  share this one validator, so they can never drift apart.
- **The CLI screening loop is `typer.prompt`-based** (type a letter, press
  Enter), the same UX level M1's `strata dedup --review` already
  established, not a raw single-keystroke terminal capture — matching
  `docs/spec/11-web-ui.md`'s framing that the *web* UI is where §7's
  keyboard-first requirements are fully realized (S1-S14); the CLI's job
  is a serviceable, scriptable-adjacent surface, which `--decisions` already
  covers for real bulk/non-interactive throughput. `u`ndo re-visits the
  immediately-previous record for a fresh decision (append, not delete —
  P13 territory); it does not chain arbitrarily far back, which the code
  comments and tests document as a deliberate scope boundary rather than
  a bug.
- **Bug found and fixed by this sitting's full-suite run**:
  `_verify_screen_events` (the new `E_EXCLUSION_NO_CRITERION`/
  `E_CRITERION_STAGE` checks) was first wired into `verify_repository`
  unconditionally, including `fast=True` — the mode `strata`'s pre-commit
  hook uses on *every* commit. This broke
  `tests/e2e/test_e2e_02_concurrent_clones.py` (an M0-era skeleton that
  hand-crafts `screen` events citing a criterion that was never actually
  registered, because M0 predates criteria existing at all) the moment any
  commit touching `events/screen/**` ran through the hook. Fixed by moving
  `_verify_screen_events` next to `_verify_aliases`/`_verify_dangling_refs`
  under the existing `if not fast:` branch — it's the same category of
  check (reconstructs cross-event state, not a cheap per-line schema/chain
  check), and every real write path already validates before appending
  regardless, so fast mode losing it costs nothing in practice. A useful
  reminder that a new verify check needs to be graded into the fast/full
  split deliberately, not just appended to the end of the function.

### 4. Rescreen + cascading staleness — done

Spec: `docs/spec/06-workflow-screening.md` §4.4, §6.

Delivered: `src/strata/protocol/rescreen.py` (`compute_stale_records`,
`stale_records_for_stage`, `rescreen_queue`, `mark_manual_stale`,
`regenerate_stale_tsv`), `strata rescreen [--stage S] --by <actor>
[--mark ID...]` in `cli/main.py`, `tests/unit/test_rescreen.py` /
`tests/integration/test_cli_rescreen.py` (100% line+branch on
`rescreen.py`). Extended `protocol/screening.py`'s `resolve_record_state`
to accept `adjudicate_events` and added `all_adjudicate_events`, so
sub-objective 5 (`strata adjudicate`) slots in without touching this file's
staleness consumers again.

- **Resolved-decision model, not per-opinion**: `derived/stale.tsv` reports
  one row per `(stage, record)`, so this module treats a resolved
  `include`/`exclude` decision — the *agreement* of however many opinions
  were required — as the unit of staleness, not each reviewer's individual
  `screen` event. A multi-opinion agreement's `decision_version` is the
  **earliest** version among the contributing opinions and its `cited` set
  is the **union** of every opinion's citations; a property test
  (`test_multi_opinion_uses_earliest_version_and_union_of_citations`)
  specifically proves earliest-not-latest matters: a criterion loosened
  *between* two reviewers' opinions must still stale the pair's agreement,
  which the latest-version choice would miss. `maybe` never appears as a
  resolved decision (`core.fold.resolve_screening` folds any `maybe`
  opinion straight to `conflict`), so this module's staleness surface is
  `include`/`exclude` only — `protocol.staleness.evaluate_staleness`'s
  `maybe` branch remains fully implemented and unit/property-tested
  (sub-objective 2) for whenever per-opinion staleness on open conflicts is
  wanted. All of this is spelled out at length in `rescreen.py`'s own module
  docstring — read that before changing any of it.
- **Cascading** (§4.4): computed per stage in `_STAGE_ORDER` order
  (title-abstract before full-text) so a title-abstract record's own
  staleness is already known by the time full-text is evaluated; a
  full-text decision's own native staleness reason (if any) always takes
  priority over `upstream-stale`, checked in that order.
- **`manual` staleness** (§6): implemented as a `note` event (§4.4's
  catalog: "free-form, attaches to any entity") carrying a canonical-JSON
  `{stage, record}` payload under `subject: "manual-stale"`, rather than a
  new event type. A mark is "consumed" — stops counting — the moment a
  fresh `screen` decision for that `(stage, record)` is recorded after it;
  there is no separate un-marking event, matching the append-only,
  no-delete log. **Comparing by `ts` alone is not precise enough**: a mark
  and its consuming decision can land in the same wall-clock second (`ts`
  is second-precision), which a first draft got wrong and a test caught
  immediately (`mark_ts > decided_ts` was false when both were "equal").
  Fixed by comparing `(ts, id)` tuples instead — `id` is a ULID with
  millisecond-plus-randomness ordering, the same tie-break
  `core.fold.sort_events` already uses everywhere else in this codebase.
- **The `--i-have-reviewed-these` guard** (§6: `strata rescreen` MUST NOT
  offer a bulk "keep all" without it) needs no code: there is no bulk
  keep-all command at all, only a per-record `[k]` press inside the
  interactive loop, so the constraint holds by construction. Documented
  here rather than as a runtime check so a future session doesn't add a
  bulk command without re-reading this.
- **Derived-file regeneration**: `derived/stale.tsv` is regenerated (and
  staged, `_commit_domain_op`/`_commit_criteria_op` now `git add derived`
  too) from every command that can change staleness -- `criteria
  add/edit/retire` (unconditionally, even under `--no-commit`, since a
  criteria change can make decisions stale before the caller ever commits)
  and `screen`/`rescreen` (only when a decision was actually recorded).
  `derived/pool.tsv`/`conflicts.tsv` stay stubs until sub-objective 7.

### 5. Adjudication — done

Spec: `docs/spec/06-workflow-screening.md` §8.

Delivered: `src/strata/protocol/adjudication.py` (`is_adjudicator`,
`conflict_queue`, `record_adjudication`, `record_discussion`), `strata
adjudicate [--stage S] --by <actor>` in `cli/main.py`,
`tests/unit/test_adjudication.py` / `tests/integration/test_cli_adjudicate.py`
(100% line+branch on `adjudication.py`). No verify.py changes needed:
adjudicate events already flow through `_verify_events`'s generic
dangling-record-reference tracking (it reads `body.get("record")`, which
`adjudicate` bodies already have), and `_verify_screen_events`'s citation
checks are screen-event-specific by design (adjudication's own citation
validity is enforced at write time in `record_adjudication`, matching how
`record_screen_decision` works).

- **`criteria_version`/`criteria_digest` on `adjudicate` events**: §4.4's
  event catalog table omits these two fields for `adjudicate`, but §4.1
  (normative) says every `screen` *and adjudicate* event records them. This
  module follows §4.1 and stamps both — see the long comment at the top of
  `adjudication.py` for the reasoning, and note this is exactly what makes
  `protocol.rescreen._resolved_decision`'s adjudication branch (built one
  sub-objective ahead of this one, in sub-objective 4) work without
  modification.
- **Authorization** (§8: "Only actors with the `adjudicator` role or listed
  in `screening.adjudicators` may resolve a conflict") is checked both at
  the CLI layer (fails fast with `EXIT_GUARDRAIL` — the first real use of
  that exit code in this codebase — before any interactive prompt) and
  again inside `record_adjudication` itself (defence in depth, and the only
  check that matters for any future non-CLI caller, e.g. the web UI).
- **Rationale is unconditionally required**, reusing `cli.main.
  _get_required_rationale` (introduced in sub-objective 1 for exactly this
  kind of no-escape-hatch requirement) rather than the general
  `--why`/`git.require_rationale` flow.
- **`own_conflict`**: `record_adjudication` computes this itself from
  whether `actor` appears in `ScreeningState.opinions` for the conflict
  being resolved, rather than trusting a caller-supplied flag — it can't be
  spoofed by a careless CLI/web caller, and it doesn't erase or alter the
  original opinions (§8: "IRR still reflects the original disagreement,
  which is the honest number" — `state.opinions` is untouched by an
  adjudication, only `state.adjudication` is added, verified directly in
  `test_record_adjudication_success_supersedes_opinions_and_stamps_version`).
- **`[d]iscuss`** is a `note` event (`subject: "adjudication-discuss"`),
  the same "free-form, attaches to any entity" reuse sub-objective 4's
  `manual`-staleness marker already established as this codebase's pattern
  for a lightweight annotation that doesn't warrant a new event type.

### 6. IRR — done

Spec: `docs/spec/02-repository-format.md` §6.5, `docs/spec/10-cli.md`
§"Screening" (`strata irr`).

Delivered: `src/strata/protocol/irr.py` (`compute_pair_irr`,
`compute_stage_irr`, `regenerate_irr_json`), `strata irr [--stage S]` in
`cli/main.py`, `tests/unit/test_irr.py` / `tests/integration/test_cli_irr.py`
(100% line+branch on `irr.py`). No `scipy`/`numpy` needed — Cohen's kappa
and PABAK are closed-form 2x2 computations.

- **First opinions only** via `core.fold.fold_first_write` (built in M0
  anticipating this): `test_compute_pair_irr_uses_first_opinion_only`
  proves a reviewer changing their mind after the fact doesn't change the
  IRR numbers, only their *original* independent opinion does.
- **Binary only, `maybe` excluded and counted separately**: the 2x2 table
  and PABAK have no natural three-category form, so a pair comparison only
  counts records where both reviewers' first opinion was a completed
  `include`/`exclude` decision; excluded-for-maybe pairs are reported in
  their own `excluded_maybe` count rather than silently shrinking `n` with
  no explanation.
- **Verified against hand computation, not just internal consistency**:
  `test_compute_pair_irr_matches_hand_computed_2x2_example` uses a 10-record
  2x2 table (5/1/0/4) with `po=0.9, pe=0.5, kappa=0.8, pabak=0.8` computed
  by hand in the test's own docstring and confirmed independently via a
  throwaway interpreter check before writing the test — an actual textbook
  dataset (Landis & Koch) wasn't available without network access, so a
  hand-verified small example serves the same "independently checkable"
  purpose the sub-objective's original plan called for.
- **`kappa` at `pe == 1.0`** (both reviewers always pick the same single
  category, so agreement is total but chance-corrected kappa's denominator
  `1 - pe` is zero): defined as `1.0` rather than raising a division error
  — perfect trivial agreement is still perfect agreement.
  `test_compute_pair_irr_perfect_agreement_pe_equals_one` pins this.
- **`strata irr` is read-only with respect to the event log**: it recomputes
  and rewrites `derived/irr.json` to disk but does not commit, unlike every
  other mutating command in this codebase — it's a report (like `strata
  status`/`strata verify`), not a decision, so there is no natural actor
  attribution or rationale to attach. The written file is picked up by
  whatever commits next (a future screen/rescreen/adjudicate, or a manual
  commit), consistent with "derived files are committed anyway" (docs/spec
  02 P3) without inventing attribution semantics a report command doesn't
  need.

### 7. `strata status` full dashboard + derived views — done

Spec: `docs/spec/10-cli.md` §4.

Delivered: `core/status.py` gained `StageStatus` (per-stage total/resolved/
unscreened/partial/conflicts/stale) and `StatusReport.stages`/`next_action`;
`src/strata/protocol/pool.py` (`regenerate_pool_tsv`, `regenerate_conflicts_tsv`,
`regenerate_all`); `tests/unit/test_pool.py` / additions to
`tests/unit/test_status.py` / `tests/integration/test_cli_more.py` (100%
line+branch on `pool.py`).

- **Dedup's pending-review count is deliberately not in `status`**:
  `dedup.engine.run_dedup` has no dry-run mode — it performs auto-merges as
  a side effect — so calling it from a command that MUST be read-only
  (`strata status`) would silently mutate `records.ndjson`. Left out rather
  than built around; a real dry-run mode for `run_dedup` is a clean,
  self-contained follow-up for whoever next touches `dedup/engine.py`.
- **One consolidated regeneration call**: `protocol.pool.regenerate_all`
  now regenerates all four screening derived views (`pool.tsv`,
  `conflicts.tsv`, `stale.tsv` via `protocol.rescreen`, `irr.json` via
  `protocol.irr`) together. Every CLI mutation point that used to call
  `rescreen_mod.regenerate_stale_tsv` directly (criteria add/edit/retire,
  both `screen` paths, `rescreen`, `adjudicate`) now calls
  `pool_mod.regenerate_all` instead, so a future new derived view only
  needs to be added to one function rather than hunted down across six call
  sites — the exact trace this sub-objective's original plan anticipated
  needing decided at implementation time.
- **`next_action`** priority order (not spec-mandated, this implementation's
  own policy, documented in `core.status._next_action`'s only caller):
  conflicts outrank staleness outrank unscreened work, on the reasoning
  that a conflict blocks progress for two reviewers at once, staleness
  blocks trusting anything downstream of it, and unscreened work is the
  default "keep going" state. `test_compute_status_reports_conflicts_and_stale`
  exercises a repo with both a conflict and an unrelated stale record
  simultaneously to pin that conflicts win.
- **`derived/pool.tsv`'s `stale` column** uses the two-letter/short codes
  `tiab`/`ft` per §6.1's own column spec (not the reason or a boolean),
  joined with a comma when both stages are stale for the same record —
  `test_pool_tsv_marks_stale_columns` covers the cascaded
  `title-abstract` + `full-text` case together.

### 8. `strata audit --criteria` sampling — done

Spec: `docs/spec/06-workflow-screening.md` §4.3.

Delivered: `src/strata/protocol/audit.py` (`all_exclusions`,
`sample_exclusions`), `strata audit --criteria [--sample N] [--seed N]` in
`cli/main.py`, `tests/unit/test_audit.py` /
`tests/integration/test_cli_audit.py` (100% line+branch on `audit.py`).

- **Current standing opinion only**: `all_exclusions` folds each actor's
  screen events last-write-wins per `(stage, record, actor)` before
  filtering to `decision == "exclude"` — a reviewer who excluded and later
  changed their mind is correctly absent from the audit pool, since there
  is nothing live to verify. `test_all_exclusions_reports_current_opinion_only`
  pins this.
- **Reproducibility**: `sample_exclusions` always returns the seed it used
  (freshly generated via `random.SystemRandom` when the caller doesn't
  supply one, echoed back otherwise), and samples from a list pre-sorted by
  `(stage, record_id, actor)` so the result depends only on the seed, never
  on event-file iteration order. The CLI prints `rerun with --seed N to
  reproduce` and accepts `--seed` to do exactly that.
- **Pure review aid, no mutation**: neither the protocol module nor the CLI
  command appends any event or touches `records.ndjson`/derived views — a
  correction found during audit is expected to go through the existing
  `strata fix` (metadata) or `strata rescreen --mark` (re-examine) paths
  rather than a new bespoke mechanism.
- `strata audit` currently only implements `--criteria` (the one variant
  the spec names); calling it without that flag is a usage error naming
  what's missing rather than silently doing nothing.

### 9. E2E scenarios — done

Spec: `docs/spec/14-testing.md` §5; `docs/spec/06-workflow-screening.md` §9
for E2E-01's exact script.

`tests/e2e/test_e2e_01_origin_scenario.py`: the full worked example from §9,
against a real temporary git repository via the CLI (following
`tests/e2e/test_e2e_02_concurrent_clones.py`'s pattern of invoking
`strata` as subprocess or in-process via `typer.testing.CliRunner` — check
which the existing E2E tests use and match it). Assert the *exact* stale
count (180 of 2,918, per the worked example) is more than this test can
promise since the worked example's numbers come from a specific corpus this
repo doesn't have — instead build a smaller synthetic corpus with the same
*shape* (N records, dual screening, an added exclusion criterion that
matches a known subset) and assert the exact stale set for *that* corpus,
which is what "MUST NOT be weakened" actually requires: exactness against
whatever fixture the test defines, not literal reproduction of the
narrative numbers. `test_e2e_04...loosened` (exclusions citing a loosened
criterion go stale, inclusions don't), `test_e2e_05...retired` (cascade +
rescreen), `test_e2e_06...cascading` (title/abstract reversal orphans a
full-text decision — extraction doesn't exist until M3, so this test's scope
is "full-text decision marked stale/orphaned," documented as a partial
implementation of E2E-06 the same way M1 left EndNote/Excel partial;
revisit when extraction lands). `test_e2e_09...interrupt` (SIGKILL mid
`strata screen` session — append-then-fsync-per-decision means the worst
case is losing the *in-progress* decision, never a torn write; assert
`strata verify` still passes and no decision is lost by re-running against
a process killed after N of M decisions).

#### E2E-01 — done

`tests/e2e/test_e2e_01_origin_scenario.py` is in and passing: init, two
actors, two criteria, two searches, two CSL-JSON imports (one exact-DOI
duplicate so dedup does real work), dual screening of all 14 canonical
records, adding EXC-07 mid-review, asserting the exact stale set (all 14 —
see the module docstring for why this test's numbers depart from §9's "180
of 2,918" narrative: the normative §4.2 rule has no per-record content
test, so it can only be exact against a corpus this test itself defines,
never against narrative color from a corpus this repo doesn't have — same
principle as sub-objective 1's version-numbering call), then re-screening
every stale record with both reviewers and asserting a clean, fully
resolved pool.

**A real bug this test caught, not a test-only fix.** Writing the dual-mode
re-screen half of this scenario (both `ethan` and `sam` re-deciding all 14
records, half kept, half newly excluded) surfaced a genuine defect in
`protocol/rescreen.py`'s multi-reviewer staleness model from sub-objective
4: `rescreen_queue` filtered `compute_stale_records`'s *aggregate*
resolved-decision view down to the given actor's assignment. That aggregate
view only exists while the record is currently resolved (`include`/
`exclude`) — the instant `ethan` re-screened a record to `exclude` while
`sam`'s opinion was still the old, stale `include`, `core.fold.resolve_screening`
correctly flipped the record to `conflict`, and `compute_stale_records`
(which only ever considers resolved records, matching §5's reason table
having no "conflict" row) dropped it entirely. `sam`'s own opinion was
exactly as stale as before, but it silently vanished from `sam`'s
`rescreen_queue` — half the queue disappeared mid-workflow, and those
records were stuck as unresolved conflicts with no path back except
`strata adjudicate`, which defeats the entire point of a same-answer dual
re-screen. The E2E test's own Python-level `compute_stale_records` check
(14/14, before either reviewer acted) and the CLI's first (`ethan`)
`rescreen` call both looked correct in isolation; only the *second*
reviewer's call, after the first had already introduced disagreement,
exposed the gap — which is exactly the kind of interaction-order bug a
single-reviewer or synthetic unit fixture won't surface, and the reason
this sub-objective's E2E tests matter beyond the unit-level coverage
sub-objectives 1-8 already have.

The fix (`protocol/rescreen.py`): staleness for `rescreen_queue` purposes is
now evaluated against **that actor's own most recent opinion** directly
(`_effective_opinion(state, actor=<handle>)`), per §4.2's literal
per-decision reading, independent of the record's aggregate resolved/
conflict status. `compute_stale_records` (and therefore `derived/stale.tsv`
and `strata status`'s stage stats) keeps the existing aggregate,
record-level view unchanged (`_effective_opinion(state, actor=None)`,
same earliest-version/union-of-citations heuristic as before) — that
reporting view is still correct and unaffected; only the actor-scoped
rescreen queue needed the fix. Added `test_rescreen_queue_survives_a_dual_reviewer_conflict`
(`tests/unit/test_rescreen.py`) as a focused regression test alongside the
E2E coverage, and `test_rescreen_queue_excludes_a_stale_opinion_after_reassignment`
for the adjacent edge case (an actor's own stale opinion should stop
appearing in their queue once they're reassigned off the record). Removed
the now-dead `_resolved_decision` wrapper it replaced rather than keeping
it as a compatibility shim; `rescreen.py` is back to 100% line+branch
coverage.

**A second, unrelated bug the same test caught.** `strata actor add` and
`strata actor deactivate` mutated `strata.toml` but never committed —
a gap from M0/M1 that no existing test had caught because none of them
checked repository cleanliness after an actor-management call.
docs/spec/04-git-integration.md §2.1 is unconditional ("every mutating
`strata` command produces exactly one commit, unless `--no-commit` is
passed"); this test's final `assert not gitio.is_dirty(root)` — the same
end-of-scenario cleanliness check `test_e2e_07...` already uses — caught
the leftover `strata.toml` diff immediately once the rescreen bug above was
fixed and the test could run to completion. Fixed both commands to build a
`StructuredCommit` and commit `strata.toml` through the same
rationale-eliciting path (`_get_rationale`) every other mutating command
uses (new shared `_commit_manifest_op` helper in `cli/main.py`, mirroring
`_commit_domain_op`'s shape but staging `strata.toml` instead of
`records`/`events`/`derived`). This is a behavior change for every existing
caller of `actor add`/`deactivate`: `git.require_rationale` defaults to
`true`, so both commands now require `--why`/`--why-file` in a
non-interactive context, matching `criteria add`/`search add`/every other
mutating command. Updated every call site across the test suite
(`test_cli_init.py`, `test_cli_screen.py`, `test_cli_irr.py`,
`test_cli_adjudicate.py`, `test_e2e_02_concurrent_clones.py` — the latter
also dropped a manual `gitio.add_all`/`gitio.commit` workaround it had been
using to paper over the missing commit) and added direct coverage
(`test_actor_add_requires_rationale_non_interactively`,
`test_actor_add_no_commit_leaves_working_tree_dirty`,
`test_actor_deactivate_unknown_handle_is_usage_error`) in `test_cli_init.py`.

#### E2E-04, E2E-05, E2E-06, E2E-09 — done

The remaining four E2E scenarios, single-reviewer (assignment defaults to
the one actor when `screening.assignment` is unset) since each is about
criteria/staleness/interruption mechanics, not dual-review interaction —
that ground is E2E-01's alone:

- `tests/e2e/test_e2e_04_loosened_criterion.py`: a 2-record repo, one
  `include` and one `exclude` citing a criterion later loosened. Asserts
  only the exclusion goes stale (`criterion-loosened`), the inclusion is
  untouched, then re-screens and checks the final pool.
- `tests/e2e/test_e2e_05_retired_criterion.py`: 4 records — two exclusions
  citing a criterion that gets retired (the "cascade" §5 calls for: a
  ripple across every decision that relied on it), one exclusion citing a
  *different*, still-active criterion, one plain inclusion. Retiring
  stales exactly the two that cited it; re-screening sends them to
  deliberately different outcomes (one still excluded on separate
  grounds, one promoted to include) to show re-screening isn't a rubber
  stamp. Caught and fixed a test-writing mistake worth noting for anyone
  extending these: `rescreen`'s prompt loop has no note prompt (unlike
  `screen`), so a trailing blank line in scripted input silently
  desyncs the *next* record's choice from `[s]kip`'s default — invisible
  with a 1-item queue (nothing left to desync), a real failure at 2+.
- `tests/e2e/test_e2e_06_cascading_staleness.py`: one record cleared
  through both stages, then a title-abstract tightening. Asserts the
  forward cascade while pending (title-abstract native-stale +
  full-text `upstream-stale`, docs/spec/06 §4.4), then reverses
  title-abstract to `exclude` on re-screen and asserts what §4.4 actually
  promises post-reversal: not a lingering stale flag (extraction is what
  gets permanently marked `orphaned` per `E_ORPHAN_EXTRACTION`, and
  extraction doesn't exist until M3 — same scope reduction M1 documented
  for EndNote/Excel) but retention — the full-text `include` event is
  still there, untouched, in the append-only log, and still visible in
  `derived/pool.tsv`'s `fulltext` column even though `tiab` now governs
  the record excluded.
- `tests/e2e/test_e2e_09_interrupted_screening.py`: the one test in this
  suite that drives a real `strata` subprocess instead of
  `typer.testing.CliRunner` (in-process, can't be SIGKILLed mid-call).
  Feeds one decision, polls stdout for the second record's prompt (proof
  the first was fully processed), `SIGKILL`s, then asserts against
  docs/spec/04-git-integration.md §2.4 directly: the first decision
  survived (appended+fsynced immediately) but nothing was committed
  (batched screening commits only at session end) — repo is correctly
  dirty, `strata verify` still passes (no torn write), and an ordinary
  follow-up `strata screen` session resumes cleanly with each of the 3
  records decided exactly once. Stable across 5 repeated local runs.

Full suite after this sub-objective: 849 passed, 97.8% overall coverage,
`rescreen.py`/every other new-this-milestone module still at 100%
line+branch.

### 10. Screening-latency benchmark — done

Spec: `docs/spec/15-roadmap.md` M2 acceptance ("< 100 ms p95 decision
latency at 50k records"), `docs/spec/13-nonfunctional.md` §1's "screening
decision round trip" row (< 100 ms target, 250 ms hard limit), `docs/spec/14-testing.md` §7.

`tests/benchmark/test_screening_performance.py`, advisory tier like
`test_dedup_performance.py`/`test_import_performance.py` (excluded from
`pyproject.toml`'s `testpaths`, picked up by `ci.yml`'s `benchmark` job via
the `benchmark_50k` marker). Generates a genuine 50,000-record repository,
then calls `record_screen_decision` directly for 1,000 distinct records
spread across the file (the same call `strata screen`'s interactive loop
makes once per decision — the queue itself is computed once per session,
not per decision, so it's correctly excluded as one-time setup, not
"decision latency"), timing each call individually to get a real p95/p99
rather than just a mean.

**This is exactly the bug the earlier planning note above predicted, just
via a different call path than guessed.** The prediction was right that
some full-`records.ndjson` re-read/re-parse per decision would blow the
budget at 50k records; the actual culprit wasn't `write_records` (screen
events are indeed per-actor append-only, never touching `records.ndjson`,
as guessed) but `core.records.get_record` — called once per decision by
`_validate_and_build_body` just to confirm the record being decided
exists, and implemented as `for record in read_records(repo): ...`, i.e. a
full-file `json.loads` of all 50,000 lines on every single decision. First
measurement: **p95 ≈ 497 ms** — 5x the soft target and 2x the hard limit.
Fixed `get_record` itself: a plain substring pre-filter for the raw id
string per line (deliberately *not* anchored to canonical JSON's exact
`"id":"<value>"` spacing, since that assumption turned out to be live —
several existing test fixtures across the suite hand-write NDJSON with
`json.dumps`'s default `": "` spacing rather than going through
`write_records`, and an id-only needle works regardless), `json.loads`
only on the line(s) that might match, with the pre-existing exact
`record["id"] == record_id` check still guarding correctness against any
false-positive substring match. Added
`tests/unit/test_records.py::test_get_record_skips_a_substring_false_positive`
(a hand-written NDJSON fixture with a genuine substring collision in a
nested field, since canonical JSON's own string-escaping makes that
surprisingly hard to trigger through the normal write path) and
`test_get_record_missing_file_returns_none` to keep `records.py` at 100%
coverage through the change. Re-measured: **p95 ≈ 80-90 ms** across 1,000
sampled decisions, comfortably inside the 100 ms target.

Real-world impact beyond satisfying the benchmark: this was a genuinely
felt defect, not just a number on a chart — a reviewer clicking through
`strata screen` on a 50k-record corpus was seeing roughly half a second of
lag per decision before this fix, which would have made the flagship
feature of this milestone feel broken at the exact scale the tool is meant
to handle.

### 11a. Web UI, sitting 1 — done

Spec: `docs/spec/11-web-ui.md` (all of it, normative) — this sitting covers
§1 (posture), §2 (the `/` and `/screen/<stage>` routes), §3 (the screening
surface), §5 (technology), §6 (accessibility, best-effort), §7 (security,
in full). §4 (criteria editor + impact preview) and the rest of §2's route
table are sitting 2 (sub-objective 11b).

**New package**: `strata.web` — `security.py` (session/CSRF tokens,
Origin/Host validation, the inactivity clock), `app.py` (`create_app`
factory + the security middleware + CSP/security headers), `routes.py`
(`/` dashboard, `GET`/`POST /screen/<stage>`), `server.py` (process-level
wiring: actor/host/token resolution, ephemeral port selection, running
uvicorn with a watchdog that actually exits the process on §7's inactivity
timeout rather than just having the middleware start rejecting requests),
`templates/*.html` (Jinja2, server-rendered, `base`/`dashboard`/`screen`),
`static/{style.css,keyboard.js}` (vendored, no CDN, no build step — total
JS is one hand-written ~2 KB file, nowhere near §5's 50 KB budget). New
CLI command `strata serve [--port N] [--host H] [--token T] [--actor A]
[--no-browser] [--inactivity-timeout S]` in `cli/main.py`.

**Security (§7), taken literally, all six bullets:**
- Session token: generated at startup (or `--token`, required whenever
  `--host` isn't loopback), delivered via the opened URL's `?token=`,
  then set as a `SameSite=Strict`, `HttpOnly` cookie on the first response
  that sees it — `SecurityMiddleware` in `app.py`. Deliberately stricter
  than §7's letter: *every* request needs a valid session (the spec only
  requires it on mutating ones), not just POST/PUT/DELETE, since nothing
  about "local" should mean another process or browser tab can read
  repository content without the token either.
- CSRF: the same session token doubles as the CSRF value, embedded as a
  hidden field in every mutating form (`csrf_field_name`, a Jinja global)
  — the standard double-submit-cookie pattern, and one less secret to
  generate/track. A subtlety worth flagging for sitting 2 or anyone else
  touching this: Starlette's `BaseHTTPMiddleware` gives the downstream
  route handler a *different* `Request` object than the one middleware
  sees, so a body the middleware already consumed (`await request.form()`,
  needed to check the CSRF field) cannot be re-read by the route — it
  comes back empty. Fixed by stashing the parsed form on `request.state`
  (backed by `scope["state"]`, shared across both `Request` wrappers) for
  the route to reuse rather than re-parsing.
- `Origin`/`Host` validation (defeats DNS rebinding): `security.py`'s
  `is_host_allowed`/`is_origin_allowed`, checked against the actual
  `--host`/port this process bound to, not a hardcoded assumption.
- Output escaping: Jinja2's autoescaping is on by default and untouched —
  every template interpolation is escaped, so titles/abstracts/notes from
  database exports (routinely containing raw HTML) render as text, not
  markup.
- Path traversal: not yet applicable — this sitting's two routes never
  take a user-supplied filesystem path (PDF locations, import files land
  in sitting 2's `/records`-adjacent screens or later milestones); noted
  here so it isn't forgotten when one does.
- Inactivity timeout: `security.InactivityClock` + `server.py`'s
  `serve_until_idle_or_interrupted`, which runs uvicorn's `Server.serve()`
  alongside a small watchdog coroutine that sets `server.should_exit =
  True` once the clock expires — actually exits the process, not just a
  middleware that starts returning 503. Defaults to 3600s per §7,
  `--inactivity-timeout` for testing/overriding.
- CSP (not itself in §7's bullet list, but directly in its spirit and
  required by §5's "no external requests"): `default-src 'self'` with no
  external origins, plus `X-Content-Type-Options: nosniff`, `X-Frame-
  Options: DENY`, `Referrer-Policy: no-referrer` on every response.

**Screening surface (§3)**, server-rendered HTML with `accesskey`
attributes as the no-JS baseline (§5's hard requirement: the page is fully
operable with `keyboard.js` disabled) and a small keydown handler layered
on top for direct single-key shortcuts matching the spec's mockup (`i`/`e`/
`m` decide, digits 1-9 cite/toggle a criterion and auto-submit when
`require_exclusion_reason` is set — S3, `,` focuses the note field — S13,
`s` skips, `u` undoes). `blind_metadata` hides author/journal/year in the
template (S11); `blind_reviewers` (S10) is satisfied structurally the same
way the CLI already is — nothing in `routes.py` ever reads another actor's
opinion. No-abstract records are visually flagged, never silently skipped
(S9). Progress bar and "N of M" position (S2's spirit — see below on what
"under 100ms" means here).

**Two spec requirements given a stateless, honest reinterpretation** (§1:
"the server is stateless with respect to the repository" — no server-side
session/queue-position tracking):
- **S8** ("closing the tab and returning resumes at the same record") is
  true for free: `/screen/<stage>` always shows the actor's current queue
  (assigned, undecided) head, so whatever was actually decided stays
  decided and whatever wasn't is still there next time, no memory needed.
- **S7** (`u`ndo, repeatable) and "skip"/"navigate" (n/p) needed *some*
  state to mean anything across two separate HTTP requests, so it lives in
  the URL: a successful decision's redirect carries the just-decided
  record forward as `?prev=`, which the next page turns into a `?redo=`
  link to re-open and overwrite that one decision (one level of undo, not
  arbitrary depth); a `?skip=<comma-ids>` list carries forward records the
  reviewer chose not to decide yet, filtered out of the queue for that
  browsing session. Both are genuinely stateless (survive a server
  restart, work with multiple tabs), at the honest cost of the `skip` list
  only lasting as long as the reviewer keeps following links that carry it
  (closing the tab and coming back drops it, same as S8's own no-memory
  premise) and living in a URL query string that would get unwieldy for a
  very long skip run — acceptable for this sitting, flagged for anyone
  who wants a stronger version later.
- **S2** ("decision visibly acknowledged in under 100ms; persistence
  asynchronous but append-before-advance"): this sitting is a plain
  full-page POST-then-redirect (`record_screen_decision` appends and
  fsyncs *before* the 303 response is sent, so "append-before-advance"
  holds exactly), not an async/htmx partial update — htmx wiring is
  explicitly deferred to sitting 2 or later per the technology note below,
  so the "under 100ms, asynchronous" half of S2 is not yet attempted; the
  synchronous round trip itself is fast (the same `record_screen_decision`
  call sub-objective 10's benchmark already measured at p95 ~80-90ms at
  50,000 records).

**Deliberately deferred, not attempted this sitting** (tracked for 11b or
later, not silently dropped): htmx partial-page updates (§5 recommends it;
this sitting is full-page-reload-only, which satisfies §5's *harder*
requirement — working with JS disabled — but not the faster progressive-
enhancement path); vendoring a JS library at all (`keyboard.js` is the
only script, hand-written, no htmx); term highlighting (S6); a full WCAG
2.1 AA audit against real assistive tech (the CSS/markup follow the
letter of §6 — focus rings, semantic HTML/ARIA, 4.5:1-designed contrast
tokens, `prefers-reduced-motion`/`prefers-color-scheme`, a 320px
breakpoint — but this was not tested with a screen reader); a multi-actor
selection *screen* (`--actor` is required outright when more than one
active actor is configured, `resolve_actor` in `server.py`, rather than
an interactive picker); `/rescreen`, `/adjudicate`, `/dedup`, `/records*`,
`/criteria` (+ impact preview), and everything M3-shaped (`/extract/*`,
`/rob/*`, `/analysis/*`, `/prisma`) — all of §2's route table beyond `/`
and `/screen/<stage>`; the §2.4 batched-commit policy for web sessions
specifically (decisions append and fsync immediately, matching E2E-09's
own guarantee for the same call, but nothing yet commits a web session's
batch — a user closes it out via the CLI today, same as before this
sitting existed).

**Testing**: `tests/unit/test_web_security.py` and
`test_web_server.py` (pure logic, 100%/76% branch respectively — the 24%
gap in `server.py` is entirely `serve_until_idle_or_interrupted`, the
function that actually runs uvicorn, which only the subprocess test below
exercises and coverage.py cannot see into a child process without
additional `COVERAGE_PROCESS_START` plumbing this sitting didn't set up);
`tests/integration/test_web_app.py` (FastAPI `TestClient`, in-process ASGI
transport, no real socket — dashboard, screening GET/POST, security
rejections, blinding, skip/undo, 100% on `app.py`/`routes.py`); `tests/
integration/test_cli_serve.py` (the one test in this new surface that
drives a real subprocess, `python -m strata.cli.main serve`, the same
pattern E2E-09 established for `strata screen` under SIGKILL — needed
because `strata serve` blocks running a real server and `CliRunner` can't
touch that: confirms a real HTTP GET against the announced URL works, the
non-loopback-without-token and unknown/ambiguous-actor usage errors, and
that the process actually exits on its own once idle past
`--inactivity-timeout`, stable across repeated local runs). Full suite
after this sitting: 913 passed, 97.5% overall coverage.

New runtime dependency: `python-multipart` (form parsing, required by
Starlette/FastAPI for any `POST` with form-encoded bodies — every mutating
route in this surface). New dev dependency: `httpx2` (this environment's
installed Starlette version deprecated plain `httpx` for
`starlette.testclient.TestClient`).

### 11b. Web UI, sitting 2 — done

Spec: `docs/spec/11-web-ui.md` §4, plus the `/criteria` row of §2's route
table. This is the one web-UI piece the M2 roadmap acceptance checklist
names outright: "The criteria editor's impact preview is correct and
non-mutating" (`docs/spec/15-roadmap.md`).

**New**: `rescreen.preview_criterion_change_impact(repo, *, criterion_id,
direction, origin="edited")` in `protocol/rescreen.py` — layers one
hypothetical `CriterionChange` (at `current_version + 1`, the version the
change *would* create) on top of the real change history and runs the
exact same `evaluate_staleness` evaluation `compute_stale_records` runs
for a change that actually happened, without ever calling
`edit_criterion`/`retire_criterion` or touching disk. `_compute_stale`
(the function both `compute_stale_records` and `rescreen_queue` already
shared) grew two new optional parameters, `extra_changes`/
`version_override`, defaulting to a no-op so neither existing caller's
behavior changed. `origin="retired"` previews a retirement — direction is
irrelevant there, matching `CriterionChange.effective_direction`'s own
origin-overrides-direction rule, the same as a real retirement.

**New web routes**: `GET /criteria` (list, active/retired status, links to
edit/retire), `GET`/`POST /criteria/<id>/edit` (direction radios +
definition textarea + live preview + rationale + save), `GET`/`POST
/criteria/<id>/retire` (same shape, direction fixed to the retirement
case). The "live" part of the preview (§4: "MUST update as the direction
radio changes") is a plain GET resubmit as the no-JS baseline — changing
the radio doesn't do anything without JavaScript until the reviewer clicks
"Preview" — plus a small, generic addition to `keyboard.js`
(`data-auto-submit-on-change`, opted into per form) that auto-resubmits
via the `formmethod="get"` "Preview" button the instant the radio changes,
so with JavaScript enabled it does feel live. Values already typed into
the definition/rationale fields are carried forward through a preview
refresh via query parameters, rather than reset to the on-disk value each
time — a GET request that just so happens to also carry those two fields
along for the ride, functionally harmless since preview computation never
reads them.

Saving reuses the identical rationale validation
(`core.commit.validate_rationale`) and structured-commit shape
(`cli.main._commit_criteria_op`'s pattern, restated for the web layer as
`routes._commit_criteria_change` — regenerate derived views, then one
commit staging `protocol/criteria.yaml`/`events/criteria`/`derived`) the
CLI already uses, so `strata criteria edit`/`retire` and the web editor
produce indistinguishable history. Unlike screening decisions (see 11a's
note on the deferred batched-commit policy), a criteria save always
commits immediately — it is one deliberate, already-confirmed action with
its own rationale, not one of many decisions accumulating in a session.

**Testing**: `tests/unit/test_rescreen.py` gained six tests for the
preview function, including one that asserts it against the *real*
post-edit `compute_stale_records` result (not just its own internals) and
one confirming two consecutive preview calls never bump
`criteria.yaml`'s version — `rescreen.py` stayed at 100% line+branch
through the change. `tests/integration/test_web_criteria.py` (16 tests:
list, preview for each direction including the "no impact" tightened-vs-
exclusion case docs/spec/06 §4.2 predicts, non-mutation across all four
directions, value carry-forward, save+commit, rationale/CSRF/unknown-
criterion rejections, retire-already-retired) plus `routes.py` staying at
100% combined with 11a's existing tests. Full suite after this
sub-objective: 935 passed, 97.5% overall coverage.

### 11c. Web UI, sitting 3 — done (`/rescreen`, `/adjudicate`, `/records*`, `/history`, `/dedup`)

Spec: `docs/spec/11-web-ui.md` §2's `/rescreen`, `/adjudicate`, and
`/dedup` rows, §3.2 (re-screening mode).

**`/rescreen/<stage>`**: the same statelessness/skip/undo design as
`/screen/<stage>` (11a), plus the prior decision and staleness reason
shown prominently and a fourth `[k]eep previous` action (§3.2) that
re-submits the record's own `prior_decision`/`prior_criteria` from
`rescreen_queue`'s current snapshot rather than asking the reviewer to
re-enter them. One genuine design difference from `/screen`, not an
oversight: `/screen`'s "N of M" has a stable M (everything *assigned*)
with N climbing; `/rescreen` has no separate "assigned" set to anchor M
to — `rescreen_queue`'s own size *is* M, and it shrinks as the reviewer
works through it (1 of 14, then 1 of 13, ...). Both are accurate at every
page load; they're just shaped differently, a direct consequence of
`/rescreen` having no state independent of what's currently stale.
Decisions batch the same way `/screen`'s do (appended immediately,
committed later — see 11a's commit-policy note) since a rescreen session
is still fundamentally a session of many small decisions, not one
deliberate action like a criteria edit.

**`/adjudicate/<stage>`**: shows every contributing opinion (actor,
decision, cited criteria, note) side by side, `[i]nclude`/`[e]xclude` with
citation checkboxes, and an unconditionally required rationale (`docs/spec/06`
§8: no `git.require_rationale` escape hatch, matching
`record_adjudication`'s own enforcement). A non-adjudicator sees the
conflict read-only with an explanation rather than a form that would just
be rejected server-side on submit — `is_adjudicator` is checked for
display, but the actual authorization boundary stays entirely in
`record_adjudication` itself, not duplicated client-side. Unlike
`/screen`/`/rescreen`, an adjudication commits immediately per resolution
(matching `/criteria`'s policy, 11b): it is one deliberate, already-
justified action, not one of many decisions accumulating in a session,
and there's no "undo" here either — resolving a disagreement is a one-way
action, not a routine re-decision.

Both screens reuse `keyboard.js` (added a `k`ey binding for `[k]eep
previous`) and the existing `screen-form` id, so the same single-key
shortcuts and CSS work without new client code.

**`/records`** (searchable/filterable table) and **`/records/<id>`**
(detail + `strata why` provenance timeline) reuse `core.filters` (the
same expression language as `strata records --filter`, §10-cli.md §3;
note the grammar's `==` for equality, not `=`) and
`core.provenance.build_provenance` respectively — both read-only, no new
write paths. A syntax error and an evaluation error (a well-formed filter
referring to a field not resolvable, e.g. one of the fields §10-cli.md
notes as not yet implemented) are distinct failure modes, both surfaced
in-page rather than as a 500. **`/history`** reuses
`core.logcmd.domain_log`, i.e. `strata log`'s own data path
(`Strata-*` commit trailers), with the same `actor`/`stage` filters.

**`/dedup`** (duplicate review queue) needed one piece of genuinely new
infrastructure the other three didn't: `dedup.engine.run_dedup` always
writes its auto-merges as a side effect, so it couldn't back a `GET`
without violating HTTP safety. Added `dedup.engine.preview_dedup`, a
non-mutating dry run sharing `run_dedup`'s exact classification pass — the
loop was extracted into a private `_compute_dedup` that returns what
*would* be written (the canonical-record map, the absorbed-record list,
the pending merge events) instead of writing it; `run_dedup` now just
calls `_compute_dedup` and persists the result, `preview_dedup` calls it
and returns the outcome untouched. `GET /dedup` renders that preview: the
review queue one pair at a time (same skip-list statelessness as
`/adjudicate`, no undo, for the same reason — a merge or keep-both
decision is one-way), plus an informational "N pairs would auto-merge on
the next run" list. Two deliberate `POST`s, each its own rationale field:
`/dedup/run` (the real auto-merge pass) and `/dedup/decide` (resolve one
reviewed pair — `merge` or `keep`, re-validated against a fresh
`preview_dedup` rather than trusting the form round-trip, since the queue
can have moved since the page was rendered). Unlike `/adjudicate`'s and
`/criteria`'s unconditional rationale requirement, dedup's rationale
follows `git.require_rationale` (default `True`) — the spec doesn't
mandate one unconditionally here (docs/spec/04 §2.3), matching
`cli.main._get_rationale`'s existing config-dependent behaviour rather
than `_get_required_rationale`'s. The dedup form intentionally does not
reuse `id="screen-form"`/the `m`/`k` keys `keyboard.js` already hardcodes
for `/screen`'s `maybe` and `/rescreen`'s `keep previous` — "merge" and
"keep both" are different decisions that happen to want the same
letters, so the dedup page relies on plain `accesskey` attributes only
(§5's no-JS baseline already requires these to work standalone) rather
than extending the shared script's hardcoded key map for a third,
differently-shaped form.

**Testing**: `tests/integration/test_web_rescreen.py` (12 tests: unknown
stage, empty queue, prior decision/reason display, keep-previous,
new-decision-with-citation, CSRF, re-keeping an already-resolved record,
skip, redo, invalid criterion, skip-carried-into-redirect),
`tests/integration/test_web_adjudicate.py` (10 tests: unknown stage, no
conflicts, both opinions shown, non-adjudicator view/rejection, resolve +
commit, missing rationale, CSRF, skip, skip-carried-into-redirect),
`tests/integration/test_web_records.py` (8 tests: list-all, filter
narrows, filter with no matches, invalid filter syntax, filter evaluation
error, links to detail pages, detail shows metadata + provenance, unknown
id is 404), `tests/integration/test_web_history.py` (4 tests: shows
every commit, filter by actor, filter by actor with no matches, filter by
stage), and `tests/integration/test_web_dedup.py` (17 tests: nothing
pending, shows a review candidate, `GET` is verifiably non-mutating,
candidate-pairs-considered summary, merge commits and resolves, keep-both
is sticky, no-longer-pending pair rejected, unknown decision rejected,
rationale required/not-required by config, CSRF on both `POST` routes,
skip carried into redirect and honored on `GET`, real auto-merge run
commits, a no-op run doesn't commit, run rejected without rationale).
`dedup.engine`'s new `_compute_dedup`/`preview_dedup` also picked up
direct unit coverage in `tests/unit/test_engine.py` (preview matches
`run_dedup`'s classification, preview never writes anything, preview
never consumes a pair a subsequent real run would still judge, chained
auto-merges preview correctly) — both `dedup/engine.py` and `web/
routes.py` are at 100% line+branch.

**Still open**: htmx partial updates for S2's "asynchronous" half, and
the §2.4 batched-commit policy for web screening/rescreening sessions
specifically (still "append immediately, commit later via the CLI," as
of 11a) — both pre-existing, tracked gaps, not new ones from this
sitting.

### 12. Traceability, roadmap acceptance pass, docs polish — done

**Traceability** (`scripts/traceability_report.py`, docs/spec/14-testing.md
§10.5): 26/38 identified requirements covered. Every one of M2's own
"suite additions" (`docs/spec/15-roadmap.md`'s M2 entry) is covered: P10
(`tests/property/test_staleness_properties.py`, both the brute-force
match and the nonempty-cause-set property), E2E-01/04/05/06/09, and the
screening-latency benchmark (E2E-11's row, since the benchmark itself is
the 50k-record-performance requirement, already covered from M1). The 12
remaining uncovered ids (P11, P12, E2E-03/08/10/12,
`E_DERIVED_DRIFT`/`E_ORPHAN_EXTRACTION`/`E_MISSING_EXTRACTION`/
`E_COUNT_RECONCILE`/`E_UNIT`/`E_EFFECT_INPUTS`) are all extraction/
analysis/count-reconciliation (M3+) or cross-platform-determinism/
migration scope M2 never claimed — reported, not hidden, matching
`docs/m1-plan.md` sub-objective 8's own precedent of leaving genuinely
out-of-scope ids uncovered rather than padding the number.

**M2 acceptance checklist** (`docs/spec/15-roadmap.md`), run end to end:

| Bullet | Result |
|---|---|
| E2E-01 passes | **pass** — exact stale set, dual re-screen, clean final pool |
| E2E-04, E2E-05, E2E-06 pass | **pass**, all three |
| P10 passes against the brute-force reference | **pass** |
| Screening session < 100 ms p95 decision latency at 50k records | **pass** — measured p95 ≈ 66-90 ms across repeated runs in this sandboxed environment (sub-objective 10's benchmark, 1,000 sampled decisions), comfortably inside the target with the 250 ms hard limit further still |
| Criteria editor's impact preview is correct and non-mutating | **pass** — `preview_criterion_change_impact` asserted against the real post-edit result, and against `criteria.yaml`'s version never moving across repeated preview calls (sub-objective 11b) |
| Usability: three non-git users complete a screening session unaided | **not run** — genuinely requires human sessions with people who have not used the tool, screen-recorded with consent (`docs/spec/14-testing.md` §8); out of scope for an unattended agent session, exactly as M1 never claimed to satisfy its own usability bullet either. Left as an explicit open item for a human to run before treating M2 as fully released, not silently dropped. |

Five of six acceptance bullets are met by this session's work; the sixth
needs people. `strata screen`, `strata rescreen`, the web dashboard, and
the web screening/criteria-editor surfaces are all real enough at this
point that running that usability session is now genuinely actionable,
which wasn't true before this milestone.

**Full suite at the point every acceptance bullet above was confirmed**:
935 passed, 97.5% overall coverage, `ruff format`/`ruff check`/`mypy src`
all clean (work continued afterward into sub-objective 11c's `/rescreen`/
`/adjudicate` screens, bringing the count to 957 passed by the time this
file was last updated — none of that later work changes any acceptance
result above, since all six bullets were already decided before it
started). Every module this milestone touched is at 100% line+branch
coverage except `web/server.py` (76% — the uncovered lines are
`serve_until_idle_or_interrupted`, the function that actually runs
uvicorn, exercised for real by `tests/integration/test_cli_serve.py`'s
subprocess test but invisible to `coverage.py` inside a child process
without additional `COVERAGE_PROCESS_START` plumbing this milestone didn't
set up) and `cli/main.py` (90% — a pre-existing characteristic of that
module across M0/M1 too: a thin CLI-argument-adapter layer with many small
error branches, not something this milestone changed the shape of).

**Retrospective: real bugs this milestone's own tests found**, beyond
what was asked for — each is detailed in its own sub-objective's write-up
above, collected here since a reader skimming just this final section
should see them:

1. **Dual-reviewer rescreen queue loses half its queue** (sub-objective
   9, caught by E2E-01): `rescreen_queue` filtered the aggregate
   resolved-decision view, which silently drops a record the instant one
   dual reviewer's fresh opinion disagrees with the other's still-stale
   one. Fixed by evaluating staleness per actor's own opinion.
2. **`strata actor add`/`deactivate` never committed**, violating
   docs/spec/04 §2.1's "every mutating command produces exactly one
   commit" (sub-objective 9, also caught by E2E-01's own end-of-scenario
   cleanliness check). Fixed with a new `_commit_manifest_op` helper.
3. **Screening decision latency ≈497 ms at 50,000 records** (sub-
   objective 10, caught by the new benchmark before it was ever measured
   against real scale): `core.records.get_record` re-parsed every line of
   `records.ndjson` on every single decision. Fixed with a cheap
   substring pre-filter; re-measured at p95 ≈ 66-90 ms.

None of these three were hypothetical or theoretical — the first two
would have made dual-mode re-screening and basic team-management
bookkeeping actively broken in real use, and the third would have made
the flagship feature feel sluggish at exactly the scale
`docs/spec/13-nonfunctional.md` says the tool must handle. All three were
caught by tests written to satisfy this milestone's own spec-fidelity
requirements, not by a separate audit pass — the intended effect of
"follow the spec and keep coverage high" as a standing instruction, not
just a slogan.

**Docs polish**: this file (`docs/m2-plan.md`) itself is the primary
artifact — every sub-objective has a "done" write-up with the spec
sections it implements, the interpretation calls it made and why, and
what it deliberately left out. `docs/spec/` itself needed no changes
(`scripts/check_docs.py` passes: no broken relative links, no broken
anchors, every fenced toml/yaml/json block parses, `docs/spec/README.md`
stays in sync) — this milestone's spec-interpretation decisions were
about filling in genuinely underspecified implementation choices (the
multi-reviewer staleness aggregation model, the web session's stateless
undo/skip design, the sitting split itself), not correcting the
specification.

**What remains after M2**, tracked explicitly rather than silently
dropped: sub-objective 11c (the `/rescreen`, `/adjudicate`, `/dedup`,
`/records*`, `/history` web screens — valuable, not acceptance-gating),
the usability session above, and everything M3 (full text and
extraction) already assumes as a starting point.
