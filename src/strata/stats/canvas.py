"""A tiny drawing layer: shapes and text in semantic colour classes, rendered to deterministic SVG
(theme-aware, accessible) or PDF (openspec:analysis-plots#deterministic-accessible-plots)."""

from __future__ import annotations

from dataclasses import dataclass

CLASSES = (
    "ink", "muted", "grid", "accent", "accent2", "band", "tint1", "tint2", "tint3", "surface",
)  # fmt: skip

# Okabe-Ito based, colour-blind safe. (light, dark)
PALETTE: dict[str, tuple[str, str]] = {
    "ink": ("#1a1a1a", "#f2f2f2"),
    "muted": ("#595959", "#bdbdbd"),
    "grid": ("#d9d9d9", "#404040"),
    "accent": ("#0072B2", "#56B4E9"),
    "accent2": ("#D55E00", "#E69F00"),
    "band": ("#cce3f1", "#1f4f6b"),
    "tint1": ("#e6e6e6", "#2e2e2e"),
    "tint2": ("#d0d0d0", "#3d3d3d"),
    "tint3": ("#b8b8b8", "#4f4f4f"),
    "surface": ("#ffffff", "#121212"),
}


@dataclass(frozen=True)
class Line:
    x1: float
    y1: float
    x2: float
    y2: float
    cls: str = "ink"
    dash: bool = False
    width: float = 1.0


@dataclass(frozen=True)
class Rect:
    x: float
    y: float
    w: float
    h: float
    cls: str = "ink"
    fill: bool = True


@dataclass(frozen=True)
class Polygon:
    points: tuple[tuple[float, float], ...]
    cls: str = "ink"
    fill: bool = True


@dataclass(frozen=True)
class Circle:
    cx: float
    cy: float
    r: float
    cls: str = "ink"
    fill: bool = True


@dataclass(frozen=True)
class Text:
    x: float
    y: float
    text: str
    cls: str = "ink"
    anchor: str = "start"  # "start" | "middle" | "end"
    size: float = 11.0
    bold: bool = False
    rotate: float = 0.0  # degrees, clockwise, about (x, y)


Shape = Line | Rect | Polygon | Circle | Text


def fmt(value: float) -> str:
    """At most two decimals, trailing zeros removed, never "-0" or an exponent."""
    raise NotImplementedError


class Canvas:
    def __init__(self, width: float, height: float, title: str, desc: str) -> None:
        self.width = width
        self.height = height
        self.title = title
        self.desc = desc
        self.shapes: list[Shape] = []

    def add(self, *shapes: Shape) -> None:
        """Append shapes in drawing order (later shapes are drawn on top)."""
        raise NotImplementedError

    def render_svg(self) -> str:
        raise NotImplementedError

    def render_pdf(self) -> bytes:
        raise NotImplementedError
