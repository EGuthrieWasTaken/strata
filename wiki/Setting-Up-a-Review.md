# Setting up a review

Before the first search you decide four things: *who* is on the team, *what* you are looking for (the
criteria), *how* you will screen (one reviewer or two, blinded or not), and what the review is *about*. `strata`
records all four, and every later change to them, with the reason.

## 1. Create the repository

```
strata init my-review --title "Spacing and retention" --actor ada --actor-name "Ada Example"
cd my-review
```

| Option | Meaning |
|---|---|
| `--title` | The review's title (also used to name the project) |
| `--actor`, `--actor-name`, `--actor-email` | Your handle (lowercase letters, digits and hyphens), full name, and optionally email. You become the review's `lead` |
| `--remote` | Address of an existing remote, if you have one (see [Git for reviewers](Git-for-Reviewers)) |
| `--ci` | Also install the GitHub workflow that checks pull requests (see [Working with others](Working-with-Others)) |

`strata init` creates the folder layout ([what is in it](The-Review-Folder)), `strata.toml` (the settings),
the versioned hooks and merge drivers, and the first commit. It is safe to look around: everything is plain
text.

## 2. Write down the question

`protocol/question.md` is a plain Markdown file for the PICO(TS) question and your rationale. `strata` does not
interpret it; it is the first thing a reader of the repository sees, and the generated Methods text points to
it. Edit it in any editor and save it with a commit (`git commit -am "protocol: the review question"`, or
let your next `strata` command carry it).

## 3. Add the team

Everyone who records anything is an *actor*. Add each collaborator once:

```
strata --why "Adding the second reviewer" actor add sam "Sam Example" --role screener
strata actor list
```

```
ada              Ada Example              lead
sam              Sam Example              screener
```

The role is a label, and it matters in one place: **everyone whose role is `screener` or `lead` is assigned to
screen every record** unless you assign otherwise ([Screening](Screening#who-screens-what)). Give a person who will
only extract data or advise some other role (`--role extractor`, `--role advisor`) and they are not
asked to screen. A person stays in the history for ever: when someone leaves,
`strata actor deactivate sam` marks them `inactive` (so they are not given new work) without rewriting
anything they did.

## 4. Decide how you will screen

The screening settings live in `strata.toml`:

```toml
[screening]
stages = ["title-abstract", "full-text"]
mode = "dual"               # "dual" (two independent reviewers) or "single" (a pilot or scoping review)
adjudicators = ["ada"]      # who may resolve disagreements
blind_reviewers = true      # hide one reviewer's decision from the other until both have decided
blind_metadata = false      # also hide authors, journal and year while screening
require_exclusion_reason = true
```

Change a setting with `strata config`, for example `strata config screening.blind_metadata true`, and read one
with `strata config screening.mode`. A review of record should use `dual` mode; `single` is for pilots, and
the generated Methods text then says "screening was performed by a single reviewer". Note that `strata config`
changes the file but does not make a commit for you yet: run `git commit -am "settings: ..."` afterwards (see
[Known limitations](Known-Limitations)). Every setting is described on [Configuration](Configuration).

## 5. Write the eligibility criteria

A criterion has an id (`INC-01`, `EXC-02`, ...), a *kind* (`inclusion` or `exclusion`), a short label, a
definition clear enough that two people would apply it the same way, and the stages it applies at.

```
strata --why "Protocol criteria agreed at kickoff" criteria add --kind inclusion \
    --label "Learners in formal education" \
    --definition "Participants are school pupils or university students." \
    --applies-at title-abstract,full-text --by ada
```

```
added INC-01 (criteria v1)
```

Each change makes a new **version** of the criteria (`criteria v1`, `v2`, ...): `strata criteria list
--version 3` shows the criteria as they stood at version 3. Spend time on the definitions *before*
screening; changing them afterwards is allowed and tracked, but it costs re-screening
([Changing criteria mid-review](Changing-Criteria-Mid-Review)). Practical advice:

- **Write exclusion criteria you can cite.** At full text an exclusion must cite a criterion, and the
  PRISMA diagram lists the reasons. Make the criteria mutually distinct so a reviewer can pick one.
- **Make inclusion criteria positive and testable** ("compares spaced with massed schedules"), not "relevant".
- **Apply criteria at the stage where you can judge them.** A criterion that needs the methods section
  (sample size, randomisation) applies at full text only (`--applies-at full-text`); a title can rule out "not
  human" at title-abstract.
- **Pilot first.** Screen 50 records with two people, compare, and refine the wording. Record the refinement
  as a normal criteria change before real screening starts.

## 6. Declare moderators and outcomes (optional now, useful early)

If you plan subgroup or meta-regression analyses, declare the moderators now, because they shape the
extraction form. In `protocol/moderators.yaml`:

```yaml
moderators:
- name: retention_interval
  label: Retention interval
  type: continuous
  unit: days
- name: learner_level
  label: Learner level
  type: categorical
  levels: [primary, secondary, university]
```

and the outcomes in `protocol/outcomes.yaml`:

```yaml
outcomes:
- name: recall
  label: Delayed recall score
```

`strata extract init` later turns these into the coding form ([Extracting data](Extracting-Data)).

## 7. Register the protocol (recommended)

If you will register the protocol (PROSPERO, OSF), do it now, and record the register and number in
`strata.toml` under `[project.registry]` (for example `PROSPERO = "CRD42026000000"`) so the generated text and
the checklist can find it (PRISMA item 24a; see [Configuration](Configuration)). Mark the moment the protocol was fixed with a git tag so that
`strata diff` can later compare the finished review with it:

```
git tag v1-protocol
```

```
strata diff v1-protocol..HEAD     # criteria, records, included studies and pooled estimates that moved
```

## Check

```
strata status
strata verify
```

`strata status` always ends with a **NEXT** line naming the command to run next. When it says
`strata screen title-abstract` and you have imported your searches, you are ready to screen.
