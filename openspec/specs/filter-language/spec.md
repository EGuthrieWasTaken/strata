# filter-language Specification

## Purpose

The small, safe `--filter` expression language used identically by the CLI, the
web UI, and analysis specifications to select records and effects — parsed to
an AST and interpreted, never evaluated as host-language code.

Rationale: `docs/spec/10-cli.md` §3.

## Requirements

### Requirement: No host-language evaluation

The filter language MUST NOT be implemented by evaluating the host language (no
`eval`, no `exec`); it MUST be parsed to an AST and interpreted.

_Source: `docs/spec/10-cli.md` §3_

#### Scenario: Injection attempt

- **WHEN** a filter such as `__import__('os').system('rm -rf ~')` is supplied
- **THEN** it is rejected as a parse error and nothing is executed

### Requirement: Grammar

Filters MUST follow this grammar:

```
expr       := or_expr
or_expr    := and_expr ("or" and_expr)*
and_expr   := not_expr ("and" not_expr)*
not_expr   := "not" not_expr | primary
primary    := "(" expr ")" | comparison | field
comparison := field op value
op         := "==" | "!=" | "<" | "<=" | ">" | ">=" | "in" | "not in" | "contains" | "matches"
value      := string | number | boolean | null | list
```

_Source: `docs/spec/10-cli.md` §3_

#### Scenario: Precedence

- **WHEN** `year >= 2000 and tiab == 'include' or stale == true` is parsed
- **THEN** `and` binds tighter than `or`

#### Scenario: Negated group

- **WHEN** `abstract contains 'randomi' and not (journal contains 'Proceedings')` is evaluated
- **THEN** records from proceedings are excluded from the match

### Requirement: Available fields

The language MUST expose these fields, with the listed semantics:

| Field | Type | Notes |
|---|---|---|
| `id`, `doi`, `pmid` | string | |
| `title`, `abstract`, `journal` | string | `contains` is case-insensitive substring; `matches` is a regex |
| `year` | integer | |
| `authors` | list of strings | `contains` tests any family name |
| `tiab`, `fulltext` | string | Screening state |
| `stale` | boolean | |
| `criteria` | list | Criteria cited at the resolved decision |
| `via` | string | `database`, `citation-searching`, ... |
| `search` | string | Search id |
| `actor_decision.<handle>` | string | One reviewer's opinion |
| `<moderator>` / `<extraction field>` | per schema | Available once extracted |
| `rob_overall`, `rob.<domain>` | string | |
| `derived_from_pvalue`, `assumed_correlation` | boolean/number | Effect-level |

_Source: `docs/spec/10-cli.md` §3_

#### Scenario: Case-insensitive contains

- **WHEN** `title contains 'SPACING'` is evaluated against a record titled "Spacing effects in learning"
- **THEN** it matches

#### Scenario: Criterion cited

- **WHEN** `criteria contains 'EXC-03'` is evaluated
- **THEN** it matches exactly the records whose resolved decision cites `EXC-03`

#### Scenario: One reviewer's opinion

- **WHEN** `actor_decision.sam == 'exclude'` is evaluated
- **THEN** it matches records whose current opinion from `sam` is `exclude`

### Requirement: Regex safety

`matches` MUST use a linear-time regex engine or enforce a timeout, so
user-supplied patterns cannot hang the tool.

_Source: `docs/spec/10-cli.md` §3; `docs/spec/13-nonfunctional.md` §5_

#### Scenario: Catastrophic backtracking pattern

- **WHEN** `title matches '(a+)+$'` is evaluated over a long title
- **THEN** evaluation is refused or bounded rather than hanging
