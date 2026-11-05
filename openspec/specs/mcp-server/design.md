# Design: mcp-server

*Informative.* The requirements are in [spec.md](spec.md).

## A fourth thin adapter

The MCP server sits alongside the CLI, the web UI, and (planned) the hosted
deployment as another presentation layer over the same `core`/`protocol`
functions — the same relationship the web routes have to the logic behind
`strata screen`. It runs over stdio, spawned locally by an MCP-aware client
against a local clone, with no new infrastructure.

## Why writes are attributed, not forbidden

`strata`'s premise is that every decision stays legible. The risk in letting an
agent write was never that a model might act; it was that it might act
*unattributed*, its work indistinguishable from a person's and counted as theirs,
which would undermine the provenance chain the rest of the tool exists to keep
honest. People already use AI assistants on reviews, and a tool that offers them
no honest way to do it only guarantees they do it outside the record.

So the server offers reads always, and writes only where a review has said so
(`openspec:ai-participation`). Each write names the model as the agent reports it
(a claim `strata` cannot verify, and says so) and the person who started the
server, is checked against the review's policy for its kind of work at the moment
of the call, and is either a suggestion that changes nothing or the agent's own
work under its own handle. What confers standing (the policy, actors,
assignment, configuration, creating or cloning a review, repair, and
synchronising) has no tool, and a test enumerates the command line's mutating
commands to keep it that way. Status, staleness, provenance, history, record
filtering and the non-mutating criteria impact preview commit nothing, and are
always offered.

This is an attributed route, not an enforcement boundary: an agent that can run
the command line can do what a person at that terminal could, and no server-side
design stops that.

## Remote access

Exposing the same tools over MCP's HTTP transport, behind per-user
authentication, is part of the `add-hosted-team-deployment` change.
