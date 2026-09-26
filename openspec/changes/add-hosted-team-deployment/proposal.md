# Proposal: Hosted, team deployment (M5.1)

## Why

`strata serve` is already a real HTTP server; the gap for a shared, always-on
instance is everything a reviewer's laptop does not need: syncing with a git
remote on its own, and knowing who is making each request. A team that cannot
expect every member to run `git` locally needs this to collaborate at all.

Roadmap milestone: M5.1 (`docs/spec/15-roadmap.md`). Note the tension with
non-goal N6 and open question Q11 (`docs/spec/16-open-questions.md`), which
recommend holding the "not a hosted service" line; this change is sequenced
after M5, does not block M3–M5, and should be reconciled with Q11 before work
starts.

## What Changes

- A git sync loop inside `strata serve`: pull before serving repository state
  (or on a short poll), push after each commit with retry and exponential
  backoff, and conflicts surfaced in-app rather than resolved silently or lost.
- Per-user authentication (GitHub identity via OAuth device flow or a personal
  access token) mapped to `strata` actor handles, replacing the single shared
  session token for hosted use.
- Multi-tenancy: one instance serving several review repositories with strict
  isolation.
- The M2.1 MCP server exposed remotely over MCP's HTTP transport behind the same
  authentication.

## Capabilities

### New Capabilities

- `hosted-deployment`: the sync loop, per-user authentication, multi-tenancy,
  and the remote MCP transport.

### Modified Capabilities

(none — local `strata serve` behaviour is unchanged; hosted mode is additive)

## Impact

- `web/` gains an authentication layer and a hosted mode; `gitio` gains a
  background sync loop.
- `mcpserver/` gains an HTTP transport.
- New security surface: this is the first mode in which `strata` is reachable
  beyond localhost by design.
