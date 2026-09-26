# Design: canonical-serialisation

*Informative.* The requirements are in [spec.md](spec.md).

## Why byte identity

Three of the project's correctness guarantees are cross-platform byte-identity
claims: collaborators' files merge without conflict, `strata verify` can compare
regenerated derived files byte for byte, and analyses reproduce exactly on
another machine. None of that survives a serialiser whose output depends on
dict order, hash seeds, locale, or float formatting.

## Why two key orders

The event envelope uses **declared order** (`ev`, `id`, `ts`, `actor`, ...) so an
event reads naturally in a diff. Bodies and records use **lexicographic order**
so there is no ambiguity at all about what bytes get hashed into `digest`.

YAML files are different: they are read and edited by humans, and a coding form
whose fields shuffle alphabetically is unusable, so YAML keeps schema order.

## Why records.ndjson is sorted by id

Ids are content-derived hashes, so sorting by id is stable across machines and
unaffected by import order or later metadata corrections. The cost is that new
records land in hash order rather than at the end of the file — a deliberate
trade of diff compactness for merge stability.

## Why `null` and absent differ

Absent means "never set"; `null` means "explicitly known to be empty". A record
that has been checked and genuinely has no abstract is different from one
nobody has looked at, and field-wise merges need to tell them apart.

## Why 12 significant digits

Floating-point results can differ in the last bits across platforms and BLAS
builds. Rounding generated JSON to 12 significant digits keeps every
scientifically meaningful digit while making the files comparable byte for
byte. Timestamps, hostnames, absolute paths, and random ids are banned from
generated files for the same reason.
