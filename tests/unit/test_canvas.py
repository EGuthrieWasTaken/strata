"""The drawing layer: deterministic, accessible SVG and PDF."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET

import pytest

from strata.stats import canvas as cv

NS = "{http://www.w3.org/2000/svg}"


def _sample() -> cv.Canvas:
    c = cv.Canvas(200, 100, "A <test> & plot", "Two lines and a label")
    c.add(
        cv.Line(10, 10, 190, 10, "grid", dash=True),
        cv.Rect(20, 20, 50, 30, "band"),
        cv.Rect(80, 20, 50, 30, "ink", fill=False),
        cv.Polygon(((100, 60), (110, 70), (100, 80), (90, 70)), "accent"),
        cv.Circle(150, 70, 5, "accent2"),
        cv.Text(100, 95, "Hello (world) \\ & <b>", "muted", anchor="middle", bold=True),
        cv.Text(5, 50, "rot", "ink", rotate=-90),
    )
    return c


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (0, "0"), (1, "1"), (1.5, "1.5"), (1.25, "1.25"), (1.005, "1"), (1.006, "1.01"),
        (-0.0, "0"), (-0.001, "0"), (-2.5, "-2.5"), (1234567.891, "1234567.89"), (1e-9, "0"),
    ],
)  # fmt: skip
def test_fmt_is_short_and_never_negative_zero_or_exponential(value: float, expected: str) -> None:
    assert cv.fmt(value) == expected


def test_svg_is_well_formed_and_accessible() -> None:
    svg = _sample().render_svg()
    root = ET.fromstring(svg)
    assert root.tag == NS + "svg"
    assert root.get("viewBox") == "0 0 200 100"
    assert root.get("role") == "img"
    assert root.get("aria-labelledby") == "strata-title strata-desc"
    title = root.find(NS + "title")
    desc = root.find(NS + "desc")
    assert title is not None and title.get("id") == "strata-title"
    assert title.text == "A <test> & plot"
    assert desc is not None and desc.get("id") == "strata-desc"
    assert desc.text == "Two lines and a label"
    assert svg.endswith("\n") and "\r" not in svg


def test_svg_has_light_and_dark_themes_and_a_background() -> None:
    svg = _sample().render_svg()
    assert "prefers-color-scheme: dark" in svg
    for name, (light, dark) in cv.PALETTE.items():
        assert light in svg and dark in svg, name
    root = ET.fromstring(svg)
    first_shape = [e for e in root if e.tag not in (NS + "title", NS + "desc", NS + "style")][0]
    assert first_shape.tag == NS + "rect"
    assert first_shape.get("class") == "f-surface"
    assert first_shape.get("width") == "200" and first_shape.get("height") == "100"


def test_svg_uses_classes_not_raw_colours_on_shapes() -> None:
    root = ET.fromstring(_sample().render_svg())
    classes = {e.get("class") for e in root.iter() if e.get("class")}
    assert {"s-grid", "f-band", "s-ink", "f-accent", "f-accent2", "f-muted"} <= classes
    for element in root.iter():
        assert element.get("fill") in (None, "none")
        assert element.get("stroke") is None


def test_svg_shapes_are_drawn_in_order_with_the_expected_geometry() -> None:
    root = ET.fromstring(_sample().render_svg())
    body = [e for e in root if e.tag not in (NS + "title", NS + "desc", NS + "style")]
    assert [e.tag.removeprefix(NS) for e in body] == [
        "rect", "line", "rect", "rect", "polygon", "circle", "text", "text",
    ]  # fmt: skip
    line = body[1]
    assert (line.get("x1"), line.get("y2"), line.get("stroke-dasharray")) == ("10", "10", "4 3")
    outline = body[3]
    assert outline.get("fill") == "none" and outline.get("class") == "s-ink"
    assert body[4].get("points") == "100,60 110,70 100,80 90,70"
    circle = body[5]
    assert (circle.get("cx"), circle.get("cy"), circle.get("r")) == ("150", "70", "5")
    label = body[6]
    assert label.text == "Hello (world) \\ & <b>"
    assert label.get("text-anchor") == "middle" and label.get("font-weight") == "bold"
    assert label.get("font-size") == "11"
    rotated = body[7]
    assert rotated.get("transform") == "rotate(-90 5 50)"


def test_element_ids_are_content_derived_unique_and_stable() -> None:
    first = _sample().render_svg()
    second = _sample().render_svg()
    assert first == second  # byte-identical
    ids = re.findall(r'\bid="((?:line|rect|polygon|circle|text)-[0-9a-f]{8}(?:-\d+)?)"', first)
    assert len(ids) == 8 and len(set(ids)) == 8
    other = cv.Canvas(200, 100, "t", "d")
    other.add(cv.Circle(150, 70, 5, "accent2"))
    circle_id = re.search(r'id="(circle-[0-9a-f]{8})"', other.render_svg())
    assert circle_id is not None and circle_id.group(1) in ids


def test_identical_shapes_get_distinct_ids() -> None:
    c = cv.Canvas(50, 50, "t", "d")
    c.add(cv.Line(0, 0, 10, 10), cv.Line(0, 0, 10, 10), cv.Line(0, 0, 10, 10))
    ids = re.findall(r'<line [^>]*\bid="([^"]+)"', c.render_svg())
    assert len(ids) == 3 and len(set(ids)) == 3
    assert ids[1] == ids[0] + "-2" and ids[2] == ids[0] + "-3"


def test_pdf_is_deterministic_and_structurally_valid() -> None:
    pdf = _sample().render_pdf()
    assert pdf == _sample().render_pdf()
    assert pdf.startswith(b"%PDF-1.4\n") and pdf.endswith(b"%%EOF\n")
    assert b"/MediaBox [0 0 200 100]" in pdf
    assert b"/BaseFont /Helvetica" in pdf and b"/BaseFont /Helvetica-Bold" in pdf
    assert b"/CreationDate" not in pdf and b"/ID" not in pdf
    start = int(re.search(rb"startxref\n(\d+)\n%%EOF", pdf).group(1))  # type: ignore[union-attr]
    assert pdf[start : start + 4] == b"xref"
    table = pdf[start:].split(b"\n")
    count = int(table[1].split()[1])
    for number in range(1, count):
        offset = int(table[2 + number].split()[0])
        assert pdf[offset:].startswith(f"{number} 0 obj".encode())


def test_pdf_text_is_escaped_and_y_is_flipped() -> None:
    pdf = _sample().render_pdf()
    assert rb"(Hello \(world\) \\ & <b>) Tj" in pdf
    assert b"\n0 0 200 100 re" in pdf or b" 0 0 200 100 re" in pdf  # the background
    assert b"10 90 m" in pdf and b"190 90 l" in pdf  # the line at svg y = 10 -> pdf y = 90


def test_pdf_replaces_characters_outside_latin_1() -> None:
    c = cv.Canvas(50, 50, "t", "d")
    c.add(cv.Text(5, 20, "tau² ≤ τ"))
    pdf = c.render_pdf()
    assert b"(tau\xb2 ? ?) Tj" in pdf


def test_unknown_colour_classes_are_rejected() -> None:
    c = cv.Canvas(50, 50, "t", "d")
    with pytest.raises(ValueError, match="colour class"):
        c.add(cv.Line(0, 0, 1, 1, "magenta"))
