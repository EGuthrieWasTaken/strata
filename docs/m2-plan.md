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
| 3 | Screening core + CLI: `protocol/screening.py`, `screen`/`assign` events, `strata screen`/`strata assign` | not started |
| 4 | Rescreen + cascading staleness: `strata rescreen`, `derived/stale.tsv`, upstream-stale cascade | not started |
| 5 | Adjudication: `strata adjudicate`, `adjudicate` event, role/rationale enforcement | not started |
| 6 | IRR: `derived/irr.json`, Cohen's kappa/PABAK, `strata irr` | not started |
| 7 | `strata status` full dashboard + `derived/pool.tsv`/`conflicts.tsv` regeneration | not started |
| 8 | `strata audit --criteria` sampling workflow | not started |
| 9 | E2E scenarios: E2E-01 (origin), E2E-04, E2E-05, E2E-06, E2E-09 | not started |
| 10 | Screening-latency benchmark (<100ms p95 @ 50k) | not started |
| 11 | Web UI: `strata serve` — dashboard, screening, rescreen, adjudicate, criteria editor w/ impact preview | not started |
| 12 | Traceability updates, roadmap acceptance pass, docs polish | not started |

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

### 3. Screening core + CLI

Spec: `docs/spec/06-workflow-screening.md` §1-§2, §7,
`docs/spec/02-repository-format.md` §4.3 (fold resolution — already
implemented in `core/fold.py`), `docs/spec/10-cli.md` §"Screening".

`src/strata/protocol/screening.py`: reads `events/screen/<stage>.*.ndjson`
per actor, calls `core.fold.resolve_screening` per `(stage, record)` using
`assigned` from `strata.toml`'s `[screening.assignment]` (or all
non-inactive actors with role `screener`/`lead` if unset), returns per-record
`ScreeningState`. `record_screen_decision(repo, *, stage, record, decision,
criteria, note, actor, confidence=None)` validates: `decision` is one of
`include|exclude|maybe`; `require_exclusion_reason` (from config) rejects an
`exclude` with no `criteria` (this is `E_EXCLUSION_NO_CRITERION`, add to
`verify.py` too); every cited criterion must be `status: active` and have
`stage` in its `applies_at` (`E_CRITERION_STAGE`, also add to `verify.py`).
Stamps `criteria_version`/`criteria_digest` from the *current* criteria file
at decision time, appends a `screen` event. `strata screen <stage>
[--filter EXPR] [--limit N]`: an interactive per-record loop (`i`/`e`/`m`
decide, digits cite criteria per §7's table, `u` undo via a correcting
append — not a delete, since events are append-only; "undo" here means "let
the reviewer immediately re-decide," which is just another `screen` event,
last-write-wins already handles it) over records `unscreened` or `partial`
for the current actor at that stage, ordered deterministically (by record
id) so `--limit` and resumability are well defined. `strata screen
--decisions <file>` per `docs/spec/10-cli.md` §5: TSV `record_id decision
criteria note`, attributed to `--by`, `imported: true` in the event body.
`strata assign <stage> --actors a,b [--filter EXPR]`: `assign` event
(`stage`, `records` or `filter`, `actors`); only meaningful once
`[screening.assignment]` isn't authoritative for a filtered subset — keep
`resolve_screening`'s `assigned` computation checking assign events layered
over the config default. Full-text stage additionally requires >=1 citation
on exclude regardless of `require_exclusion_reason` (§7, "Full-text
screening additionally MUST... require at least one criterion on
exclusion").

### 4. Rescreen + cascading staleness

Spec: `docs/spec/06-workflow-screening.md` §4.4, §6.

Wire sub-objective 2's pure rules to real repository state:
`protocol/staleness.compute_stale_records(repo, stage)` — for each resolved
(`include`/`exclude`) or `maybe` decision at `stage`, gather the criteria
changes between its `criteria_version` and the current version restricted to
`stage`, call the pure staleness predicate. Then cascade (§4.4): any record
whose `title-abstract` decision is stale gets its `full-text` decision (if
any) marked stale too, reason `upstream-stale`, *without* recomputing
full-text's own criteria-change staleness first (upstream-stale is
additional to, not a replacement for, a full-text-native staleness cause —
if both apply, prefer the more specific native reason and only fall back to
`upstream-stale`). Regenerate `derived/stale.tsv` (columns per
`docs/spec/02-repository-format.md` §6.4) as a pure function over the fold
result, written by the CLI command, matching `derived/pool.tsv`'s stub
pattern from `core/init.py`. `strata rescreen [--stage S]`: opens the stale
queue (deterministic order), shows the prior decision and the specific
reason (§6's worked UI), `[i]/[e]/[m]` re-decide (a fresh `screen` event at
the new criteria version, which by construction has `criteria_version ==
current` and so folds to not-stale), `[k]eep previous` appends an identical-
decision `screen` event at the new version (also clears staleness — same
mechanism, no special case needed). Implement the `--i-have-reviewed-these`
guard: `strata rescreen` MUST NOT offer a bulk "keep all" without this flag
plus a rationale (§6) — since there's no bulk keep-all command being built
here at all (each `[k]` press is one record), this constraint is satisfied
by construction; add a test that documents *why* there's no bulk-keep
command rather than a runtime guard, so a future session doesn't add one
without re-reading this constraint. `manual` staleness reason: `strata
rescreen --mark <records>` lets a user force a record stale outside the
criteria-change mechanism (e.g. "actually, re-check this one") — implement
as appending a special `screen`-adjacent marker; simplest correct approach
is a `note`-style flag consumed by `compute_stale_records` — decide the
concrete mechanism when writing this (a small addition, not a redesign).

