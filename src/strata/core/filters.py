"""The filter expression language: openspec:filter-language (normative).

A small, safe expression language used identically by `--filter` in the CLI,
the (future) web UI, and analysis specifications. openspec:filter-language is explicit that this
MUST NOT be implemented by evaluating the host language (no `eval`, no
`exec`): `parse()` hand-writes a recursive-descent parser producing an AST,
and `evaluate()` walks that AST against a caller-supplied field resolver.

This module knows nothing about what fields exist on a record, a screening
decision, or an effect -- that's the caller's job (see
`strata.core.records.record_field_resolver` for the M1 set of fields this
milestone actually has data for). Keeping field semantics out of the parser
is what lets one grammar serve the CLI, the web UI, and analysis specs
without three copies of it.

Grammar (openspec:filter-language, reproduced here so the parser and the spec
can be read side by side)::

    expr    := or_expr
    or_expr := and_expr ("or" and_expr)*
    and_expr:= not_expr ("and" not_expr)*
    not_expr:= "not" not_expr | primary
    primary := "(" expr ")" | comparison | field
    comparison := field op value
    op      := "==" | "!=" | "<" | "<=" | ">" | ">=" | "in" | "not in" | "contains" | "matches"
    value   := string | number | boolean | null | list

`matches`'s pattern is screened for catastrophic-backtracking shapes before
it ever runs a match -- see `_is_catastrophic`'s docstring for why that is
this module's real defence against a hanging pattern, rather than a runtime
timeout (which does not work against a single call into CPython's `re`
engine, verified empirically during development).
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

FieldResolver = Callable[[str], Any]


class FilterSyntaxError(ValueError):
    """A `--filter` expression could not be parsed (openspec:filter-language)."""


class FilterEvaluationError(ValueError):
    """A parsed filter referenced an unknown field or applied an operator to an
    incompatible value at evaluation time (e.g. `<` between a string and a
    number, or `matches` on a non-string field)."""


# ---- AST -------------------------------------------------------------------


@dataclass(frozen=True)
class FieldRef:
    """A bare field reference used as a full expression, e.g. `stale` alone."""

    name: str


@dataclass(frozen=True)
class Comparison:
    field: str
    op: str
    value: Any


@dataclass(frozen=True)
class Not:
    operand: Node


@dataclass(frozen=True)
class And:
    left: Node
    right: Node


@dataclass(frozen=True)
class Or:
    left: Node
    right: Node


Node = FieldRef | Comparison | Not | And | Or

# ---- Tokenizer ---------------------------------------------------------------

_KEYWORDS = {"and", "or", "not", "in", "contains", "matches", "true", "false", "null"}

_TOKEN_SPEC = [
    ("WS", r"\s+"),
    ("STRING", r"'(?:[^'\\]|\\.)*'|\"(?:[^\"\\]|\\.)*\""),
    ("NUMBER", r"-?\d+(?:\.\d+)?"),
    ("OP", r"==|!=|<=|>=|<|>"),
    ("LPAREN", r"\("),
    ("RPAREN", r"\)"),
    ("LBRACKET", r"\["),
    ("RBRACKET", r"\]"),
    ("COMMA", r","),
    ("IDENT", r"[A-Za-z_][A-Za-z0-9_.]*"),
]
_MASTER_RE = re.compile("|".join(f"(?P<{name}>{pattern})" for name, pattern in _TOKEN_SPEC))
_ESCAPE_RE = re.compile(r"\\(.)")

Token = tuple[str, str]


def _tokenize(text: str) -> list[Token]:
    tokens: list[Token] = []
    pos = 0
    for match in _MASTER_RE.finditer(text):
        if match.start() != pos:
            raise FilterSyntaxError(
                f"unexpected character {text[pos]!r} at position {pos} in {text!r}"
            )
        pos = match.end()
        kind = match.lastgroup
        assert kind is not None  # every alternative in _TOKEN_SPEC is named
        value = match.group()
        if kind == "WS":
            continue
        if kind == "IDENT" and value.lower() in _KEYWORDS:
            value = value.lower()
            kind = value.upper()
        tokens.append((kind, value))
    if pos != len(text):
        raise FilterSyntaxError(f"unexpected character {text[pos]!r} at position {pos} in {text!r}")
    tokens.append(("EOF", ""))
    return tokens


def _unescape_string(token_text: str) -> str:
    return _ESCAPE_RE.sub(lambda m: m.group(1), token_text[1:-1])


# ---- Parser ------------------------------------------------------------------


class _Parser:
    def __init__(self, tokens: list[Token]) -> None:
        self._tokens = tokens
        self._pos = 0

    def _peek(self) -> Token:
        return self._tokens[self._pos]

    def _advance(self) -> Token:
        token = self._tokens[self._pos]
        self._pos += 1
        return token

    def _expect(self, kind: str) -> Token:
        token = self._advance()
        if token[0] != kind:
            raise FilterSyntaxError(f"expected {kind}, got {token[0] or 'end of expression'}")
        return token

    def parse(self) -> Node:
        node = self._or_expr()
        trailing = self._peek()
        if trailing[0] != "EOF":
            raise FilterSyntaxError(f"unexpected trailing input starting at {trailing[1]!r}")
        return node

    def _or_expr(self) -> Node:
        node = self._and_expr()
        while self._peek()[0] == "OR":
            self._advance()
            node = Or(node, self._and_expr())
        return node

    def _and_expr(self) -> Node:
        node = self._not_expr()
        while self._peek()[0] == "AND":
            self._advance()
            node = And(node, self._not_expr())
        return node

    def _not_expr(self) -> Node:
        if self._peek()[0] == "NOT":
            self._advance()
            return Not(self._not_expr())
        return self._primary()

    def _primary(self) -> Node:
        kind, text = self._peek()
        if kind == "LPAREN":
            self._advance()
            node = self._or_expr()
            self._expect("RPAREN")
            return node
        if kind == "IDENT":
            field = self._advance()[1]
            op = self._maybe_op()
            if op is None:
                return FieldRef(field)
            value = self._value()
            return Comparison(field, op, value)
        raise FilterSyntaxError(f"expected a field name or '(', got {text!r}")

    def _maybe_op(self) -> str | None:
        kind, text = self._peek()
        if kind == "OP":
            self._advance()
            return text
        if kind == "IN":
            self._advance()
            return "in"
        if kind == "NOT" and self._tokens[self._pos + 1][0] == "IN":
            self._advance()
            self._advance()
            return "not in"
        if kind == "CONTAINS":
            self._advance()
            return "contains"
        if kind == "MATCHES":
            self._advance()
            return "matches"
        return None

    def _scalar(self) -> Any:
        kind, text = self._advance()
        if kind == "STRING":
            return _unescape_string(text)
        if kind == "NUMBER":
            return float(text) if "." in text else int(text)
        if kind == "TRUE":
            return True
        if kind == "FALSE":
            return False
        if kind == "NULL":
            return None
        raise FilterSyntaxError(f"expected a value, got {text!r}")

    def _value(self) -> Any:
        if self._peek()[0] == "LBRACKET":
            self._advance()
            items: list[Any] = []
            if self._peek()[0] != "RBRACKET":
                items.append(self._scalar())
                while self._peek()[0] == "COMMA":
                    self._advance()
                    items.append(self._scalar())
            self._expect("RBRACKET")
            return items
        return self._scalar()


def parse(expression: str) -> Node:
    """Parse a `--filter` expression into an AST. Raises `FilterSyntaxError`."""
    return _Parser(_tokenize(expression)).parse()


# ---- Interpreter ---------------------------------------------------------------


def _find_nested_unbounded_repeat(subpattern: Any, constants: Any, *, in_repeat: bool) -> bool:
    """True if `subpattern` contains an unbounded repeat nested inside another --
    `(a+)+`, `(a*)+`, `(a+)*`, and similar shapes -- the textbook cause of
    catastrophic (exponential) regex backtracking. See `_is_catastrophic`
    for why this static check, not a runtime timeout, is this module's
    actual defence.
    """
    for op, av in subpattern:
        if op in (constants.MAX_REPEAT, constants.MIN_REPEAT):
            _min_count, max_count, inner = av
            unbounded = max_count == constants.MAXREPEAT
            if unbounded and in_repeat:
                return True
            if _find_nested_unbounded_repeat(inner, constants, in_repeat=in_repeat or unbounded):
                return True
        elif op is constants.SUBPATTERN:
            inner = av[-1]
            if _find_nested_unbounded_repeat(inner, constants, in_repeat=in_repeat):
                return True
        elif op is constants.BRANCH:
            _, branches = av
            for branch in branches:
                if _find_nested_unbounded_repeat(branch, constants, in_repeat=in_repeat):
                    return True
    return False


def _is_catastrophic(pattern: str) -> bool:
    """Heuristic ReDoS guard: does `pattern` nest one unbounded repeat inside
    another? Not exhaustive -- some catastrophic patterns use a different
    shape (e.g. overlapping alternation) that this does not catch -- but it
    is the single most common real-world cause and it is static: no regex
    ever actually runs to find out.

    This is the *primary* defence, not a fallback, because a runtime
    timeout cannot reliably be one here: verified empirically during this
    module's development, a background-thread-plus-`join(timeout)` approach
    failed to bound wall-clock time at all against a genuinely catastrophic
    pattern, because CPython's `re` engine holds the GIL for the entire
    duration of a single `search()` call -- there is no bytecode-level safe
    point for another thread to run at, so the "timed-out" caller's own
    thread cannot even reacquire the GIL to notice the timeout until the
    match finishes on its own (which, for a catastrophic pattern, is
    effectively never). `multiprocessing` is the only mechanism that can
    actually kill a runaway match, and spawning a process per `matches`
    evaluation is far too slow to use across e.g. `strata records list
    --filter` on a large repository.
    """
    try:
        import re._constants as _constants  # type: ignore[import-not-found]
        import re._parser as _parser  # type: ignore[import-not-found]

        parsed = _parser.parse(pattern)
    except Exception:
        return False  # can't introspect this pattern -- don't block on our own limitation
    return _find_nested_unbounded_repeat(parsed, _constants, in_repeat=False)


def _matches(actual: Any, pattern: Any) -> bool:
    if not isinstance(actual, str):
        raise FilterEvaluationError(
            f"'matches' requires a string field, got {type(actual).__name__}"
        )
    if not isinstance(pattern, str):
        raise FilterEvaluationError("'matches' requires a string pattern")
    if _is_catastrophic(pattern):
        raise FilterEvaluationError(
            f"pattern {pattern!r} nests an unbounded repeat inside another "
            "(e.g. `(a+)+`), which can take exponential time to fail to match -- rewrite it"
        )
    try:
        compiled = re.compile(pattern)
    except re.error as exc:
        raise FilterEvaluationError(f"invalid regex {pattern!r}: {exc}") from exc
    return compiled.search(actual) is not None


def _contains(actual: Any, value: Any) -> bool:
    if isinstance(actual, str):
        if not isinstance(value, str):
            raise FilterEvaluationError("'contains' on a string field requires a string value")
        return value.lower() in actual.lower()
    if isinstance(actual, list | tuple | set):
        return value in actual
    raise FilterEvaluationError(f"'contains' is not supported on {type(actual).__name__} values")


def _membership(op: str, actual: Any, value: Any) -> bool:
    if not isinstance(value, list):
        raise FilterEvaluationError(f"'{op}' requires a list value, e.g. {op} ['a', 'b']")
    return (actual in value) if op == "in" else (actual not in value)


def _ordered_compare(op: str, actual: Any, value: Any) -> bool:
    try:
        if op == "<":
            return bool(actual < value)
        if op == "<=":
            return bool(actual <= value)
        if op == ">":
            return bool(actual > value)
        return bool(actual >= value)  # ">="
    except TypeError as exc:
        raise FilterEvaluationError(f"cannot compare {actual!r} {op} {value!r}: {exc}") from exc


def _apply_op(op: str, actual: Any, value: Any) -> bool:
    if op == "==":
        return bool(actual == value)
    if op == "!=":
        return bool(actual != value)
    if op in ("<", "<=", ">", ">="):
        return _ordered_compare(op, actual, value)
    if op in ("in", "not in"):
        return _membership(op, actual, value)
    if op == "contains":
        return _contains(actual, value)
    if op == "matches":
        return _matches(actual, value)
    raise AssertionError(f"unknown operator {op!r}")  # pragma: no cover


def evaluate(node: Node, resolve: FieldResolver) -> bool:
    """Evaluate a parsed filter AST against one record, via `resolve(field_name)`.

    `resolve` raises `FilterEvaluationError` for a field the caller doesn't
    recognise or doesn't have data for yet -- this function propagates that
    as-is rather than treating an unresolvable field as false.
    """
    if isinstance(node, Or):
        return evaluate(node.left, resolve) or evaluate(node.right, resolve)
    if isinstance(node, And):
        return evaluate(node.left, resolve) and evaluate(node.right, resolve)
    if isinstance(node, Not):
        return not evaluate(node.operand, resolve)
    if isinstance(node, FieldRef):
        return bool(resolve(node.name))
    if isinstance(node, Comparison):
        return _apply_op(node.op, resolve(node.field), node.value)
    raise AssertionError(f"unknown AST node {node!r}")  # pragma: no cover


def matches_filter(expression: str, resolve: FieldResolver) -> bool:
    """Parse and evaluate `expression` in one call -- the common case for a
    caller that isn't caching the parsed AST across many records."""
    return evaluate(parse(expression), resolve)
