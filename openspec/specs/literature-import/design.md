# Design: literature-import

*Informative.* The requirements are in [spec.md](spec.md).

## Why the query string cannot be skipped

PRISMA item 7 requires the full search strategy for every database, and
reconstructing it after the fact is the single most common reason systematic
reviews fail replication. Recording `query: "PENDING"` lets the user move on
without losing track: `strata status` keeps reporting the gap until it is
filled. Where an export carries its own query, `strata` offers it for
confirmation rather than accepting it silently, because the export's idea of the
query and the user's may differ.

## Why the raw export is kept byte-for-byte

The raw file under `imports/<id>/raw/` is the ground truth. Parsers improve over
time; a review can be re-derived from its raw exports with a better parser, but
never from a lossy parse.

## Losing records loudly

A row that cannot be parsed must not abort the import, and must not vanish
either. It goes to `rejected.txt` with its line number and error, is counted in
the manifest, and is reported. Losing three records silently is worse than
losing three records loudly.

## Why CSV mapping is profile-driven

CSV exports vary per platform and per user configuration, so the mapping cannot
be hard-coded. Header-signature profiles cover the common platforms; anything
else gets an explicit mapping that is saved and offered again next time.

## Why an exact-id match is not a dedup candidate

The same DOI arriving from MEDLINE and Embase is the same record by
construction. Appending a source to the existing record keeps the provenance
("found by both searches") without creating work for the dedup queue.

## Other sources

PRISMA 2020 tracks records found outside database searching separately, and the
flow diagram has a second column for them. `--via` tags carry that distinction
from import through to the diagram. Citation chasing itself is out of scope; its
results import like any other export.
