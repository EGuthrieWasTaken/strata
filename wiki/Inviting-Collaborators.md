# Inviting collaborators

On a [hosted instance](Running-a-Hosted-Instance) each person has their own account, and acts in a project
through a *membership*: which actor of the review they are, and what role they have there.

## Accounts

An administrator creates an account and sends the person an invitation link:

```
strata host user add sam.okonkwo --name "Sam Okonkwo" --invite
added account sam.okonkwo
invitation (valid for 7 days): https://strata.example.org/invite/DR65iP0-Gb98dhve5IlW3WIxGClBWpaVOxWRiiMlGsU
```

Sam opens the link and chooses a password (twelve characters or more), or signs in with a configured provider
to link it to the account. The link works once. To set a password directly instead, leave out `--invite`; the
password is asked for (or read from `STRATA_PASSWORD`), never typed on the command line.

```
strata host user invite sam.okonkwo     # a new link, e.g. for a forgotten password
strata host user disable sam.okonkwo    # signs them out everywhere and revokes their API tokens
strata host user list
```

An administrator manages accounts and projects; they have no role in any review unless a lead gives them one.

## Memberships

The person must be an **actor** of the review first: actors live in the review's own `strata.toml` (add one
with `strata actor add` on any clone, or ask the lead), so they travel with the repository. A membership then
says which person on this instance acts as them:

```
strata host member add spacing sam.okonkwo --actor sam --role screener
sam.okonkwo is sam (screener) in spacing
```

Every decision Sam records in the browser is the actor `sam`'s, and every commit made for Sam has Sam's name
and email from `strata.toml` as its author (the instance is the committer). A handle that is not in the
review's `strata.toml` is refused:

```
strata host member add spacing sam.okonkwo --actor samuel --role screener
error: 'samuel' is not an actor in spacing's strata.toml; add it there first (`strata actor add`), or use one
of: ethan, sam
```

A project's leads can also manage its members in the browser, from **Members** in the page header. One actor
belongs to one person, and a project always keeps at least one lead.

### Roles

| Role | May |
|---|---|
| observer | read everything; change nothing |
| screener | screen and re-screen, correct a record |
| extractor | extract data, judge risk of bias, record full-text retrieval, correct a record |
| adjudicator | screen and re-screen, adjudicate conflicts, correct a record |
| lead | everything: criteria, searches and imports, duplicates, assignment, studies, members, sync conflicts |

The role is checked on every request; a page you cannot use says so.

### Blinding on a shared server

While `blind_reviewers` is on (the default), the instance never shows you a colleague's opinion on a record you
are assigned and have not decided yet, on any page or through MCP. Once you decide, nothing is hidden. See
[Blinding and independence](Blinding-and-Independence).

## Signing in with GitHub or your institution

Local accounts need nothing external. An operator can also add sign-in providers in `instance.toml`:

```toml
[[oidc]]
id = "university"
label = "University sign-in"
kind = "oidc"                       # any OpenID Connect provider, found from its issuer
issuer = "https://login.example.edu"
client_id = "strata"
client_secret = "oidc-university"   # the NAME of a secret, not the secret itself

[[oidc]]
id = "github"
label = "GitHub"
kind = "github"
client_id = "Iv1.0123456789abcdef"
client_secret = "oidc-github"
```

Register the instance with the provider with the redirect address `https://<your instance>/auth/<id>/callback`,
and supply the client secret as a container secret or environment variable (`STRATA_SECRET_OIDC_UNIVERSITY`),
or store it: `strata host secret set oidc-university`.

A provider sign-in reaches an account only once it is **linked**: the person opens their invitation and
chooses the provider there. Someone with an account at the same provider but no invitation is turned away (and
the attempt is logged). For GitHub the link is to GitHub's numeric user id, so renaming a GitHub login does not
break it.

## Assistants (remote MCP)

The read-only MCP tools (`status`, `why`, `log`, `records`, `criteria_diff`, and the criteria impact preview)
are served at `https://<your instance>/p/<project>/mcp` over MCP's HTTP transport. A client authenticates with
an API token:

```
strata host token add sam.okonkwo --label laptop
API token for sam.okonkwo (laptop); it is not shown again:
strata_...
```

The token sees exactly the projects its owner is a member of, with the same blinding, and can never record a
decision. `strata host token revoke sam.okonkwo` withdraws it.
