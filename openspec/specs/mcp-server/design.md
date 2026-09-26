# Design: mcp-server

*Informative.* The requirements are in [spec.md](spec.md).

## A fourth thin adapter

The MCP server sits alongside the CLI, the web UI, and (planned) the hosted
deployment as another presentation layer over the same `core`/`protocol`
functions — the same relationship the web routes have to the logic behind
`strata screen`. It runs over stdio, spawned locally by an MCP-aware client
against a local clone, with no new infrastructure.

## Why read-only

`strata`'s entire premise is that a screening decision is an accountable human
judgement. A tool that let an agent record one unsupervised would undermine the
provenance chain the rest of the tool exists to keep honest. Status, staleness,
provenance, history, record filtering, and the non-mutating criteria impact
preview commit nothing, so they carry no accountability risk. If a write-capable
tool is ever added, it produces a proposal — a drafted decision or rationale —
for a human to review and execute.

## Remote access

Exposing the same tools over MCP's HTTP transport, behind per-user
authentication, is part of the `add-hosted-team-deployment` change.
