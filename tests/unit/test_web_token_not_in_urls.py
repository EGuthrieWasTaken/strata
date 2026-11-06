"""The session token must never be able to reach an address (openspec:web-ui#localhost-security).

The same per-process token is the session cookie and the CSRF field in every form. A form that is
submitted with GET puts all its fields in the URL, so a token in such a form lands in browser
history, the address bar, `Referer` headers and any proxy log, which defeats the cookie being
`HttpOnly`. The criteria editor's Preview button once did exactly that (`formmethod="get"` inside
the form that carries the token).
"""

import re
from pathlib import Path

TEMPLATES = sorted(
    (Path(__file__).resolve().parents[2] / "src/strata/web/templates").glob("*.html")
)
FORM = re.compile(r"<form\b(?P<attrs>[^>]*)>(?P<body>.*?)</form>", re.S)
TOKEN = re.compile(r"csrf_field_name|csrf_token|session_token")


def test_no_form_that_carries_the_session_token_can_be_submitted_with_get() -> None:
    offenders = []
    for template in TEMPLATES:
        for form in FORM.finditer(template.read_text(encoding="utf-8")):
            if not TOKEN.search(form["body"]):
                continue
            method = re.search(r"""\bmethod=["'](\w+)["']""", form["attrs"])
            if method is None or method[1].lower() != "post":
                offenders.append(f"{template.name}: a form with the token is not method=post")
            if re.search(r"""formmethod=["']get["']""", form["body"], re.I):
                offenders.append(f"{template.name}: a control inside it submits with GET")
    assert offenders == []


def test_the_guard_looks_at_the_forms_that_exist() -> None:
    carrying = [
        t.name
        for t in TEMPLATES
        if any(TOKEN.search(f["body"]) for f in FORM.finditer(t.read_text()))
    ]
    assert "criteria_edit.html" in carrying and len(carrying) >= 5
