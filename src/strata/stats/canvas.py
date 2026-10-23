"""A tiny drawing layer: shapes and text in semantic colour classes, rendered to deterministic SVG
(theme-aware, accessible) or PDF (openspec:analysis-plots#deterministic-accessible-plots)."""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from xml.sax.saxutils import escape

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
    text = f"{round(float(value), 2):.2f}".rstrip("0").rstrip(".")
    return "0" if text in ("-0", "") else text


def _hex(color: str) -> tuple[float, float, float]:
    return tuple(int(color[i : i + 2], 16) / 255 for i in (1, 3, 5))  # type: ignore[return-value]


class Canvas:
    def __init__(self, width: float, height: float, title: str, desc: str) -> None:
        self.width = width
        self.height = height
        self.title = title
        self.desc = desc
        self.shapes: list[Shape] = []

    def add(self, *shapes: Shape) -> None:
        """Append shapes in drawing order (later shapes are drawn on top)."""
        for shape in shapes:
            if shape.cls not in CLASSES:
                raise ValueError(f"unknown colour class {shape.cls!r}; one of {', '.join(CLASSES)}")
        self.shapes.extend(shapes)

    # --- SVG ---------------------------------------------------------------------------------

    def _style(self) -> str:
        light = "".join(f"--{n}:{c[0]};" for n, c in PALETTE.items())
        dark = "".join(f"--{n}:{c[1]};" for n, c in PALETTE.items())
        rules = "".join(f".s-{n}{{stroke:var(--{n})}}.f-{n}{{fill:var(--{n})}}" for n in CLASSES)
        return f":root{{{light}}}@media (prefers-color-scheme: dark){{:root{{{dark}}}}}{rules}"

    def render_svg(self) -> str:
        used: dict[str, int] = {}

        def element_id(tag: str, key: object) -> str:
            digest = hashlib.sha256(repr(key).encode("utf-8")).hexdigest()[:8]
            base = f"{tag}-{digest}"
            used[base] = used.get(base, 0) + 1
            return base if used[base] == 1 else f"{base}-{used[base]}"

        w, h = fmt(self.width), fmt(self.height)
        out = [
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" width="{w}" '
            f'height="{h}" role="img" aria-labelledby="strata-title strata-desc">',
            f'<title id="strata-title">{escape(self.title)}</title>',
            f'<desc id="strata-desc">{escape(self.desc)}</desc>',
            f"<style>{self._style()}</style>",
            f'<rect id="{element_id("rect", ("background", self.width, self.height))}" '
            f'class="f-surface" x="0" y="0" width="{w}" height="{h}"/>',
        ]
        for shape in self.shapes:
            out.append(self._svg_shape(shape, element_id))
        out.append("</svg>")
        return "\n".join(out) + "\n"

    @staticmethod
    def _svg_shape(shape: Shape, element_id) -> str:  # type: ignore[no-untyped-def]
        def paint(fill: bool) -> str:
            return f'class="f-{shape.cls}"' if fill else f'class="s-{shape.cls}" fill="none"'

        if isinstance(shape, Line):
            dash = ' stroke-dasharray="4 3"' if shape.dash else ""
            return (
                f'<line id="{element_id("line", shape)}" class="s-{shape.cls}" '
                f'x1="{fmt(shape.x1)}" y1="{fmt(shape.y1)}" x2="{fmt(shape.x2)}" '
                f'y2="{fmt(shape.y2)}" '
                f'stroke-width="{fmt(shape.width)}"{dash}/>'
            )
        if isinstance(shape, Rect):
            return (
                f'<rect id="{element_id("rect", shape)}" {paint(shape.fill)} x="{fmt(shape.x)}" '
                f'y="{fmt(shape.y)}" width="{fmt(shape.w)}" height="{fmt(shape.h)}"/>'
            )
        if isinstance(shape, Polygon):
            points = " ".join(f"{fmt(x)},{fmt(y)}" for x, y in shape.points)
            return (
                f'<polygon id="{element_id("polygon", shape)}" {paint(shape.fill)} '
                f'points="{points}"/>'
            )
        if isinstance(shape, Circle):
            return (
                f'<circle id="{element_id("circle", shape)}" {paint(shape.fill)} '
                f'cx="{fmt(shape.cx)}" cy="{fmt(shape.cy)}" r="{fmt(shape.r)}"/>'
            )
        bold = ' font-weight="bold"' if shape.bold else ""
        rotate = (
            f' transform="rotate({fmt(shape.rotate)} {fmt(shape.x)} {fmt(shape.y)})"'
            if shape.rotate
            else ""
        )
        return (
            f'<text id="{element_id("text", shape)}" class="f-{shape.cls}" x="{fmt(shape.x)}" '
            f'y="{fmt(shape.y)}" font-family="Helvetica, Arial, sans-serif" '
            f'font-size="{fmt(shape.size)}" text-anchor="{shape.anchor}"{bold}{rotate}>'
            f"{escape(shape.text)}</text>"
        )

    # --- PDF ---------------------------------------------------------------------------------

    def render_pdf(self) -> bytes:
        w, h = self.width, self.height
        ops: list[str] = []

        def colour(name: str, stroke: bool) -> str:
            r, g, b = _hex(PALETTE[name][0])
            return f"{fmt(r)} {fmt(g)} {fmt(b)} {'RG' if stroke else 'rg'}"

        def flip(y: float) -> float:
            return h - y

        ops.append(f"{colour('surface', False)}\n0 0 {fmt(w)} {fmt(h)} re f")
        for shape in self.shapes:
            if isinstance(shape, Line):
                dash = "[4 3] 0 d" if shape.dash else "[] 0 d"
                ops.append(
                    f"{colour(shape.cls, True)}\n{fmt(shape.width)} w {dash}\n"
                    f"{fmt(shape.x1)} {fmt(flip(shape.y1))} m {fmt(shape.x2)} "
                    f"{fmt(flip(shape.y2))} l S\n[] 0 d"
                )
            elif isinstance(shape, Rect):
                paint = "f" if shape.fill else "S"
                ops.append(
                    f"{colour(shape.cls, not shape.fill)}\n{fmt(shape.x)} "
                    f"{fmt(flip(shape.y + shape.h))} {fmt(shape.w)} {fmt(shape.h)} re {paint}"
                )
            elif isinstance(shape, Polygon):
                paint = "f" if shape.fill else "S"
                pts = [f"{fmt(x)} {fmt(flip(y))}" for x, y in shape.points]
                path = f"{pts[0]} m " + " ".join(f"{p} l" for p in pts[1:]) + " h"
                ops.append(f"{colour(shape.cls, not shape.fill)}\n{path} {paint}")
            elif isinstance(shape, Circle):
                ops.append(f"{colour(shape.cls, not shape.fill)}\n{_circle(shape, h)}")
            else:
                ops.append(f"{colour(shape.cls, False)}\n{_pdf_text(shape, h)}")
        stream = "\n".join(ops).encode("latin-1") + b"\n"
        objects = [
            b"<< /Type /Catalog /Pages 2 0 R >>",
            b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            (
                f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {fmt(w)} {fmt(h)}] "
                "/Resources << /Font << /F1 4 0 R /F2 5 0 R >> >> /Contents 6 0 R >>"
            ).encode("latin-1"),
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold "
            b"/Encoding /WinAnsiEncoding >>",
            f"<< /Length {len(stream)} >>\nstream\n".encode("latin-1") + stream + b"endstream",
        ]
        out = bytearray(b"%PDF-1.4\n")
        offsets = []
        for number, body in enumerate(objects, start=1):
            offsets.append(len(out))
            out += f"{number} 0 obj\n".encode("latin-1") + body + b"\nendobj\n"
        xref = len(out)
        out += f"xref\n0 {len(objects) + 1}\n".encode("latin-1")
        out += b"0000000000 65535 f \n"
        for offset in offsets:
            out += f"{offset:010d} 00000 n \n".encode("latin-1")
        out += (
            f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n"
        ).encode("latin-1")
        return bytes(out)


