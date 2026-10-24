# Screening

Screening decides, for each record, whether it meets your eligibility criteria. It happens in two stages:
**title and abstract** (fast, generous) and **full text** (careful, with a reason for every exclusion).
`strata screen` works the queue for a stage; the [web interface](The-Web-Interface) offers the same
screening with the keyboard.

```
strata --why "Title and abstract screening, first pass" screen title-abstract --by ada
```

## Who screens what

The default (`screening.mode = "dual"`) is that **two reviewers screen every record independently**. Who those
two are comes from the actors on the team (every `screener` and `lead`), or from an explicit assignment:

```
strata --why "Both reviewers screen everything" assign title-abstract --actors ada,sam --by ada
```

```
assigned 8 record(s) at title-abstract to ada, sam
```

By default **every actor whose role is `screener` or `lead` is assigned to every record**; an `assign` event for a
record overrides that for that record, and `screening.assignment.<stage>` in `strata.toml` changes the default.
`assign` records which reviewers must opine on which records; it can be limited with `--filter`, for example
to give a subset (say, non-English records) to one particular person. A record is *resolved* when everyone
assigned to it has opined and they agree. With `mode = "single"` one opinion is enough (use it for pilots; the
generated Methods will say so).

> **Adding a screener part-way through.** Because the default is "everyone", adding a new `screener` makes every
> record that is already finished *partial* again (the new person has not opined), and studies you had included
> can seem to disappear from `strata status` until they have. Before you add the person, freeze who is
> assigned to the work already done (`strata --why "..." assign title-abstract --actors ada,sam --by ada`, and the
> same for `full-text`), or add them with another role if they will not screen.

## The screening session

```
title-abstract  record 1 of 8

Sleep and memory consolidation in rats
Lindqvist · Example Neuroscience Letters · 2017

Invented abstract for illustration. An animal study unrelated to classroom learning.

Criteria:
  1  INC-01  Learners in formal education
  2  INC-02  Spacing manipulated
  3  EXC-01  Not an empirical study
  4  EXC-02  Not human
[i]nclude [e]xclude [m]aybe [s]kip [u]ndo [q]uit [s]:
```

| Key | Does |
|---|---|
| `i` | Include |
| `e` | Exclude. You are then asked which criteria to cite (the numbers, comma-separated: `3` or `1,4`) |
| `m` | Maybe. Use sparingly: any "maybe" makes the record a conflict to adjudicate, and it is the decision that goes stale under *any* criteria change |
| `s` | Skip for now (it returns next session) |
| `u` | Undo the last decision (it records a correcting event; nothing is deleted) |
| `q` | Quit. Run the command again to resume |

After every decision you can type a short note (press Enter for none). The note and the cited criteria are what
the adjudicator and the PRISMA exclusion table see.

Things worth knowing:

- **Decisions are saved as you make them.** If the session dies, run the command again; it resumes with the
  records already done, and the commit is made when the session ends. `git diff` shows what is waiting.
- **The queue is deterministic** (sorted by record id), so closing and reopening picks up in the same place.
- **Narrow it** with `--filter` (for example `--filter "year >= 2010"`) and cap it with `--limit 50`.
- **A "maybe", or two reviewers who disagree, makes a conflict**, which goes to
  [adjudication](Adjudication-and-Agreement). It does not hold up the other reviewer.
- **You cannot see your colleague's decision** while you screen unless you have turned blinding off. See
  [Blinding and independence](Blinding-and-Independence).
- **At full text, an exclusion must cite at least one criterion.** At title-abstract it must too, when
  `screening.require_exclusion_reason` is on (the default).

## Working to the criteria

Cite the criterion that actually excludes the record, not the first that comes to mind: staleness is computed
from the criteria you cite ([Staleness](Staleness)), so a miscited reason can hide a decision from a later
criteria change. `strata audit --criteria` re-presents a random sample of past exclusions so you can check
them: see [Adjudication and agreement](Adjudication-and-Agreement#spot-checking-exclusions).

When a record has no abstract it is shown as it is, flagged, never skipped silently.

## Moving to full text

Records resolved as **include** (or the ones adjudicated to include) at title-abstract move on: they appear in
the retrieval queue ([Retrieving full texts](Retrieving-Full-Texts)). Once you have the full text, screen at the
`full-text` stage:

```
strata --why "Full-text screening" assign full-text --actors ada,sam --by ada
strata --why "Full-text screening" screen full-text --by ada
```

> **Current limitation: the full-text queue is not narrowed to the records that passed title-abstract.**
> Unless you assign otherwise, every record is in the full-text queue, including the ones you excluded at
> title-abstract; and `--filter` cannot yet test a record's screening state (`tiab`, `fulltext`, `stale`,
> `actor_decision` are listed in the [filter language](Filter-Language) but report "not available yet").
> Until that is fixed, limit the queue to the records you retrieved by id, as the [quickstart](Quickstart)
> does:
>
> ```
> strata --why "Full-text screening" screen full-text --by ada --filter "id in ['rec_...','rec_...']"
> ```
>
> `derived/pool.tsv` lists every record with its `tiab` and `fulltext` state, so you can copy the ids from
> there. The unscreened remainder will show as "unscreened" at full text in `strata status`; it does not
> affect the PRISMA counts, which are computed from what was actually assessed. See
> [Known limitations](Known-Limitations).

## Bringing in screening done elsewhere

If some screening was done in another tool, import it from a tab-separated file instead of redoing it:

```
strata --why "Imported the pilot screening done in a spreadsheet" screen title-abstract --by ada --decisions pilot.tsv
```

The file has the header `record_id`, `decision`, `criteria`, `note` (criteria separated by semicolons).
Imported decisions are marked as imported in the log, because their independence cannot be verified. Agreement
statistics (`strata irr`) do not yet tell imported decisions apart, so do not report agreement for screening you
imported.

## Pace and checking

- `strata status` shows, per stage, how many records are resolved, unscreened, partly screened and in conflict,
  and a **NEXT** line with the command to run.
- `strata irr` reports agreement between reviewers ([Adjudication and agreement](Adjudication-and-Agreement)).
- A good routine is a pilot of 50 to 100 records screened by everyone, a short discussion, refined criteria
  (recorded as a change, see [Changing criteria mid-review](Changing-Criteria-Mid-Review)), then the rest.

Next: [Adjudication and agreement](Adjudication-and-Agreement).
