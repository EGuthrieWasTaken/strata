# Design: record-identity

*Informative.* The requirements are in [spec.md](spec.md).

## Determinism is the point

Identifiers must be stable, collision-resistant, and — where possible —
deterministic across independent imports of the same paper. Determinism is what
lets two collaborators import the same Scopus export on different machines and
produce byte-identical files that merge without conflict. That is why ids are
derived from a canonical key rather than assigned.

## Why a truncated hash

`rec_` + the first 10 bytes of `sha256(canonical_key)` in lowercase Crockford
base32 gives 80 bits of entropy: a collision probability below 1e-12 at 10^6
records, ids short enough to read aloud (`rec_3kq8v1r0zx2m4a7b`), and safe in
URLs and filenames on every platform (including case-insensitive filesystems,
since the alphabet is lowercase only).

The ULID fallback (priority 7) is the one non-deterministic branch. It exists
because a row with no title cannot be identified any other way, and it warns
loudly because two collaborators importing that row will get different ids.

## Why ids are permanent

An id is a name, not a checksum. If correcting a DOI changed the id, every event,
alias, export, and collaborator branch naming the old id would dangle. A
correction therefore amends the record and leaves the id alone; merges create
aliases, and every id that ever existed resolves forever.

## Why normalisation is frozen

The normalisation rules feed identity, blocking, and similarity. Changing them
can change every id in an existing repository, so a change is a breaking format
change governed by `openspec:repository-format#format-versioning` — never a
refactor.

## Why criterion numbers are never reused

Historical events cite criteria by id. Reusing `EXC-05` after retiring it would
silently change what every old exclusion citing `EXC-05` means.
