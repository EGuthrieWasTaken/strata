# Tasks

## 0. Decision

- [ ] 0.1 Reconcile this milestone with non-goal N6 and open question Q11 and record the decision

## 1. Sync loop

- [ ] 1.1 Pull before serving repository state (or on a short poll)
- [ ] 1.2 Push after each commit with retry and exponential backoff
- [ ] 1.3 Surface merge conflicts as a clear in-app message; never drop work silently

## 2. Authentication

- [ ] 2.1 GitHub-identity login via OAuth device flow or personal access token
- [ ] 2.2 Map identities to `strata` actor handles and attribute every commit and decision

## 3. Multi-tenancy

- [ ] 3.1 Serve several review repositories from one instance
- [ ] 3.2 Enforce per-team isolation on every route

## 4. Remote MCP

- [ ] 4.1 Expose the M2.1 MCP tools over MCP's HTTP transport behind the same auth

## 5. Tests (suite additions, `docs/spec/15-roadmap.md` M5.1)

- [ ] 5.1 A sync-loop E2E scenario: two members editing concurrently through the hosted UI, merge-or-surfaced-conflict, never silent loss
- [ ] 5.2 Auth integration tests mapping a GitHub identity to an actor handle
- [ ] 5.3 A multi-tenancy isolation test
