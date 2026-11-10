"""The funnel plot's confidence limits and significance regions stay inside its axes.

On a review of four studies with similar effects (the wiki Quickstart's) the limit lines from the
apex are drawn out to where they would reach the widest standard error, which is far beyond the
plot's horizontal range: they ran from x = -30 to x = 630 on a 560 px figure, through the axis and
its label and out of the picture, while the shaded regions beside them were clamped to the box.
"""

from __future__ import annotations

from types import SimpleNamespace

from strata.analysis import plots
from tests.unit import _svg as svg_mod

# yi and se of the Quickstart's four studies (standardised mean differences).
EFFECTS = [(0.5276, 0.1857), (0.5086, 0.2134), (0.4417, 0.2368), (0.4104, 0.2006)]
POOLED = 0.476


def _funnel_svg(effects: list[tuple[float, float]] = EFFECTS, pooled: float = POOLED) -> str:
    spec = SimpleNamespace(measure="SMD", title="Effect of spaced practice")
    result = SimpleNamespace(
        units=[SimpleNamespace(yi=yi, vi=se * se) for yi, se in effects],
        estimates={"pooled": {"coefficients": [{"estimate": pooled}]}},
    )
    return plots.render(plots.funnel(spec, result), "svg").decode("utf-8")  # type: ignore[arg-type]


def test_the_limit_lines_and_regions_stay_inside_the_axes_on_the_quickstart_data() -> None:
    svg = _funnel_svg()
    box = svg_mod.funnel_axes_box(svg)
    points = svg_mod.funnel_data_points(svg)
    assert svg_mod.outside(points, *box) == [], box
    width, height = svg_mod.viewbox(svg)
    assert svg_mod.outside(svg_mod.every_point(svg), 0, 0, width, height) == []


def test_each_limit_line_is_a_straight_line_from_the_apex_on_the_pooled_estimate() -> None:
    svg = _funnel_svg()
    diagonals = [ln for ln in svg_mod.line_ends(svg, "s-ink") if ln[0] != ln[2] and ln[1] != ln[3]]
    assert len(diagonals) == 2
    apexes = {(round(ln[0], 1), round(ln[1], 1)) for ln in diagonals}
    assert len(apexes) == 1  # both start at the same point: the pooled estimate at standard error 0
    left, top, right, bottom = svg_mod.funnel_axes_box(svg)
    ax, ay = apexes.pop()
    assert ay == top and left < ax < right
    ends = sorted(ln[2] for ln in diagonals)
    assert ends[0] < ax < ends[1]  # one limit goes down and left, the other down and right
    # Cut, not bent: the two limits are mirror images about the pooled estimate's vertical.
    slopes = [abs((ln[2] - ln[0]) / (ln[3] - ln[1])) for ln in diagonals]
    assert abs(slopes[0] - slopes[1]) < 1e-3


def test_the_shaded_regions_keep_the_slope_of_the_significance_boundary() -> None:
    """A region's slanted edge is the line |yi| = z * se. Clamping its far corner to the box (the
    old drawing) turned it into a diagonal to the corner; cutting it keeps the true slope."""
    svg = _funnel_svg()
    left, top, right, bottom = svg_mod.funnel_axes_box(svg)
    for polygon in svg_mod.polygons(svg, r"f-tint[123]"):
        slanted = [
            (a, b)
            for a, b in zip(polygon, polygon[1:] + polygon[:1], strict=True)
            if a[0] != b[0] and a[1] != b[1]
        ]
        assert slanted, polygon
        for a, b in slanted:
            # The true boundary is shallower than the box's corner-to-corner diagonal, which is
            # what clamping the far corner to the box produced.
            assert abs((b[0] - a[0]) / (b[1] - a[1])) < (right - left) / (bottom - top)
