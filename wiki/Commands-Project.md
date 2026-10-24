# Commands: project and repository

Create, clone and check a review; settings; the team; history. Part of the [Command reference](Command-Reference).

> This page is generated from the program's own help text by `scripts/build_wiki_reference.py`. Do not edit it by hand; change the help text in the code and regenerate.

Contents: [`init`](#strata-init), [`clone`](#strata-clone), [`doctor`](#strata-doctor), [`config`](#strata-config), [`actor`](#strata-actor), [`verify`](#strata-verify), [`status`](#strata-status), [`log`](#strata-log), [`diff`](#strata-diff), [`version`](#strata-version)

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

Guide: [Setting up a review](Setting-Up-a-Review)

## `strata verify`

Validate the whole repository.

```
strata verify [OPTIONS]
```

| Option | Takes | Default | Meaning |
|---|---|---|---|
| `--fast` | flag |  |  |
| `--fix` | flag |  |  |

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
