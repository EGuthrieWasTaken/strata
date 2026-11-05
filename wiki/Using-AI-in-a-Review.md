# Using AI in a review

`strata` is not an AI product and ships no model. It makes no network call and holds no key. What it does
offer is an honest place for the AI your review may already be using: the reviewers decide **whether,
where and how far** an AI assistant may take part, and wherever one does, the record says so. It names the
model and the person who started it, keeps its work apart from the people's, and carries all of it into the
Methods text.

AI participation is **off by default**. A review that never turns it on behaves exactly as it always has,
and nothing in it changes format.

> **This page grows with the feature.** The policy, registering a model, the second file format, the
> labelling of agreement and **suggestions** are in this version. The assistant's own tools (proposing and
> recording decisions over MCP) and the generated disclosure arrive in later stages of the same change, and
> this page will cover them as they do. Until then an assistant cannot write to a review through `strata`.

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

Abandoning AI means removing the assistants and setting every kind of work back to `off` with
`strata ai policy`. The history stays: what the assistants did, and that you later stopped, are both part of
the record.
