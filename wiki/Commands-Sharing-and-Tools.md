# Commands: sharing, the web interface and tools

Syncing a shared review, the browser interface, a hosted instance, the read-only assistant server, CI helpers. Part of the [Command reference](Command-Reference).

> This page is generated from the program's own help text by `scripts/build_wiki_reference.py`. Do not edit it by hand; change the help text in the code and regenerate.

Contents: [`sync`](#strata-sync), [`serve`](#strata-serve), [`host`](#strata-host), [`mcp`](#strata-mcp), [`ci`](#strata-ci)

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
| `--max-upload-mb` | int | `100` | Largest file upload the server accepts, in megabytes |

Guide: [The web interface](The-Web-Interface), [Running in a container](Running-in-a-Container)

## `strata host`

Run and administer a hosted strata instance.

```
strata host [OPTIONS] COMMAND
```

| Option | Takes | Default | Meaning |
|---|---|---|---|
| `--data` | path |  | The instance's data directory (default: $STRATA_DATA or /data) (environment variable `STRATA_DATA`) |
| `--public-url` | str |  | The https:// URL people use to reach the instance (default: instance.toml's) (environment variable `STRATA_PUBLIC_URL`) |
| `--bind` | str | `127.0.0.1` | Address to listen on (0.0.0.0 in a container) |
| `--port` | int | `8000` | Port to listen on |
| `--trusted-proxy` | str | `127.0.0.1` | Address(es) of the TLS-terminating proxy whose X-Forwarded-* headers are believed (environment variable `STRATA_TRUSTED_PROXY`) |
| `--insecure-local-testing` | flag |  | Accept plain HTTP and issue sessions over it: only to try an instance locally |

### `strata host init`

Initialise instance state and the first administrator.

```
strata host init [OPTIONS]
```

| Option | Takes | Default | Meaning |
|---|---|---|---|
| `--data` | path |  | The instance's data directory (default: $STRATA_DATA or /data) (environment variable `STRATA_DATA`) |
| `--public-url` | str |  | (environment variable `STRATA_PUBLIC_URL`) |
| `--admin` | str | `admin` | User name of the first administrator |
| `--admin-name` | str |  | Their display name |
| `--admin-email` | str |  |  |
| `--invite` | flag |  | Print an invitation link instead of asking for a password |

### `strata host signins`

Show the sign-in audit log, newest first.

```
strata host signins [OPTIONS]
```

| Option | Takes | Default | Meaning |
|---|---|---|---|
| `--limit` | int | `50` |  |
| `--data` | path |  | The instance's data directory (default: $STRATA_DATA or /data) (environment variable `STRATA_DATA`) |

### `strata host project`

Projects on this instance.

```
strata host project COMMAND
```

#### `strata host project add`

Add a project by cloning its remote, or initialise a new review.

```
strata host project add [OPTIONS] PROJECT_ID
```

| Argument | | Meaning |
|---|---|---|
| `project_id` | required | Short id, used in URLs (e.g. spacing) |

| Option | Takes | Default | Meaning |
|---|---|---|---|
| `--remote` | str |  | Clone this review's git remote |
| `--credential` | str |  | KIND:SECRET -- ssh-key:<secret> (deploy key) or token:<secret> (HTTPS token) |
| `--credential-user` | str |  | User name sent with an HTTPS token |
| `--title` | str |  |  |
| `--actor` | str |  | First actor of a new review |
| `--actor-name` | str |  |  |
| `--actor-email` | str |  |  |
| `--data` | path |  | The instance's data directory (default: $STRATA_DATA or /data) (environment variable `STRATA_DATA`) |

#### `strata host project list`

List projects with their remote and last-sync status.

```
strata host project list [OPTIONS]
```

| Option | Takes | Default | Meaning |
|---|---|---|---|
| `--data` | path |  | The instance's data directory (default: $STRATA_DATA or /data) (environment variable `STRATA_DATA`) |

### `strata host user`

Local accounts.

```
strata host user COMMAND
```

#### `strata host user add`

Create a local account.

```
strata host user add [OPTIONS] USERNAME
```

| Argument | | Meaning |
|---|---|---|
| `username` | required |  |

| Option | Takes | Default | Meaning |
|---|---|---|---|
| `--name` | str |  | Display name |
| `--email` | str |  |  |
| `--admin` | flag |  | Make them an instance administrator |
| `--invite` | flag |  | Print an invitation link instead of setting a password |
| `--data` | path |  | The instance's data directory (default: $STRATA_DATA or /data) (environment variable `STRATA_DATA`) |

#### `strata host user invite`

Issue a new invitation link for an existing account (to reset a password).

```
strata host user invite [OPTIONS] USERNAME
```

| Argument | | Meaning |
|---|---|---|
| `username` | required |  |

| Option | Takes | Default | Meaning |
|---|---|---|---|
| `--data` | path |  | The instance's data directory (default: $STRATA_DATA or /data) (environment variable `STRATA_DATA`) |

#### `strata host user disable`

Disable an account: it cannot sign in, and its sessions and API tokens end now.

```
strata host user disable [OPTIONS] USERNAME
```

| Argument | | Meaning |
|---|---|---|
| `username` | required |  |

| Option | Takes | Default | Meaning |
|---|---|---|---|
| `--data` | path |  | The instance's data directory (default: $STRATA_DATA or /data) (environment variable `STRATA_DATA`) |

#### `strata host user enable`

Re-enable a disabled account.

```
strata host user enable [OPTIONS] USERNAME
```

| Argument | | Meaning |
|---|---|---|
| `username` | required |  |

| Option | Takes | Default | Meaning |
|---|---|---|---|
| `--data` | path |  | The instance's data directory (default: $STRATA_DATA or /data) (environment variable `STRATA_DATA`) |

#### `strata host user list`

List accounts (never their credentials).

```
strata host user list [OPTIONS]
```

| Option | Takes | Default | Meaning |
|---|---|---|---|
| `--data` | path |  | The instance's data directory (default: $STRATA_DATA or /data) (environment variable `STRATA_DATA`) |

### `strata host member`

Project memberships.

```
strata host member COMMAND
```

#### `strata host member add`

Map a user to an actor and role in a project.

```
strata host member add [OPTIONS] PROJECT USERNAME
```

| Argument | | Meaning |
|---|---|---|
| `project` | required |  |
| `username` | required |  |

| Option | Takes | Default | Meaning |
|---|---|---|---|
| `--actor` (required) | str |  | The actor handle in the project's strata.toml |
| `--role` (required) | str |  | One of: adjudicator, extractor, lead, observer, screener |
| `--data` | path |  | The instance's data directory (default: $STRATA_DATA or /data) (environment variable `STRATA_DATA`) |

#### `strata host member remove`

Remove a user's membership of a project.

```
strata host member remove [OPTIONS] PROJECT USERNAME
```

| Argument | | Meaning |
|---|---|---|
| `project` | required |  |
| `username` | required |  |

| Option | Takes | Default | Meaning |
|---|---|---|---|
| `--data` | path |  | The instance's data directory (default: $STRATA_DATA or /data) (environment variable `STRATA_DATA`) |

#### `strata host member list`

List a project's members.

```
strata host member list [OPTIONS] PROJECT
```

| Argument | | Meaning |
|---|---|---|
| `project` | required |  |

| Option | Takes | Default | Meaning |
|---|---|---|---|
| `--data` | path |  | The instance's data directory (default: $STRATA_DATA or /data) (environment variable `STRATA_DATA`) |

### `strata host token`

API tokens (remote MCP).

```
strata host token COMMAND
```

#### `strata host token add`

Create an API token for a user's MCP client; shown once, stored only as a hash.

```
strata host token add [OPTIONS] USERNAME
```

| Argument | | Meaning |
|---|---|---|
| `username` | required |  |

| Option | Takes | Default | Meaning |
|---|---|---|---|
| `--label` | str | `mcp` | What the token is for |
| `--data` | path |  | The instance's data directory (default: $STRATA_DATA or /data) (environment variable `STRATA_DATA`) |

#### `strata host token revoke`

Revoke a user's API tokens.

```
strata host token revoke [OPTIONS] USERNAME
```

| Argument | | Meaning |
|---|---|---|
| `username` | required |  |

| Option | Takes | Default | Meaning |
|---|---|---|---|
| `--label` | str |  | Only the tokens with this label |
| `--data` | path |  | The instance's data directory (default: $STRATA_DATA or /data) (environment variable `STRATA_DATA`) |

### `strata host secret`

Instance secrets.

```
strata host secret COMMAND
```

#### `strata host secret set`

Store a secret encrypted at rest (a deploy key, a token, an OIDC client secret).

The value is read from standard input (a deploy key can be piped in: `strata host secret set
spacing-key < id_ed25519`), from --from-env, or from a hidden prompt; never from the command
line.

```
strata host secret set [OPTIONS] NAME
```

| Argument | | Meaning |
|---|---|---|
| `name` | required |  |

| Option | Takes | Default | Meaning |
|---|---|---|---|
| `--from-env` | str |  | Read the value from this environment variable |
| `--data` | path |  | The instance's data directory (default: $STRATA_DATA or /data) (environment variable `STRATA_DATA`) |

#### `strata host secret list`

List stored secret names (never values), and where any named one comes from.

```
strata host secret list [OPTIONS] [NAMES]
```

| Argument | | Meaning |
|---|---|---|
| `names` | optional | Also say where these names would come from |

| Option | Takes | Default | Meaning |
|---|---|---|---|
| `--data` | path |  | The instance's data directory (default: $STRATA_DATA or /data) (environment variable `STRATA_DATA`) |

#### `strata host secret delete`

Delete a stored secret.

```
strata host secret delete [OPTIONS] NAME
```

| Argument | | Meaning |
|---|---|---|
| `name` | required |  |

| Option | Takes | Default | Meaning |
|---|---|---|---|
| `--data` | path |  | The instance's data directory (default: $STRATA_DATA or /data) (environment variable `STRATA_DATA`) |

Guide: [Running a hosted instance](Running-a-Hosted-Instance), [Inviting collaborators](Inviting-Collaborators), [Hosted and local collaborators](Hosted-and-Local-Collaborators)

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
