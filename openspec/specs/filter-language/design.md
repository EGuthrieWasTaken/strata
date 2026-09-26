# Design: filter-language

*Informative.* The requirements are in [spec.md](spec.md).

## Why a small language instead of `eval`

The same filters appear in the CLI, the web UI, the MCP server, and analysis
specifications — and in the hosted deployment they come from other people's
browsers. Evaluating host-language code would turn every filter box into a code
execution surface. A parsed, interpreted AST keeps the language exactly as
powerful as it needs to be.

## Why `matches` is bounded

User-supplied regular expressions can backtrack catastrophically. A pattern
like `(a+)+$` must not be able to hang the tool, so `matches` uses a linear-time
engine or a hard bound.

## Examples

```
year >= 2000 and tiab == 'include'
abstract contains 'randomi' and not (journal contains 'Proceedings')
stale == true and fulltext == 'include'
rob_overall in ['low', 'some-concerns']
criteria contains 'EXC-03'
```
