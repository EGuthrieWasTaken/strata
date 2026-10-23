# Tasks

## 1. Distribution

- [ ] 1.1 Claim or confirm the PyPI name (ship as `strata-review` until the PEP 541 claim on `strata` succeeds)
- [ ] 1.2 Standalone PyInstaller binaries for macOS (universal), Windows (x64), Linux (x64, musl), attached to each release
- [ ] 1.3 Homebrew formula and conda-forge recipe (the container image is `add-container-image`)
- [ ] 1.4 Test the five-minute first run on all three platforms as a release criterion

## 2. Migration imports

- [ ] 2.1 Covidence export import (records and screening decisions)
- [ ] 2.2 Rayyan export import
- [ ] 2.3 EPPI-Reviewer export import
- [x] 2.4 EndNote XML, Excel (`.xlsx`, with size caps), and PRISMA-style citation-list parsers deferred from M1

## 3. Adoption

- [ ] 3.1 Publish a real, small, completed worked-example review in the repository and run it as a regression test
- [ ] 3.2 Complete the documentation set (`project-documentation` spec)
- [ ] 3.3 Translations of the externalised strings

## 4. Tests

- [ ] 4.1 Golden fixtures and fuzz-corpus entries for every new parser
- [ ] 4.2 The nightly `cold-install` job installs each published artefact and runs the quickstart

## Notes

Only task 2.4 is built. 4.1 stays open: it covers every new parser, and the Covidence, Rayyan and
EPPI-Reviewer imports (2.1-2.3) do not exist yet.

- 2.4: EndNote XML (`ingest/parsers/endnote_xml.py`), Excel (`ingest/parsers/xlsx.py`, standard library
  only, with caps on file size, unpacked size, rows, columns and cell length, `--sheet`) and the
  plain-text citation list (`ingest/parsers/citation_list.py`, best effort: Vancouver and APA layouts,
  everything else rejected, records flagged `best-effort-parse` and kept out of automatic merging). Golden
  fixtures under `tests/fixtures/exports/{endnote-xml,citation-list}/`, unit and integration tests, and
  fuzz tests (which found and fixed four ways a corrupt workbook could escape as the wrong exception).
- Limits worth knowing: dates stored in Excel as dates arrive as serial numbers (a year typed as a
  number or text is read as written); the citation-list parser understands two layouts; EndNote's
  `<foreign-keys>`, notes and attachments are not read.

