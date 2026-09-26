# Design: copyright-and-licensing

*Informative.* The requirements are in [spec.md](spec.md).

## Why this matters more than usual

The natural workflow of a systematic review involves mass-downloading
copyrighted articles. Committing 400 publisher PDFs to a GitHub repository is
copyright infringement at scale, and the tool must not lead users there
casually — hence `.gitignore` excluding `fulltext/` and a refusal to stage PDFs
without an explicit override.

## Identifiers, not files

The provenance chain (which document was assessed, in which version) is kept by
DOI or equivalent in `fulltext/manifest.ndjson`, without redistributing the
document. Content hashes are deliberately not used: annotating a PDF changes its
bytes without changing the document, so a hash would report two copies of the
same paper as different in the ordinary case. The Zotero integration planned
for M6 fills the practical gap: Zotero owns the documents, `strata` owns the
decisions.

## Legitimate sources only

No Sci-Hub, no LibGen, no institutional-proxy credential handling, no scraping
of subscription databases. `strata` consumes the exports those platforms
provide for exactly this purpose.

## The review's own data

`project.license` declares the licence for the review data, and the
reproducibility package includes it. Bibliographic metadata is generally not
copyrightable; abstracts generally are, which users planning to publish their
screening dataset should know.

## Licences

`strata` is GPL-3.0-or-later. Whether the repository format and its schemas
should be released permissively, so other tools can read and write `strata`
repositories, is open question Q2 in
[docs/open-questions.md](../../../docs/open-questions.md).
