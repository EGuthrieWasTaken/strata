# Commands: project and repository

Create, clone and check a review; settings; the team; history. Part of the [Command reference](Command-Reference).

> This page is generated from the program's own help text by `scripts/build_wiki_reference.py`. Do not edit it by hand; change the help text in the code and regenerate.

Contents: [`init`](#strata-init), [`clone`](#strata-clone), [`doctor`](#strata-doctor), [`config`](#strata-config), [`actor`](#strata-actor), [`ai`](#strata-ai), [`suggestions`](#strata-suggestions), [`migrate`](#strata-migrate), [`verify`](#strata-verify), [`status`](#strata-status), [`log`](#strata-log), [`diff`](#strata-diff), [`version`](#strata-version)

## `strata init`

Create a repository: layout, strata.toml, .gitattributes, hooks, merge drivers, commit.

With --ci the repository also gets .github/workflows/strata.yml, which runs `strata verify`,
comments what a pull request does to the review, and labels changes to the criteria.

```
strata init [OPTIONS] [PATH]
```

| Argument | | Meaning |
|---|---|---|
| `path` | optional | Directory to create the repository in |

| Option | Takes | Default | Meaning |
|---|---|---|---|
| `--title` | str |  |  |
| `--remote` | str |  |  |
| `--actor` | str |  | Your actor handle |
| `--actor-name` | str |  |  |
| `--actor-email` | str |  |  |
| `--ci` | flag |  | Also install the GitHub Actions workflow that checks pull requests |
| `--ci-ref` | str |  | With --ci: the strata tag, branch or commit the checks run from |
| `--methodologist` | str |  | With --ci: GitHub login asked to review a change to the criteria |

Guide: [Setting up a review](Setting-Up-a-Review)

## `strata clone`

`git clone` plus merge-driver and hook installation plus `strata verify`.

```
strata clone URL [DEST]
```

| Argument | | Meaning |
|---|---|---|
| `url` | required |  |
| `dest` | optional |  |

Guide: [Git for reviewers](Git-for-Reviewers), [Working with others](Working-with-Others)

## `strata doctor`

Diagnose and repair: missing merge drivers, missing hooks, git version.

```
strata doctor [OPTIONS]
```

| Option | Takes | Default | Meaning |
|---|---|---|---|
| `--fix` | flag |  |  |

Guide: [Installation](Installation)

## `strata config`

Read or set `strata.toml` values.

```
strata config KEY [VALUE]
```

| Argument | | Meaning |
|---|---|---|
| `key` | required |  |
| `value` | optional |  |

Guide: [Configuration](Configuration)

## `strata actor`

Manage contributors.

```
strata actor COMMAND
```

### `strata actor add`

```
strata actor add [OPTIONS] HANDLE NAME
```

| Argument | | Meaning |
|---|---|---|
| `handle` | required |  |
| `name` | required |  |

| Option | Takes | Default | Meaning |
|---|---|---|---|
| `--email` | str |  |  |
| `--role` | str | `screener` |  |
| `--kind` | str | `human` | human (the default), or agent: an AI model the review accepts (needs `strata ai enable`) |
| `--model` | str |  | For --kind agent: the model name the agent reports about itself |

### `strata actor list`

```
strata actor list
```

### `strata actor deactivate`

```
strata actor deactivate HANDLE
```

| Argument | | Meaning |
|---|---|---|
| `handle` | required |  |

Guide: [Setting up a review](Setting-Up-a-Review), [Using AI in a review](Using-AI-in-a-Review)

## `strata ai`

Optional: decide whether, where and how far AI agents may take part in this review.

```
strata ai COMMAND
```

### `strata ai enable`

Turn AI participation on for this review (a lead's decision; every kind of work starts off).

Upgrades the review to format 2 in the same commit if it is not there yet. Nothing changes for
anyone until `strata ai policy` lets a kind of work be suggested or counted, and an agent must
still be registered (`strata actor add NAME --kind agent --model MODEL`).

```
strata ai enable
```

### `strata ai policy`

Show, or set, what AI agents may do for each kind of work: off, suggest or count.

off: nothing. suggest: an agent may propose, and a person decides. count: an agent's work
takes effect, recorded as the agent's and reported as such. Setting a mode is a commit with
your rationale; no agent can do it.

```
strata ai policy [KIND] [MODE]
```

| Argument | | Meaning |
|---|---|---|
| `kind` | optional | A kind of work; omit to list them all |
| `mode` | optional | off, suggest or count; omit to show the mode |

### `strata ai report`

The AI ledger: for each agent and kind of work, what it suggested (and what became of each
suggestion), what took effect as its own, what a person later changed, who ran it and when.

Read from the record, so it cannot disagree with the generated Methods text, which is written
from the same figures. The model name is the agent's own report; `strata` cannot verify it.

```
strata ai report
```

### `strata ai revoke`

Withdraw an agent's standing: it is deactivated, and every screening decision of its that
still counted goes in the stale queue (reason agent-revoked) for people to look at again.

Its history stays in the record. Your rationale (--why) is part of the commit. No agent can do
this, or anything else that changes who takes part.

```
strata ai revoke [OPTIONS] AGENT
```

| Argument | | Meaning |
|---|---|---|
| `agent` | required |  |

| Option | Takes | Default | Meaning |
|---|---|---|---|
| `--by` (required) | str |  | The lead revoking the agent |

Guide: [Using AI in a review](Using-AI-in-a-Review)

## `strata suggestions`

Optional: what an AI agent has proposed, for a person to adopt or reject.

```
strata suggestions COMMAND
```

### `strata suggestions list`

List the suggestions waiting for a person (the pending ones; `--all` for the rest).

While reviewers are blinded, a suggestion about a record is not shown to a reviewer assigned to
it until they have recorded their own opinion; with no `--by` the list is the one safe to show
anyone.

```
strata suggestions list [OPTIONS]
```

| Option | Takes | Default | Meaning |
|---|---|---|---|
| `--all` | flag |  | Include adopted, rejected, superseded |
| `--by` | str |  | Who is looking: suggestions hidden from them by blinding are left out |

### `strata suggestions show`

Show one suggestion in full: the proposal, the agent's reasons and what became of it.

```
strata suggestions show [OPTIONS] SUGGESTION_ID
```

| Argument | | Meaning |
|---|---|---|
| `suggestion_id` | required |  |

| Option | Takes | Default | Meaning |
|---|---|---|---|
| `--by` | str |  | Who is looking: a suggestion blinding hides from them is not shown |

### `strata suggestions adopt`

Adopt a suggestion: the operation is recorded as yours, with your rationale (--why).

The suggestion is checked again against the review as it is now. The events written are your
opinion, not the agent's, and the suggestion is linked to them.

```
strata suggestions adopt [OPTIONS] SUGGESTION_ID
```

| Argument | | Meaning |
|---|---|---|
| `suggestion_id` | required |  |

| Option | Takes | Default | Meaning |
|---|---|---|---|
| `--by` | str |  | The person adopting (default: the review's only active person) |
| `--confirm` | flag |  | Adopt even though the review changed since it was suggested |

### `strata suggestions reject`

Reject a suggestion; your reason (--why) is kept with it and it is not offered again.

```
strata suggestions reject [OPTIONS] SUGGESTION_ID
```

| Argument | | Meaning |
|---|---|---|
| `suggestion_id` | required |  |

| Option | Takes | Default | Meaning |
|---|---|---|---|
| `--by` | str |  | The person rejecting (default: the review's only active person) |

Guide: [Using AI in a review](Using-AI-in-a-Review)

## `strata migrate`

Upgrade this review to the newest file format this version of strata knows.

Forward-only and idempotent: one commit with your rationale, nothing rewritten, and a second
run changes nothing. A review stays in the format it is in until you ask; the next format
permits AI participation (`strata ai enable` runs this for you).

```
strata migrate
```

Guide: [Using AI in a review](Using-AI-in-a-Review)

## `strata verify`

Validate the whole repository.

```
strata verify [OPTIONS]
```

| Option | Takes | Default | Meaning |
|---|---|---|---|
| `--fast` | flag |  |  |
| `--fix` | flag |  | Regenerate derived files that drifted; other problems are only reported |

Guide: [Recovery and troubleshooting](Recovery-and-Troubleshooting)

## `strata status`

The dashboard: project identity, actors, commits, criteria version.

```
strata status
```

Guide: [Quickstart](Quickstart)

## `strata log`

Domain-level history: reads `Strata-` trailers, not raw commit messages.

```
strata log [OPTIONS]
```

| Option | Takes | Default | Meaning |
|---|---|---|---|
| `--criteria` | flag |  |  |
| `--stage` | str |  |  |
| `--actor` | str |  |  |

Guide: [Searching and importing](Searching-and-Importing)

## `strata diff`

Domain-level diff: criteria, records, pools, included studies and pooled estimates.

```
strata diff <REF>..<REF>
```

| Argument | | Meaning |
|---|---|---|
| `<ref>..<ref>` | required | e.g. v1-protocol..HEAD |

Guide: [Analysis](Analysis), [Changing criteria mid-review](Changing-Criteria-Mid-Review)

## `strata version`

```
strata version
```

Guide: [Installation](Installation)
