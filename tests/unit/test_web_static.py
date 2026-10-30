"""The web interface's shipped JavaScript: openspec:web-ui#technology and
#drag-and-drop-is-an-enhancement (OpenSpec change `add-web-ui-write-surfaces`, task 4.6).

The Python suite cannot run a browser, so what it can pin is the script's contract: it is small, it
makes no request and reads no file, and no page *needs* it (each form works as a plain form post,
which every other test in the suite exercises without any script at all).
"""

import re
from importlib.resources import files
from pathlib import Path

import pytest

STATIC = Path(str(files("strata.web") / "static"))
TEMPLATES = Path(str(files("strata.web") / "templates"))
BUDGET_BYTES = 50 * 1024


def _scripts() -> list[Path]:
    return sorted(STATIC.glob("*.js"))


def test_all_the_shipped_javascript_stays_under_the_budget() -> None:
    total = sum(path.stat().st_size for path in _scripts())

    assert total < BUDGET_BYTES, f"{total} bytes of JavaScript; the budget is {BUDGET_BYTES}"
    assert {p.name for p in _scripts()} >= {"keyboard.js", "dropzone.js"}


@pytest.mark.parametrize(
    "forbidden",
    [
        r"\bfetch\s*\(",
        r"XMLHttpRequest",
        r"\bWebSocket\b",
        r"sendBeacon",
        r"\beval\s*\(",
        r"new Function",
        r"\.innerHTML",
        r"\.outerHTML",
        r"insertAdjacentHTML",
        r"document\.write",
        r"https?://",
        r"FileReader",
        r"\.submit\s*\(",
        r"requestSubmit",
    ],
)
def test_the_drop_script_makes_no_request_reads_no_file_and_submits_nothing(
    forbidden: str,
) -> None:
    source = (STATIC / "dropzone.js").read_text(encoding="utf-8")

    assert re.search(forbidden, source) is None


def test_the_drop_script_does_not_touch_the_session_token() -> None:
    source = (STATIC / "dropzone.js").read_text(encoding="utf-8").lower()

    assert "csrf" not in source and "token" not in source and "cookie" not in source


def _pages_with_a_file_chooser() -> list[str]:
    return sorted(
        path.name
        for path in TEMPLATES.glob("*.html")
        if 'type="file"' in path.read_text(encoding="utf-8")
        or "file_picker(" in path.read_text(encoding="utf-8")
    )


def test_the_chooser_is_a_real_file_input_that_works_without_the_script() -> None:
    macro = (TEMPLATES / "_forms.html").read_text(encoding="utf-8")

    assert '<input type="file"' in macro and "multiple" in macro
    # The convenience text about dropping is hidden until the script runs.
    assert 'class="dropzone-js-only" hidden' in macro


def test_exactly_the_pages_with_a_chooser_load_the_script() -> None:
    pages = _pages_with_a_file_chooser()
    assert pages  # a chooser exists

    for name in pages:
        if name == "_forms.html":
            continue
        text = (TEMPLATES / name).read_text(encoding="utf-8")
        assert "/static/dropzone.js" in text, f"{name} has a file chooser but loads no script"
    for path in TEMPLATES.glob("*.html"):
        if path.name in pages or path.name == "base.html":
            continue
        assert "dropzone.js" not in path.read_text(encoding="utf-8"), path.name


def test_every_form_with_a_chooser_posts_as_multipart() -> None:
    for name in _pages_with_a_file_chooser():
        if name == "_forms.html":
            continue
        text = (TEMPLATES / name).read_text(encoding="utf-8")
        for form in re.findall(r"<form[^>]*>.*?</form>", text, flags=re.S):
            if "file_picker(" in form or 'type="file"' in form:
                assert 'enctype="multipart/form-data"' in form, f"{name}: {form[:80]}"
