# Using AI in a review

`strata` is not an AI product and ships no model. It makes no network call and holds no key. What it does
offer is an honest place for the AI your review may already be using: the reviewers decide **whether,
where and how far** an AI assistant may take part, and wherever one does, the record says so. It names the
model and the person who started it, keeps its work apart from the people's, and carries all of it into the
Methods text.

AI participation is **off by default**. A review that never turns it on behaves exactly as it always has,
and nothing in it changes format.

> **Scope.** This page covers the policy, registering a model, suggestions, counting an assistant as a
> reviewer, the generated disclosure, the audit and revoking. How an assistant is connected is
> [The web interface](The-Web-Interface#also-available-to-ai-assistants); what this cannot do is in
> [Known limitations](Known-Limitations).

## What is and is not recorded

| Recorded, and covered by the event's hash | Not recorded, because `strata` cannot know it |
|---|---|
| The **model name**, exactly as the assistant reported it | That the name is true: it is the assistant's own claim, and `strata` says "self-reported" wherever it shows it |
| The **client** (name and version) the assistant connected through, when it said | How good the assistant's work was |
| The **person** who started the assistant's session, who is responsible for it | What prompt or settings it ran with |

An assistant's events are written under its **own handle** (`claude-opus`), in its own files, never under a
person's. Someone who edits an assistant's event out of its file, or a person's event into an assistant's
handle, is caught by `strata verify`.

## Turning it on

Enabling is a lead's decision and a commit like any other, with the lead's reason in it:

```
strata --why "Piloting AI suggestions on screening, as the protocol allows" ai enable
```

```
enabled AI participation (upgraded from format 1); every kind of work is off. Next: `strata ai policy KIND suggest` and `strata actor add NAME --kind agent --model MODEL`
```

That one commit does two things: it moves the review to **format 2** (below), and it adds this to
`strata.toml`:

```toml
[ai]
enabled = true

[ai.policy]
screening = "off"
extraction = "off"
# ... every kind of work, all "off"
```

Nothing has changed for anyone yet. Running it again says so and records nothing.

## The policy: what, and how far

The review sets a **mode** for each kind of work, so a review that welcomes help with screening need not
welcome an assistant editing its criteria.

| Mode | What an assistant may do |
|---|---|
| `off` | Nothing. The default for every kind of work |
| `suggest` | Propose. A person decides, and only then does anything take effect |
| `count` | Act. Its work takes effect directly, recorded as the assistant's and reported as such |

| Kind of work | Covers |
|---|---|
| `screening` | Include, exclude or maybe decisions at any stage |
| `extraction` | Filling the coding form |
| `risk-of-bias` | Risk-of-bias judgements |
| `retrieval` | Recording whether a full text was obtained |
| `studies` | Grouping reports into studies and splitting them |
| `dedup` | Deciding whether two records are the same paper |
| `records` | Correcting a record's fields, and notes |
| `search-import` | Recording searches and importing exports |
| `criteria` | Adding, editing and retiring eligibility criteria |
| `adjudication` | Resolving conflicts between reviewers |
| `analysis` | Running analyses and generating the PRISMA diagram and reports |

```
strata ai policy
```

```
AI participation is enabled for this review
  screening      off
  extraction     off
  ...
  suggestions are shown after-own-decision
```

Set one kind, with your reason; this too is a commit, and the old and new modes are in it:

```
strata --why "Piloting AI suggestions on screening" ai policy screening suggest
```

```
set screening: off -> suggest
```

`strata ai policy screening` shows one kind's mode. `strata log` lists every change to the policy, so the
history of the policy is the history of the review's stance on AI. **Only a person can change it, from the
command line or the web interface.** No assistant can widen its own permissions.

A policy needs AI to be enabled first. Setting a mode before `strata ai enable` is refused and says so.

### Some policies

These are stances, not recommendations: the review decides. Each is a few `strata ai policy` commands, and
each can be changed later.

**Suggestions only, on screening.** The most common starting point. The assistant proposes; a person decides
every record, and nothing the assistant says can change a count.

```
strata --why "Piloting AI suggestions on screening" ai policy screening suggest
```

**Suggestions on screening, a helper on retrieval.** Recording whether a full text was obtained is clerical,
and there is no judgement to protect.

```
strata --why "Screening suggestions only; retrieval is clerical" ai policy screening suggest
strata --why "Let the assistant record retrieval outcomes" ai policy retrieval count
```

**An assistant as the second screener.** The assistant's screening takes effect as its own. It fills a
reviewer's place only on the records a person assigns it to, so a disagreement with a person goes to an
adjudicator like any other, and every figure that involves it is reported apart.

```
strata --why "Second screener for the pilot batch, with a human adjudicator" ai policy screening count
strata --why "Assign the assistant to the pilot batch" assign title-abstract --actors ethan,claude-opus --by ethan
```

Some things are deliberately not in a policy: whether to let an assistant change the criteria or adjudicate
(`criteria` and `adjudication` can be set to `count`, and a change to the criteria is still a protocol
amendment that the review-repository CI labels), and whether AI is acceptable at all. That is the reviewers'
call; `strata` makes it visible and reportable.

## Registering the models you accept

A review accepts specific models, registered the way people are. An assistant whose reported model is not
registered is refused, and the refusal tells whoever is running it how to accept it.

```
strata --why "Accepting Claude Opus as a screener" actor add claude-opus "Claude Opus" --kind agent --model claude-opus-5-5 --role screener
```

```
strata actor list
```

```
ethan            Ethan                    lead
claude-opus      Claude Opus              screener  [AI agent; model claude-opus-5-5 (self-reported)]
```

The rules:

- The **model name must match exactly**. A provider that quietly moves `...-latest` to a new model produces
  a different name, and it is refused rather than absorbed. You decide when to accept the new one.
- An assistant cannot be a `lead`.
- One model can be registered for one active assistant, so a reported name always means exactly one handle.
- An assistant can only be registered after `strata ai enable`.
- It is removed with `strata ai revoke`, not `strata actor deactivate`, because losing standing is more than
  switching a role off. `actor deactivate` on an assistant says so.

## Suggestions: what an assistant proposes

In `suggest` mode an assistant does not change the review. It **proposes**, and a proposal waits for a
person. A suggestion is checked exactly as the real action would be (an exclusion without a criterion is
refused for the reason a real exclusion would be), is recorded with the assistant's reason, and then changes
nothing: not the pool, not the conflicts, not the PRISMA counts, not what is stale. Suggestions are counted
in the ledger and the generated disclosure, never as decisions.

```
strata suggestions list --by ethan
```

```
ev_01m6n1qdfcxrgx51n08m67wp6f  screening    include rec_0000000000000001 at title-abstract
    by claude-opus (model claude-opus-5-5, self-reported; invoked by sam)
```

`strata suggestions show ID` gives the proposal in full: the arguments, the assistant's reason, the criteria
version it was made under, and (for a change to the criteria) how many decisions it would make stale.

**Adopting** a suggestion makes it yours. The action is run *as you*, after checking it again against the
review as it is now, with *your* reason; the decision recorded is your own, with no mark of the assistant on
it, and the suggestion is linked to it. `strata why` shows both together.

```
strata --why "Agree: it is a randomised trial in schoolchildren reporting recall." suggestions adopt ev_01m6n1qdfcxrgx51n08m67wp6f --by ethan
```

```
adopted ev_01m6n1qdfcxrgx51n08m67wp6f: recorded as ethan's own (1 event(s))
```

```
strata suggestions show ev_01m6n1qdfcxrgx51n08m67wp6f
```

```
ev_01m6n1qdfcxrgx51n08m67wp6f  screening    include rec_0000000000000001 at title-abstract
    by claude-opus (model claude-opus-5-5, self-reported; invoked by sam)
    status: adopted
    suggested: screen {"decision": "include", "record": "rec_0000000000000001", "stage": "title-abstract"}
    reason given: Spaced-practice RCT in schoolchildren; reports recall.
    made under criteria v2
    adopted by ethan: Agree: it is a randomised trial in schoolchildren reporting recall.
    -> ev_01m6n1r8x309w6s03q3x6y1m69
```

- If the **criteria changed** since the suggestion was made, you are told what changed and must confirm
  (`--confirm`) before adopting it against the review as it now stands.
- If the action would now be **refused** (the criterion it cited has been retired, say), adopting says so and
  records nothing.
- An observer, and an assistant, cannot adopt.
- **Rejecting** (`strata --why "..." suggestions reject ID`) keeps the suggestion and your reason in the
  record and does not offer it again. A reason is required.
- A **newer suggestion** from the same assistant about the same thing supersedes an earlier one that nobody
  has dealt with; only the latest is waiting, and the earlier one is shown as superseded.

In the browser, the same list is at `/suggestions` (see [The web interface](The-Web-Interface)).

### Suggestions and blinding

A suggestion is something that could steer a reviewer. While the review blinds its reviewers
(`[screening] blind_reviewers`, on by default), a suggestion about a record is **not shown** to a reviewer
assigned to that record until they have recorded their own opinion. They do not see it in the list, in the
browser or in `strata why`. `strata suggestions list` and `show` take `--by` to say who is looking; with no
`--by` the list is the one safe to show anyone.

Some teams want AI-first screening. Set `show_suggestions = "always"` under `[ai]` (it is a setting in
`strata.toml`, in [Configuration](Configuration#ai)) and reviewers see suggestions at once. `strata` then
marks an opinion recorded after a suggestion about the same record could have been seen, and any opinion that
came from adopting one, as **informed by it**, and leaves it out of agreement between independent
reviewers. `derived/irr.json` and `strata irr` count the records left out (`excluded_informed`). Under the
default, a reviewer's first opinion is made before they can see anything, so it stays independent.

## Connecting an assistant

An assistant connects through `strata mcp`. Start it with the person who is responsible for it:

```
strata -C /path/to/review mcp --as ada
```

`--as` names the active, non-observer person on whose behalf the assistant acts; it is recorded on everything
the assistant does. Without it the server uses the review's only active person; with several people and no
`--as` it offers reads only and says why. `--allow-dir DIR` (repeatable) lets the import tool read from a
directory outside the review; every path is resolved first, so a link that points elsewhere does not pass, and
anything outside the review and the allowed directories is refused and not read.

What the assistant sees, every time it connects:

| Review state | The assistant is offered |
|---|---|
| AI not enabled | Read tools only, and an `ai_policy` tool that says AI is not enabled |
| Enabled, the person named | Reads, and a write tool for each family of work (below) |
| Enabled, but several people and no `--as`, or `--as` names an observer | Reads only, and `ai_policy` says what is needed |

| Family | Write tools |
|---|---|
| Screening, adjudication | `screen_record`, `adjudicate_conflict` |
| Extraction, risk of bias | `set_extraction_field`, `record_risk_of_bias` |
| Retrieval, studies | `record_retrieval`, `group_reports`, `split_report` |
| Records, deduplication | `correct_record`, `add_note`, `decide_duplicate` |
| Searches and imports | `record_search`, `import_records` |
| Criteria | `add_criterion`, `edit_criterion`, `retire_criterion` |
| Analysis | `run_analysis`, `draw_prisma` |

Each takes the assistant's `model` and a `rationale`, and the policy is checked **on the call itself**, so a
lead changing it takes effect on the next write. A kind that is `off` is refused and nothing is recorded; the
refusal names the policy. A model the review has not accepted is refused with the command that accepts it. In
`suggest` mode the result says "recorded as a suggestion", in `count` mode that it took effect as the
assistant's own work, and in both gives the id. A write never says whether anyone else has decided the record
or whether they agree. A criteria change carries what it would make stale, and in `count` mode that figure is
recorded in the commit.

There is no tool for the policy, for registering or deactivating an actor, for assignment, for configuration,
for creating or cloning a review, for repair or for syncing. A test lists every command that changes a review
and fails until each is either available to assistants or reserved for people, so a new command cannot become
reachable by omission.

An assistant cannot get past a guardrail: `run_analysis` has no way to force a run or to acknowledge a warning.

## What an assistant's commit looks like

A commit made for an assistant is **authored by the assistant and committed by the person**:

```
strata log --actor claude-opus
```

The author reads `claude-opus (via ada)` at an address on the reserved `agents.invalid` domain, so nothing is
credited to a stranger or to Ada; the committer is whoever's git identity ran the server and is the one
responsible to the remote. The commit carries the trailers `Strata-Agent`, `Strata-Invoked-By`, `Strata-Via:
mcp` and `Strata-Model`, and `strata log --actor` finds it. The history screen in the browser marks it with the
same icon and the words "AI".

## Reading the ledger

```
strata ai report
```

```
claude-opus model claude-opus-5-5 (self-reported)
  active 2026-11-05; invoked by ethan, sam; via claude-code 2.1.3
  screening      suggested 1 (adopted 1, rejected 0, superseded 0, waiting 0); counted 3 (3 as a reviewer, 1 later changed by a person)
```

For each assistant and kind of work: the suggestions made and what became of each, the decisions that took
effect as its own (and how many of those filled a reviewer's place), how many a person later changed, who
ran it, through which client, and the dates. `--json` gives the same figures. The generated Methods text and
PRISMA checklist items 8, 9 and 11 are written from this ledger, so they cannot disagree with it, and cannot
claim that no automation tool was used when one was.

```
strata status
```

```
AI participation is on (screening: count, criteria: suggest) · 3 agent event(s) · 0 suggestion(s) waiting
```

## Checking what an assistant decided alone

```
strata audit --ai --sample 20 --seed 7
```

re-presents a random sample of the assistant's decisions **that no person has independently decided** (not
those a person also screened, and not those an adjudicator settled). The same seed gives the same sample, so a
second reader can look at the same twenty. A correction found this way goes through the usual route: change a
decision and it is a new decision.

## Revoking an assistant

```
strata --why "We no longer want AI in this review" ai revoke claude-opus --by ethan
```

```
revoked claude-opus: 3 decision(s) now wait in the stale queue (`strata rescreen`); its history is unchanged
```

Revoking deactivates the assistant and puts every decision of its that still counted in the stale queue with
the reason `agent-revoked`, exactly as a change of criteria does, so people look at them again with the
assistant's decision shown. Only a lead can do it. Its events stay in the record, it can write nothing more,
and the Methods text still discloses that it took part.

## An assistant is not a reviewer until you assign it

Registering a model does not put it on the review. **Assignment decides who counts**, and only a person can
assign. By default the reviewers on a record are every active screener and lead, and **never** a
registered assistant. To use one as a second reviewer, assign it:

```
strata --why "Claude Opus as second screener for the pilot batch" assign title-abstract --actors ethan,claude-opus --by ethan
```

Agreement is reported **per pair**, and every pair that involves an assistant is labelled, so agreement with
a model is never mixed into agreement between people. With `ethan`, `sam` and `claude-opus` each screening
the same four records:

```
strata irr
```

```
title-abstract   claude-opus x ethan   n=4   agreement=0.50   kappa=0.00   pabak=0.00   (AI: involves an agent)
title-abstract   claude-opus x sam   n=4   agreement=0.75   kappa=0.50   pabak=0.50   (AI: involves an agent)
title-abstract   ethan x sam   n=4   agreement=0.75   kappa=0.50   pabak=0.50
```

In `derived/irr.json` those pairs carry `"involves_agent": true`; a person-to-person pair is exactly as it
was. For the arithmetic see [Adjudication and agreement](Adjudication-and-Agreement).

## A correction that applies to every review

The specification has always said that a record is resolved from the opinions of the people **assigned** to
it. The software used to count the opinion of anyone who had decided it. For people that rarely mattered. An
assistant that nobody assigned would have been a free second reviewer, so this is now enforced for everyone:
an opinion from someone who is not assigned to a record stays in the log and in `strata why`, and counts for
nothing.

If your review recorded such an opinion (decisions imported for a person who was never assigned, say),
`strata verify` tells you which records would resolve differently now:

```
W_UNASSIGNED_OPINION: 3 record(s) at title-abstract were resolved with the help of an opinion from someone not assigned to them, which no longer counts (rec_..., rec_..., rec_...); assign the reviewer with `strata assign` if their opinion should
```

It is a warning, not an error. Assigning the reviewer makes their opinion count again.

## What `strata migrate` does

A review has a **format version**, in `.strata/schema-version`. Reviews are created in format 1. Format 2 is
the one that permits an assistant's events, and a `strata` that only knows format 1 will refuse to open a
format 2 review (`E_SCHEMA_TOO_NEW`) rather than read an assistant's opinion as a person's.

```
strata status
```

```
Spacing review  criteria v0
1 commits · 1 actors · clean
0 records · 0 searches recorded
format 1; format 2 is available (`strata migrate`; AI participation needs it)
```

`strata status` mentions it and changes nothing. A review stays in format 1 until you ask:

```
strata --why "Moving to format 2 so we can pilot AI suggestions" migrate
```

- It is **one commit** with your reason in it, and nothing in the history is rewritten.
- It only goes **forward**. There is no way back to format 1.
- Running it again changes nothing and makes no commit.
- `strata ai enable` runs it for you, in the same commit.

A review that never enables AI may stay in format 1 for good, and is never nagged.

## If you decide AI was a mistake

Revoke the assistants (above) and set every kind of work back to `off` with `strata ai policy`. The history
stays: what the assistants did, and that you later stopped, are both part of the record. There is no way back
to format 1.
