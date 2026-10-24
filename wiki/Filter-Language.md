# Filter language

The same small, safe expression language selects records everywhere in `strata`: `--filter` on
`strata records list`, `strata screen` and `strata assign`, the search box in the
[web interface](The-Web-Interface), and the `include.filter` and `subset` entries of an
[analysis](Analysis). It is parsed, never evaluated as code, so a hostile expression cannot run anything.

```
strata records list --filter "year >= 2015 and title contains 'spacing'"
strata screen title-abstract --by ada --filter "journal contains 'Education' and not year < 2010"
```

## Grammar

```
expression := term ("or" term)*
term       := factor ("and" factor)*
factor     := "not" factor | "(" expression ")" | field operator value | field
operator   := ==  !=  <  <=  >  >=  in  "not in"  contains  matches
value      := 'text' | "text" | number | true | false | null | [value, value, ...]
```

`and` binds tighter than `or`; use parentheses to be sure. A bare `field` is true when it has a value.

| Operator | Meaning |
|---|---|
| `==`, `!=`, `<`, `<=`, `>`, `>=` | comparison (numbers compare as numbers, text as text) |
| `in`, `not in` | membership in a list: `year in [2018, 2019]`, `id in ['rec_...', 'rec_...']` |
| `contains` | case-insensitive substring in text (`title contains 'SPACING'`); for `authors`, whether any author's family name matches |
| `matches` | a regular expression; evaluated with a guard against patterns that could hang |

## Fields you can use today

| Field | Type | Notes |
|---|---|---|
| `id`, `doi`, `pmid` | text | |
| `title`, `abstract`, `journal` | text | `contains` is case-insensitive |
| `year` | number | |
| `authors` | list | `authors contains 'Cepeda'` tests each author's family name |
| `via`, `search` | text | The record's first source: `database` or an other-method name, and the search id |
| `rob_overall`, `rob.D1`, ... | text | A study's risk-of-bias judgement, where a filter is applied to studies and effects (analyses, exports) |

## Fields that are specified but not available yet

The language reserves these, and a filter that uses one stops with the message "field ... is not available
yet": `tiab`, `fulltext` (a record's screening state), `stale`, `criteria` (the criteria cited), and
`actor_decision.<handle>` (one reviewer's opinion). Extraction fields and effect-level fields (`derived_from_pvalue`,
`assumed_correlation`) are likewise available only where a filter is applied to extracted data. Until the
screening-state fields exist, select by `id in [...]` built from `derived/pool.tsv` (see
[Screening](Screening#moving-to-full-text) and [Known limitations](Known-Limitations)).

## Tips

- Quote text with single quotes inside a double-quoted shell argument: `--filter "title contains 'spacing'"`.
- Test an expression on `strata records list --filter ...` before you use it to assign or screen.
- A typo in a field name is an error, not an empty result.