def _circle(shape: Circle, height: float) -> str:
    k = 0.5523 * shape.r
    cx, cy, r = shape.cx, height - shape.cy, shape.r
    paint = "f" if shape.fill else "S"
    curves = [
        (cx + r, cy, cx + r, cy + k, cx + k, cy + r, cx, cy + r),
        (cx, cy + r, cx - k, cy + r, cx - r, cy + k, cx - r, cy),
        (cx - r, cy, cx - r, cy - k, cx - k, cy - r, cx, cy - r),
        (cx, cy - r, cx + k, cy - r, cx + r, cy - k, cx + r, cy),
    ]
    path = f"{fmt(cx + r)} {fmt(cy)} m " + " ".join(
        " ".join(fmt(v) for v in c[2:]) + " c" for c in curves
    )
    return f"{path} h {paint}"


def _pdf_text(shape: Text, height: float) -> str:
    safe = shape.text.encode("latin-1", errors="replace").decode("latin-1")
    safe = safe.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    x = shape.x
    if not shape.rotate:
        width = 0.5 * shape.size * len(shape.text)
        x -= {"middle": width / 2, "end": width}.get(shape.anchor, 0.0)
    angle = math.radians(-shape.rotate)
    c, s = math.cos(angle), math.sin(angle)
    font = "F2" if shape.bold else "F1"
    return (
        f"BT /{font} {fmt(shape.size)} Tf {fmt(c)} {fmt(s)} {fmt(-s)} {fmt(c)} "
        f"{fmt(x)} {fmt(height - shape.y)} Tm ({safe}) Tj ET"
    )
