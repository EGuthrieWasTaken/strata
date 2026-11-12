"""Reading the numbers back out of a drawn plot, for tests about where things are."""

from __future__ import annotations

import re

Point = tuple[float, float]


def numbers(text: str) -> list[float]:
    return [float(n) for n in re.findall(r"-?\d+(?:\.\d+)?", text)]


def attribute(tag: str, name: str) -> str:
    found = re.search(rf'\b{name}="([^"]*)"', tag)
    assert found is not None, f"{tag} has no {name}"
    return found.group(1)


def viewbox(svg: str) -> tuple[float, float]:
    width, height = numbers(attribute(svg, "viewBox"))[2:4]
    return width, height


def line_ends(svg: str, cls: str | None = None) -> list[tuple[float, float, float, float]]:
    """(x1, y1, x2, y2) of every <line>, or only those of one class."""
    tags = re.findall(rf"<line\b[^>]*{f'class=.{cls}.' if cls else ''}[^>]*>", svg)
    return [
        (
            float(attribute(t, "x1")),
            float(attribute(t, "y1")),
            float(attribute(t, "x2")),
            float(attribute(t, "y2")),
        )
        for t in tags
    ]


def polygons(svg: str, cls_pattern: str = ".*") -> list[list[Point]]:
    found = []
    for tag in re.findall(r"<polygon\b[^>]*>", svg):
        if re.fullmatch(cls_pattern, attribute(tag, "class")):
            values = numbers(attribute(tag, "points"))
            found.append(list(zip(values[0::2], values[1::2], strict=True)))
    return found


def every_point(svg: str) -> list[Point]:
    """Every polygon point and every line end in the figure."""
    points = [p for polygon in polygons(svg) for p in polygon]
    for x1, y1, x2, y2 in line_ends(svg):
        points += [(x1, y1), (x2, y2)]
    return points


def funnel_axes_box(svg: str) -> tuple[float, float, float, float]:
    """(left, top, right, bottom) of the box the funnel plot's two axis lines bound."""
    lines = line_ends(svg, "s-ink")
    horizontal = max((ln for ln in lines if ln[1] == ln[3]), key=lambda ln: ln[2] - ln[0])
    vertical = max((ln for ln in lines if ln[0] == ln[2]), key=lambda ln: ln[3] - ln[1])
    return horizontal[0], vertical[1], horizontal[2], vertical[3]


def funnel_data_points(svg: str) -> list[Point]:
    """The corners of the shaded regions and the ends of the two limit lines."""
    points = [p for polygon in polygons(svg, r"f-tint[123]") for p in polygon]
    for x1, y1, x2, y2 in line_ends(svg, "s-ink"):
        if x1 != x2 and y1 != y2:  # the two diagonals, not the axes or ticks
            points += [(x1, y1), (x2, y2)]
    return points


def outside(
    points: list[Point], left: float, top: float, right: float, bottom: float
) -> list[Point]:
    return [
        p
        for p in points
        if not (left - 0.01 <= p[0] <= right + 0.01 and top - 0.01 <= p[1] <= bottom + 0.01)
    ]
