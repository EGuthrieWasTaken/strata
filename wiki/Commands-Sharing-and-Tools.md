# Commands: sharing, the web interface and tools

Syncing a shared review, the browser interface, the read-only assistant server, CI helpers. Part of the [Command reference](Command-Reference).

> This page is generated from the program's own help text by `scripts/build_wiki_reference.py`. Do not edit it by hand; change the help text in the code and regenerate.

Contents: [`sync`](#strata-sync), [`serve`](#strata-serve), [`mcp`](#strata-mcp), [`ci`](#strata-ci)

## `strata sync`

Fetch, merge, verify and push: the one verb for sharing a review. A dirty working tree is refused. Merged event files are put in
order and re-linked, the derived views are regenerated, and the result is verified: if that
fails, your repository is restored exactly and nothing is pushed. Two people editing the same
criterion or file is shown as mine and theirs; settle it with `--resolve mine|theirs`, answer
the prompts, or open an editor.

Example: strata sync

```
strata sync [OPTIONS]
```

| Option | Takes | Default | Meaning |
|---|---|---|---|
| `--by` | str |  | The actor syncing (default: the first active actor) |
| `--resolve` | str |  | Settle every conflicting file the same way: mine \| theirs |
| `--no-push` | flag |  | Fetch, merge and verify, but do not push |

Guide: [Working with others](Working-with-Others)

## `strata serve`

Start the local web UI.

```
strata serve [OPTIONS]
```

| Option | Takes | Default | Meaning |
|---|---|---|---|
| `--port` | int | `0` | Port to bind (0 = OS-assigned ephemeral port) |
| `--host` | str | `127.0.0.1` | Bind address; a non-loopback host requires --token |
| `--token` | str |  | Fixed session token (required with a non-loopback --host); or STRATA_TOKEN (environment variable `STRATA_TOKEN`) |
| `--public-url` | str |  | The URL a browser uses to reach this server (a published port or a proxy); Host and Origin are then validated against it (environment variable `STRATA_PUBLIC_URL`) |
| `--actor` | str |  | Screen as this actor; required if more than one is configured |
| `--no-browser` | flag |  | Do not automatically open a browser |
| `--inactivity-timeout` | number | `3600` | Seconds of inactivity before the server exits |

Guide: [The web interface](The-Web-Interface), [Running in a container](Running-in-a-Container)

## `strata mcp`

Run the local, read-only MCP server over stdio.

Exposes status/why/log/records/criteria-diff/impact-preview as MCP tools --
nothing that writes. Spawned by an MCP-aware client (Claude Code, Claude
Desktop, or any other) against this repository, the same way the client
would spawn any other local stdio server, e.g. `strata -C <path> mcp`.

```
strata mcp
```

Guide: [The web interface](The-Web-Interface)

## `strata ci`

Helpers the review-repository CI workflow uses.

```
strata ci COMMAND
```

### `strata ci amendment`

Did the change between two commits edit the review criteria? (JSON)

Compares `protocol/criteria.yaml` as data, so reformatting is not an amendment. The CI
workflow labels such a pull request `protocol-amendment`.

Example: strata ci amendment --base origin/main --head HEAD

```
strata ci amendment [OPTIONS]
```

| Option | Takes | Default | Meaning |
|---|---|---|---|
| `--base` (required) | str |  | The commit the change is made against |
| `--head` | str | `HEAD` | The commit with the change |

### `strata ci comment`

Write the pull-request comment (Markdown) from two status documents.

Example: strata ci comment base.json head.json --amendment amendment.json

```
strata ci comment [OPTIONS] BASE HEAD
```

| Argument | | Meaning |
|---|---|---|
| `base` | required | `strata --json status` at the base (`null` if none) |
| `head` | required | `strata --json status` at the head |

| Option | Takes | Default | Meaning |
|---|---|---|---|
| `--amendment` | str |  | The JSON `strata ci amendment` printed |
| `--methodologist` | str |  | Who is asked to review a change to the criteria |

Guide: [Working with others](Working-with-Others)
