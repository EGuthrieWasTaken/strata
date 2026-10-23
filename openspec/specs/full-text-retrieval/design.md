# Design: full-text-retrieval

*Informative.* The requirements are in [spec.md](spec.md).

## Why documents are identified by identifier and version, never by hash

Annotating a PDF changes its bytes without changing the document, so a hash check
would report disagreement between two copies of the same paper in the ordinary
case, and nothing a reader could act on. `version` (preprint, accepted manuscript,
version of record) plus a per-version `locator` is both more robust and more
informative: the two reviewers can see that one of them read the preprint. A
`sha256` MAY be recorded as advisory metadata, never as identity.

## Why the manifest and the files are separate

The manifest (`fulltext/manifest.ndjson`) is committed; the PDFs are not
(`copyright-and-licensing`). A collaborator can see which reports have been
obtained, by whom, from where, and in which version, and fetch their own copy.
`strata retrieve` never downloads a document; with enrichment enabled it adds a
legal open-access link from Unpaywall for the user to open, and writes the request
to `.strata/network.log`.

## Reasons are a fixed vocabulary

A report that cannot be obtained is a PRISMA item (reports not retrieved, with
reasons), so the reason is one of a fixed list rather than free text. The queue
shows what is outstanding; a report that is deliberately given up on is recorded,
not merely absent.

## Example

```
$ strata retrieve

  204 reports sought. 8 outstanding.

  rpt_3kq8v1r0zx2m4a7b  Cepeda et al. (2008)  Psychological Science
    doi:10.1111/j.1467-9280.2008.02209.x

    [f] I have the file      [u] open DOI in browser      [i] interlibrary loan requested
    [n] not retrievable      [s] skip
```

A manifest entry written by `[f]`:

```json
{"report":"rpt_3kq8v1r0zx2m4a7b","locator":{"doi":"10.1111/j.1467-9280.2008.02209.x","pmid":"19076480"},"version":"version-of-record","path":"cepeda-2008.pdf","retrieved":"2026-03-28","source":"institutional-access","actor":"ethan"}
```
