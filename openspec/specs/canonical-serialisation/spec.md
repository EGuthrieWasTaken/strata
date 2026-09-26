# canonical-serialisation Specification

## Purpose

Byte-exact serialisation rules for every file `strata` writes — NDJSON, YAML,
TSV, and generated numeric output — so the same logical content produces the
same bytes on any platform. Cross-platform byte identity is what keeps merges
conflict-free and lets `strata verify` compare regenerated output byte for byte.

Rationale and worked examples: [design.md](design.md).

## Requirements

### Requirement: Byte-identical output

Any file `strata` writes MUST be byte-identical given the same logical content,
on any platform, across runs, and under any Python hash seed.
`parse(canon(x)) == x` MUST hold for every schema.

#### Scenario: Randomised hash seed

- **GIVEN** the same logical record
- **WHEN** it is serialised under two different `PYTHONHASHSEED` values on Linux and Windows
- **THEN** the outputs are byte-identical

#### Scenario: Round trip

- **WHEN** any schema object is serialised canonically and parsed back
- **THEN** the parsed value equals the original

### Requirement: NDJSON rules

NDJSON files MUST follow these rules:

- One JSON value per line, UTF-8, LF, trailing newline at end of file; no
  literal newlines inside values.
- Object keys in **schema-declared order** for the event envelope, and
  **lexicographic order** inside `body` and inside record objects.
- Separators exactly `,` and `:` with no spaces.
- Non-ASCII characters emitted literally (`ensure_ascii=false`).
- Integers as integers; floats with shortest round-trip (`repr`-style)
  representation. `NaN` and `Infinity` MUST NOT be emitted.
- `null` and absent are distinct: absent means "never set", `null` means
  "explicitly known to be empty".

#### Scenario: Body keys are sorted

- **WHEN** an event with body `{"stage": ..., "decision": ..., "criteria": ...}` is written
- **THEN** the body keys appear in the order `criteria`, `decision`, `stage`
- **AND** the envelope keys appear in the declared order `ev`, `id`, `ts`, `actor`, `seq`, `body`, `tool`, `prev`, `digest`

#### Scenario: Non-finite float

- **WHEN** a value to be serialised is `NaN`
- **THEN** serialisation fails rather than emitting `NaN`

#### Scenario: Non-ASCII title

- **WHEN** a record titled `Über das Gedächtnis` is written
- **THEN** the title appears literally, not as `\u` escapes

### Requirement: records.ndjson ordering

`records/records.ndjson` MUST be sorted by `id`, ascending, byte-wise, so its
order is stable across machines and unaffected by import order or metadata
corrections.

#### Scenario: Import order does not affect file order

- **GIVEN** two exports imported in opposite orders on two clones
- **WHEN** `records/records.ndjson` is written on each
- **THEN** both files are byte-identical

### Requirement: YAML rules

YAML files MUST use block style, two-space indent, no tabs, no aliases or
anchors, and no flow mappings. Keys MUST be written in schema-declared order,
not sorted. Strings are quoted only when YAML requires it; long prose uses block
scalars (`>` folded for definitions, `|` literal for query strings, which MUST
be preserved verbatim). Version numbers, ids, and anything that could be read as
a number, date, or boolean MUST be quoted.

#### Scenario: Search query written as a literal block

- **WHEN** a multi-line search query is saved
- **THEN** it is written as a `|` literal block scalar and reads back byte-for-byte

#### Scenario: Id that looks like a number

- **WHEN** a value such as `"1990"` or `"yes"` is written as a string
- **THEN** it is quoted so it is not coerced to an integer or boolean on load

### Requirement: TSV rules

Derived TSV views MUST be tab-separated, LF-terminated, with one header row and
no quoting. Tabs, CR, and LF inside a field MUST be replaced with a single space
at write time. Columns are fixed per view and rows sorted by the view's declared
sort key.

#### Scenario: Title containing a tab

- **WHEN** a record whose title contains a tab character is written to a TSV view
- **THEN** the tab is replaced with a single space and the row has the declared column count

### Requirement: Deterministic generated output

Implementations MUST round every float in `analysis/results/**/*.json` to 12
significant digits before serialisation, and MUST NOT embed timestamps,
hostnames, absolute paths, locale-dependent formatting, or random ids in any
generated file. SVG output MUST use fixed element ids derived from content, not
counters or UUIDs.

#### Scenario: Regenerating results on another machine

- **GIVEN** a committed `analysis/results/primary/estimates.json`
- **WHEN** the analysis is rerun on a different platform at the same commit
- **THEN** the file is byte-identical
