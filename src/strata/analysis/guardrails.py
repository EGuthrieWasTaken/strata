"""Named guardrails (openspec:analysis-specification#guardrails).

Each is a named warning recorded in `run.json`. A warning is shown unless it was acknowledged
(`--ack CODE`), and an acknowledgement is itself recorded. The only *blocking* guardrail is the
underpowered small-study-effect test (fewer than ten studies), which exits with code 8 unless
`--force` is given; a forced bypass is recorded.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from strata.analysis.spec import AnalysisSpec

CODES = (
    "k-lt-3",
    "k-lt-5",
    "k-lt-10-bias-tests",
    "meta-regression-overfitting",
    "cluster-robust:few-clusters",
    "cluster-robust:few-clusters-strong",
    "dependence-ignored",
    "p-value-derived",
    "assumed-correlation",
    "high-heterogeneity",
    "exploratory",
    "freeman-tukey-instability",
    "double-zero-excluded",
    "hk-truncation",
)


class BlockingGuardrail(Exception):
    """A blocking guardrail fired; the CLI exits with code 8 unless `--force` is given."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


@dataclass
class Context:
    spec: AnalysisSpec
    k: int
    n_params: int
    i2: float | None
    multi_effect_studies: list[str]
    handling: str
    p_value_effects: list[str]
    assumed_correlation_effects: list[str]
    fit_warnings: list[str]
    freeman_tukey: str | None
    double_zero: int
    hk_truncated: bool
    bias_requested: bool
    forced: list[str] = field(default_factory=list)


def _named(items: list[str], limit: int = 5) -> str:
    shown = ", ".join(items[:limit])
    return shown + (f" and {len(items) - limit} more" if len(items) > limit else "")


def evaluate(ctx: Context, acknowledged: set[str]) -> list[dict[str, Any]]:
    """Every guardrail that applies, in a fixed order, each marked acknowledged or not."""
    found: list[tuple[str, str, bool]] = []
    random_effects = ctx.spec.section("model")["type"] == "random-effects"
    if random_effects and ctx.k < 3:
        found.append(
            ("k-lt-3", "Random-effects pooling is not meaningful with fewer than 3 studies; "
             "report the studies individually.", False)
        )  # fmt: skip
    if random_effects and ctx.k < 5:
        found.append(
            ("k-lt-5", "tau^2 is very poorly estimated with fewer than 5 studies; prefer "
             "Paule-Mandel or Knapp-Hartung and interpret I^2 with great caution.", False)
        )  # fmt: skip
    if ctx.bias_requested and ctx.k < 10:
        found.append(
            ("k-lt-10-bias-tests", "Publication-bias tests are underpowered with fewer than 10 "
             "studies" + (" (computed with --force; results are labelled underpowered)."
                          if ctx.forced else " (blocked by default)."), True)
        )  # fmt: skip
    if ctx.n_params > 1 and ctx.k / ctx.n_params < 10:
        found.append(
            ("meta-regression-overfitting", f"Meta-regression with k = {ctx.k} effects and "
             f"{ctx.n_params} parameters (k/p < 10): overfitting risk.", False)
        )  # fmt: skip
    for text in ctx.fit_warnings:
        if text.startswith("dependence:cluster-robust:few-clusters-strong"):
            found.append(
                ("cluster-robust:few-clusters-strong", _cluster_message(text, True), False)
            )
        elif text.startswith("dependence:cluster-robust:few-clusters"):
            found.append(("cluster-robust:few-clusters", _cluster_message(text, False), False))
    if ctx.handling == "none" and ctx.multi_effect_studies:
        found.append(
            ("dependence-ignored", f"DEPENDENCE IGNORED: {len(ctx.multi_effect_studies)} study(ies)"
             " "
             f"contribute more than one effect ({_named(ctx.multi_effect_studies)}) but "
             "dependency.handling is none; the pooled interval is too narrow.", False)
        )  # fmt: skip
    if ctx.p_value_effects:
        found.append(
            ("p-value-derived", f"{len(ctx.p_value_effects)} effect(s) were derived from a p-value "
             f"alone, the lowest-quality conversion ({_named(ctx.p_value_effects)}).", False)
        )  # fmt: skip
    if ctx.assumed_correlation_effects:
        found.append(
            ("assumed-correlation", f"{len(ctx.assumed_correlation_effects)} effect(s) use an "
             "assumed "
             "pre-post correlation; state the assumption in the manuscript (results are shown at "
             "r = 0.3, 0.5 and 0.7).", False)
        )  # fmt: skip
    if ctx.i2 is not None and ctx.i2 > 75:
        found.append(
            ("high-heterogeneity", f"I^2 = {ctx.i2:.0f}%: consider whether pooling is appropriate "
             "at all.", False)
        )  # fmt: skip
    if not ctx.spec.preregistered:
        found.append(
            ("exploratory", "This analysis is not marked preregistered and will be reported as "
             "exploratory.", False)
        )  # fmt: skip
    if ctx.freeman_tukey:
        found.append(("freeman-tukey-instability", ctx.freeman_tukey, False))
    if ctx.double_zero:
        found.append(
            ("double-zero-excluded", f"{ctx.double_zero} study(ies) with zero events in both arms "
             "were excluded from this ratio analysis.", False)
        )  # fmt: skip
    if ctx.hk_truncated:
        found.append(
            ("hk-truncation", "The Knapp-Hartung standard error was truncated to the Wald standard "
             "error (metafor's ad hoc rule).", False)
        )  # fmt: skip
    return [
        {
            "code": code,
            "message": message,
            "blocking": blocking,
            "acknowledged": code in acknowledged,
            "forced": bool(ctx.forced) if code == "k-lt-10-bias-tests" else False,
        }
        for code, message, blocking in found
    ]


def _cluster_message(text: str, strong: bool) -> str:
    detail = dict(part.split("=", 1) for part in text.split(":") if "=" in part)
    base = (
        f"Only {detail.get('clusters')} clusters; the Satterthwaite degrees of freedom achieved is "
        f"{detail.get('satterthwaite-df')}."
    )
    return (
        ("STRONG WARNING: " if strong else "")
        + base
        + (
            " Cluster-robust inference is unreliable with so few clusters."
            if strong
            else " Report the Satterthwaite df."
        )
    )
