# Design: git-integration

*Informative.* The requirements are in [spec.md](spec.md).

## Posture

`strata` is a purpose-built front end to git. Git already solves versioning,
attribution, branching, merging, and "what changed and why"; it does not solve
them *for this domain*, because the domain objects are not files a researcher
wants to edit by hand and the interface is hostile to someone who does not
already know it. So: domain operations are the interface, git is the storage
engine and the audit log, and a user who never learns git still gets
versioning, provenance, blame, and conflict-free collaboration. A user who does
know git gets an ordinary repository they can branch and review with ordinary
tools.

## An example structured commit

```
screen(title-abstract): exclude 42 records under new criterion EXC-07

Re-screened the 180 records flagged stale by the v3->v4 criteria change.
42 were excluded under the new age criterion; 138 retained.

Strata-Op: screen
Strata-Stage: title-abstract
Strata-Actor: ethan
Strata-Records-Affected: 180
Strata-Decisions: include=138 exclude=42
Strata-Criteria-Version: 4
Strata-Criteria-Digest: sha256:9f1c2a...
Strata-Events: ev_01j9x7m2q4h8s0v3n5k1t6w2yb..ev_01j9x7p0r1k3m5n7q9s1u3w5yd
Strata-Pool-Delta: -42
Strata-Schema-Version: 1
```

The subject is generated from what changed, the body is the user's reason, and
the trailers make history queryable: `strata log`, `strata prisma`, and
`strata report amendments` read them.

## Why the rationale prompt shows the impact first

```
$ strata criteria edit EXC-03

  You tightened EXC-03 ("Non-English publication").

  This invalidates 180 of 1,204 screening decisions:
    138 previously INCLUDED at title-abstract  (a tightened criterion may now exclude them)
     42 previously EXCLUDED citing EXC-03      (the grounds changed)
    the other 1,024 decisions remain valid.

  Why did you make this change? (This goes in the permanent record and in your
  manuscript's protocol-amendment section.)
  > _
```

Telling the user what changed first means the answer is about *why*. The
rationale is written once, at the moment the user actually remembers the
reason, and reappears in the manuscript's amendments section months later. The
stop-list (`wip`, `fix`, ...) and 12-character minimum exist because this is the
one place a rushed user will try to type nothing.

## Why screening commits are batched

One commit per screening decision would produce thousands of commits and make
history unreadable. Decisions are appended (and fsynced) immediately, so nothing
is lost if the process dies, and committed in batches. A batch that contradicts
an earlier resolved decision is a change of mind, and the record should say why,
so that case still prompts.

## Why merge drivers are an optimisation

Driver definitions live in `.git/config`, which is not committed, so a plain
`git clone` does not have them. That clone still works: git falls back to its
default driver, produces conflicts in `derived/`, and `strata sync` resolves
them by regeneration. `strata-regenerate` can safely ignore all three inputs
precisely because derived files are never read as input.

## Why history is never rewritten

A published review's history is evidence. There is no `strata amend` for a
pushed commit: a mistake is corrected by a new event in a new commit, which is
also what research integrity requires. Teams that want protocol changes
reviewed before adoption can use ordinary pull requests; `strata` documents
that pattern but never requires it.
