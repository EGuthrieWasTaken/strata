"""What the web interface's templates and stylesheet promise about accessibility, without a browser.

`tests/browser/test_pages_browser.py` checks the same promises in a real Chromium, but needs Node
and Playwright (the `browser` CI job installs them; locally the tests are skipped without them).
These are the parts that can be read off the files, so they run everywhere
(openspec:web-ui#accessibility, openspec:web-ui#localhost-security):

* the Content-Security-Policy is `style-src 'self'`, so a template must not carry a `style=`
  attribute: the browser would drop it silently (the screening progress bar once did);
* the colour tokens meet WCAG 2.1 AA in both schemes: text 4.5:1, and 3:1 for a boundary a person
  has to see (the drop target's border, which used `--border` at 1.6:1 in light and 1.9:1 in dark);
* a table that does not stack into cards scrolls inside its own box rather than pushing the page
  sideways.
"""

import re
from pathlib import Path

import pytest

WEB = Path(__file__).resolve().parents[2] / "src" / "strata" / "web"
CSS = (WEB / "static" / "style.css").read_text(encoding="utf-8")
TEMPLATES = sorted((WEB / "templates").glob("*.html"))


def _tokens(block: str) -> dict[str, str]:
    return dict(re.findall(r"--([a-z-]+):\s*(#[0-9a-fA-F]{6})", block))


def _schemes() -> dict[str, dict[str, str]]:
    light = _tokens(CSS[CSS.index(":root") : CSS.index("@media (prefers-color-scheme: dark)")])
    dark_start = CSS.index("@media (prefers-color-scheme: dark)")
    dark = {**light, **_tokens(CSS[dark_start : CSS.index("* {", dark_start)])}
    return {"light": light, "dark": dark}


def _luminance(hex_colour: str) -> float:
    def channel(value: int) -> float:
        v = value / 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4

    r, g, b = (int(hex_colour[i : i + 2], 16) for i in (1, 3, 5))
    return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)


def _ratio(a: str, b: str) -> float:
    high, low = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (high + 0.05) / (low + 0.05)


def test_the_policy_forbids_inline_styles_and_no_template_has_one() -> None:
    app = (WEB / "app.py").read_text(encoding="utf-8")
    assert "style-src 'self'" in app and "unsafe-inline" not in app.split("_CSP")[1].split(")")[0]
    offenders = [t.name for t in TEMPLATES if re.search(r"""\sstyle\s*=\s*["']""", t.read_text())]
    assert offenders == [], f"inline style attributes are blocked by the CSP: {offenders}"


@pytest.mark.parametrize("scheme", ["light", "dark"])
def test_text_colours_reach_4_5_to_1_on_the_background(scheme: str) -> None:
    tokens = _schemes()[scheme]
    for name in ("fg", "muted", "accent", "include", "exclude", "maybe"):
        assert _ratio(tokens[name], tokens["bg"]) >= 4.5, f"--{name} in {scheme}"


@pytest.mark.parametrize("scheme", ["light", "dark"])
def test_the_drop_target_border_reaches_3_to_1_on_the_background(scheme: str) -> None:
    tokens = _schemes()[scheme]
    assert _ratio(tokens["border-strong"], tokens["bg"]) >= 3, f"--border-strong in {scheme}"
    assert re.search(r"\.dropzone\s*\{[^}]*border:\s*2px dashed var\(--border-strong\)", CSS)
    # The dragging state uses the accent, which must also be a visible boundary.
    assert _ratio(tokens["accent"], tokens["bg"]) >= 3


def test_every_table_that_does_not_stack_scrolls_inside_its_own_box() -> None:
    unwrapped = []
    for template in TEMPLATES:
        text = template.read_text(encoding="utf-8")
        for match in re.finditer(r"<table\b[^>]*>", text):
            if "stack-table" in match.group(0):
                continue
            before = text[: match.start()].rstrip()
            if not before.endswith('tabindex="0">') or 'class="table-scroll"' not in before[-220:]:
                unwrapped.append(template.name)
    assert unwrapped == [], (
        f"a wide table here would push the page sideways: {sorted(set(unwrapped))}"
    )
    assert re.search(r"\.table-scroll\s*\{[^}]*overflow-x:\s*auto", CSS)


def test_the_page_breaks_long_words_without_squeezing_table_columns() -> None:
    """`overflow-wrap: anywhere` on the body lowers every table column's minimum width, so a column
    is squeezed below its longest word ("Yea/r") instead of the table scrolling in its box."""
    body = re.search(r"\nbody\s*\{.*?\n\}", CSS, re.S)
    assert body is not None
    rule = re.sub(r"/\*.*?\*/", "", body.group(0), flags=re.S)
    assert "overflow-wrap: break-word" in rule and "anywhere" not in rule


def test_scroll_boxes_have_names_of_their_own_and_stop_being_tab_stops_when_they_fit() -> None:
    """#89: several boxes on a page all called "Table, scrolls sideways..." cannot be told apart,
    and each was a tab stop whether or not its table overflowed."""
    for template in TEMPLATES:
        text = template.read_text(encoding="utf-8")
        labels = re.findall(r'class="table-scroll" role="region" aria-label="([^"]+)"', text)
        assert all(not label.startswith("Table,") for label in labels), template.name
        assert len(set(labels)) == len(labels), f"{template.name}: {labels}"
    script = (WEB / "static" / "keyboard.js").read_text(encoding="utf-8")
    assert "box.scrollWidth > box.clientWidth" in script
    assert 'box.removeAttribute("tabindex")' in script and "ResizeObserver" in script


@pytest.mark.parametrize(
    "name", ["records.html", "history.html", "adjudicate.html", "extract_index.html", "prisma.html"]
)
def test_the_tables_read_on_a_phone_stack_into_labelled_cards(name: str) -> None:
    text = next(t for t in TEMPLATES if t.name == name).read_text(encoding="utf-8")
    assert "stack-table" in text and "table-scroll" not in text
    body = text[text.index("<tbody") :]
    assert "<td>" not in body.replace('<td colspan="3">', ""), "every cell needs a data-label"
