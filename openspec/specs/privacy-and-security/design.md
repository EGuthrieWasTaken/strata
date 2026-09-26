# Design: privacy-and-security

*Informative.* The requirements are in [spec.md](spec.md).

## No telemetry, not even anonymous

A tool researchers commit multi-year projects to, sometimes on sensitive
topics, should not phone home. If the project ever wants usage data it will ask
users to send it deliberately. (Contributors are asked to run OpenSpec with
`OPENSPEC_TELEMETRY=0` for the same reason.)

## Offline by default

With enrichment disabled, the only network traffic is what the user initiates:
`strata sync` talking to the git remote the user configured. A self-hosted
instance (see the `add-hosted-team-deployment` change) moves the whole stack to
a server the team chose; it does not add any third party.

## Why enrichment is logged

When enrichment is on, `.strata/network.log` records every outbound request so a
user can audit exactly what left the machine.

## Why polite API use is a requirement

Crossref, OpenAlex, and PubMed provide free APIs with published etiquette.
Abusing a free scholarly API on behalf of thousands of users would be both
wrong and self-defeating, so a descriptive User-Agent with a contact address,
`Retry-After`, backoff, and a local cache are mandatory rather than polite
suggestions.

## Threat model

Modest — a local, single-user tool by default — but not empty. The realistic
threats are hostile input files (fuzzed, memory-bounded parsers; no XML external
entities; decompression caps), the browser reaching the localhost server
(tokens, CSRF, Origin/Host checks), HTML in abstracts (escaped on output),
catastrophic regexes in filters, and the software supply chain (pinned,
hash-locked dependencies; signed artefacts; an SBOM). Hosted operation widens
this surface and is specified separately.