### 5. Adjudication

Spec: `docs/spec/06-workflow-screening.md` §8.

`src/strata/protocol/adjudication.py`: `record_adjudication(repo, *, stage,
record, decision, criteria, rationale, actor)` — rationale is REQUIRED
(unconditionally, unlike the general `--why` flow, since §8 says "A
rationale is REQUIRED for adjudications" with no config escape hatch);
raises if `actor` is not in `screening.adjudicators` and does not have role
`adjudicator`/`lead`. Appends `adjudicate` event
(`stage`,`record`,`decision`,`criteria[]`,`rationale`,`supersedes[]` — the
opinion event ids it resolves, from `ScreeningState.opinions`). `strata
adjudicate [--stage S]`: iterates records in `conflict` state (from
`resolve_screening`), renders both opinions with actor/date/note (§8's
worked UI), `[i]/[e]` decide, `[d]` discuss (a `note` event, conflict stays
open — verify `note`'s event body/schema needs `subject`/`text` per
`docs/spec/02-repository-format.md` §4.4, already in the enum), `[s]` skip.
Note (and surface in `strata report`'s eventual output, out of scope here
beyond recording it) when the adjudicator is one of the two original
screeners for that record (§8: "MUST be noted in the event, and `strata
report` MUST count it") — add an `own_conflict: bool` field to the
`adjudicate` event body.

### 6. IRR

Spec: `docs/spec/02-repository-format.md` §6.5, `docs/spec/10-cli.md`
§"Screening" (`strata irr`).

`src/strata/protocol/irr.py`: per stage, per reviewer pair, compute raw
percent agreement, Cohen's kappa, PABAK (prevalence-and-bias-adjusted
kappa), and the 2x2 table — over **first opinions only**
(`core.fold.fold_first_write`, already built for exactly this). Only
records both reviewers in the pair have screened count. Regenerate
`derived/irr.json` (GENERATED, per §6.1's sibling views). `strata irr
[--stage S]` prints the table; `--json` emits the same structure written to
disk. This is a small, pure-math module (no `scipy`/`numpy` needed — kappa
is a closed-form 2x2 computation) — unit test with hand-computed expected
values from a textbook example (e.g. Landis & Koch's worked kappa example)
so the numbers are independently checkable, not just internally consistent.

### 7. `strata status` full dashboard + derived views

Spec: `docs/spec/10-cli.md` §4.

Extend `core/status.py`'s `StatusReport` with the screening/dedup/stale
sections from the worked example (dedup pending-review count already
computed by `dedup.engine`, just not surfaced in status yet; per-stage
resolved/unscreened/conflicts/stale counts from sub-objectives 3-4; a
"NEXT" line naming the single most actionable command, e.g. `strata
rescreen` with an ETA from recent per-record timing — timing data needs
`screen` events' timestamps, a simple mean of consecutive deltas is
sufficient, no need for anything fancier). Wire `derived/pool.tsv` (one row
per canonical record, `tiab`/`fulltext`/`stale` columns from the fold) and
`derived/conflicts.tsv` regeneration to real state; both were `init.py`
stubs (header row only) until this lands. Regenerating derived views on
every mutating screening command (not just on `strata status`) keeps
`git diff` on `derived/pool.tsv` meaningful per
`docs/spec/02-repository-format.md` P3 — decide the exact trigger point
(likely: every command in `cli/main.py` that appends a `screen`/`adjudicate`
event also calls a shared `regenerate_derived(repo)` helper) when
implementing.

### 8. `strata audit --criteria` sampling

Spec: `docs/spec/06-workflow-screening.md` §4.3.

A deterministic-but-unpredictable-to-the-user random sample (seeded from
something stable per invocation, e.g. `--seed`, defaulting to a fresh
seed printed so a run is reproducible on request) of past `exclude`
decisions, re-presented for the auditor to confirm the cited criterion
still looks right. `strata audit --criteria --sample N`. This is a review
aid, not a mutating command by default — no event emitted unless the
auditor explicitly corrects something, which routes through existing
`strata fix`/re-screen mechanisms rather than inventing a new one.

### 9. E2E scenarios

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

### 10. Screening-latency benchmark

Spec: `docs/spec/15-roadmap.md` M2 acceptance ("< 100 ms p95 decision
latency at 50k records"), `docs/spec/14-testing.md` §7.

`tests/benchmark/test_screening_performance.py`, advisory tier like
`test_dedup_performance.py`/`test_import_performance.py` (excluded from
`pyproject.toml` `testpaths`, picked up by `ci.yml`'s `benchmark` job).
Generate 50k records, screen a sample via the same code path
`record_screen_decision` uses (not a synthetic shortcut), measure per-call
latency, assert p95 < 100ms. If this fails, profile before concluding
architecture is wrong — `read_records`/`write_records` re-reading/rewriting
the *entire* `records.ndjson` on every single-decision `screen` command
would obviously blow this budget at 50k records, unlike dedup/import which
batch; screening is fundamentally a per-record trickle, so the on-disk
format for screen events (per-actor append-only, no read-modify-write of a
shared file) already avoids that trap — the risk is more likely in
`resolve_screening` being called naively over the whole fold on every single
decision instead of incrementally. Budget real profiling time here.

### 11. Web UI: `strata serve`

Spec: `docs/spec/11-web-ui.md` (all of it, normative).

The single largest remaining sub-objective. FastAPI + Jinja2 + htmx per §5,
127.0.0.1-only by default, session token + CSRF + Origin/Host validation per
§7, keyboard-first screening surface per §3, criteria editor with
non-mutating live impact preview per §4 (compute stale-count preview by
running sub-objective 4's `compute_stale_records` against a *hypothetical*
direction without writing anything — the preview function must take the
proposed change as a parameter rather than reading it from a committed
`criteria.yaml`), WCAG 2.1 AA per §6. Routes at minimum: `/`, `/screen/<stage>`,
`/rescreen`, `/adjudicate`, `/criteria` (editor + preview). `/dedup`,
`/records`, `/records/<id>`, `/history` can reuse M1 data and are lower
risk to add alongside. Given the size, consider splitting this into two
sittings: (a) server scaffold + dashboard + screening surface + security
baseline, (b) rescreen/adjudicate/criteria-editor screens. Update this
table with two rows if that split happens.

### 12. Traceability, roadmap acceptance pass, docs polish

Re-run `scripts/traceability_report.py`, confirm P10 and the new E2E ids
show covered. Run the M2 acceptance checklist from
`docs/spec/15-roadmap.md` end to end and record results here the way
`docs/m1-plan.md` sub-objective 8 did (exact numbers, any bugs found and
fixed). Usability testing with three non-git users (§8 of
`docs/spec/14-testing.md`) is out of scope for an unattended agent session
— note it explicitly as an open acceptance item for a human to run, same
as M1 never claimed to satisfy usability sessions itself.
