"""The PRISMA 2020 flow diagram (new reviews), drawn on the deterministic canvas.

Implements openspec:prisma-reporting#flow-diagram. The box labels follow the template published
with the PRISMA 2020 statement (Page et al., BMJ 2021;372:n71) as reproduced in the `PRISMA2020` R
package's data template; they are reproduced here under CC BY 4.0. Like the analysis plots, the
output is byte-identical for the same counts: no timestamps, content-derived ids, one number
formatter.

`columns="one"` draws a single flow. `columns="both"` draws the databases-and-registers flow on the
left and the other-methods flow (records imported with `--via`) on the right, each with its own
screening, retrieval and eligibility boxes, and one included box beneath both.
"""

from __future__ import annotations

import re
import textwrap
from dataclasses import dataclass
from typing import Any

from strata.analysis.plots import PlotError
from strata.analysis.plots import render as render_canvas
from strata.report.counts import SEARCHES, Counts, Funnel, Reason
from strata.stats import canvas as cv

ATTRIBUTION = (
    "Flow diagram layout and wording: PRISMA 2020 (Page MJ et al. BMJ 2021;372:n71), "
    "CC BY 4.0, https://creativecommons.org/licenses/by/4.0/"
)
DRAFT_TEXT = "DRAFT — screening incomplete"
MAX_REASON_LINES = 6
OTHER_REASONS = "Other reasons"

VIA_LABELS = {
    "website": "Websites",
    "organisation": "Organisations",
    "citation-searching": "Citation searching",
    "registry": "Registries",
    "contact": "Contact with experts",
}

COLUMNS = ("one", "both")
FORMATS = ("svg", "pdf", "png", "json")

_FS = 12.0
_LH = 16.0
_PAD = 8.0
_MAIN_W = 250.0
_SIDE_W = 286.0
_GAP_X = 34.0
_GAP_Y = 30.0
_BAND_W = 28.0
_MARGIN = 14.0
_CHAR_W = 5.7  # average Helvetica advance at 12 pt, a little generous so text stays inside


class StaleDecisionsError(ValueError):
    """Decisions are stale, so the diagram is a draft; `--allow-stale` renders it anyway."""


class FlowError(ValueError):
    pass


def require_final(counts: Counts, *, allow_stale: bool) -> None:
    if counts.stale_decisions and not allow_stale:
        raise StaleDecisionsError(
            f"{counts.stale_decisions} decision(s) are stale; re-screen them first or pass "
            "--allow-stale to render a draft"
        )


# --- reasons --------------------------------------------------------------------------------


def collapse_reasons(reasons: list[Reason]) -> tuple[list[Reason], bool]:
    """At most six lines: the five largest reasons and an "Other reasons" line for the rest.

    Reasons with a count of zero never appear. Returns the lines and whether anything collapsed;
    the full table is then emitted alongside (`reasons_table`).
    """
    shown = [r for r in reasons if r.count > 0]
    if len(shown) <= MAX_REASON_LINES:
        return shown, False
    kept, rest = shown[: MAX_REASON_LINES - 1], shown[MAX_REASON_LINES - 1 :]
    return [*kept, Reason("other", OTHER_REASONS, sum(r.count for r in rest))], True


def reasons_table(counts: Counts) -> str:
    """Every full-text exclusion reason with its count, largest first, as TSV."""
    lines = ["id\tlabel\tcount"]
    for reason in counts.exclusion_reasons:
        label = reason.label.replace("\t", " ").replace("\n", " ")
        lines.append(f"{reason.id}\t{label}\t{reason.count}")
    return "\n".join(lines) + "\n"


# --- layout ---------------------------------------------------------------------------------


@dataclass
class _Line:
    text: str
    bold: bool = False
    cls: str = "ink"


_COUNT = re.compile(r"\(n = [^)]*\)")


def _wrap(text: str, width: float) -> list[str]:
    """Wrap to `width`, never splitting inside a "(n = 14)" count."""
    glued = _COUNT.sub(lambda m: m.group(0).replace(" ", "\x00"), text)
    pieces = textwrap.wrap(glued, max(int(width / _CHAR_W), 12)) or [""]
    return [piece.replace("\x00", " ") for piece in pieces]


def _lines(items: list[_Line], width: float) -> list[_Line]:
    wrapped: list[_Line] = []
    for item in items:
        for piece in _wrap(item.text, width - 2 * _PAD):
            wrapped.append(_Line(piece, item.bold, item.cls))
    return wrapped


def _height(items: list[_Line], width: float) -> float:
    return 2 * _PAD + len(_lines(items, width)) * _LH


def _n(label: str, value: int) -> str:
    return f"{label} (n = {value})"


def _identification_lines(counts: Counts, column: str, columns: str, draft: bool) -> list[_Line]:
    box = counts.identification
    other = box["other_methods"]["by_via"]
    out = [_Line("Records identified from:", bold=True)]
    if column == "searches":
        out += [
            _Line(_n("Databases", box["databases"]["total"])),
            _Line(_n("Registers", box["registers"]["total"])),
        ]
        if columns == "one":
            out += [_Line(_n(VIA_LABELS.get(v, v), n)) for v, n in sorted(other.items())]
    else:
        out += [_Line(_n(VIA_LABELS.get(v, v), n)) for v, n in sorted(other.items())]
    return out


def _removed_lines(f: Funnel) -> list[_Line]:
    return [
        _Line("Records removed before screening:", bold=True),
        _Line(_n("Duplicate records removed", f.duplicates_removed)),
        _Line(
            _n(
                "Records marked as ineligible by automation tools",
                f.marked_ineligible_by_automation,
            )
        ),
        _Line(_n("Records removed for other reasons", f.removed_other)),
    ]


def _awaiting(count: int, what: str, draft: bool) -> list[_Line]:
    return [_Line(_n(f"of which awaiting {what}", count), cls="accent2")] if draft and count else []


def _rows(
    counts: Counts, f: Funnel, reasons: list[Reason], column: str, columns: str, draft: bool
) -> list[tuple[list[_Line], list[_Line]]]:
    shown, _ = collapse_reasons(reasons)
    excluded = [_Line("Reports excluded:", bold=True)]
    excluded += [_Line(_n(r.label, r.count)) for r in shown] or [_Line("(none)", cls="muted")]
    return [
        (_identification_lines(counts, column, columns, draft), _removed_lines(f)),
        (
            [
                _Line(_n("Records screened", f.records_screened)),
                *_awaiting(f.awaiting_tiab, "a decision", draft),
            ],
            [_Line(_n("Records excluded", f.records_excluded_tiab))],
        ),  # fmt: skip
        (
            [
                _Line(_n("Reports sought for retrieval", f.reports_sought)),
                *_awaiting(f.awaiting_retrieval, "retrieval", draft),
            ],
            [_Line(_n("Reports not retrieved", f.reports_not_retrieved))],
        ),  # fmt: skip
        (
            [
                _Line(_n("Reports assessed for eligibility", f.reports_assessed)),
                *_awaiting(f.awaiting_ft, "a decision", draft),
            ],
            excluded,
        ),  # fmt: skip
    ]


def _column_funnels(counts: Counts, columns: str) -> list[tuple[str, str, Funnel, list[Reason]]]:
    if columns == "one":
        return [
            (
                SEARCHES,
                "Identification of studies via databases, registers and other methods"
                if counts.other_methods.identified
                else "Identification of studies via databases and registers",
                counts.totals,
                counts.exclusion_reasons,
            )
        ]
    other_reasons: dict[str, int] = {}
    labels: dict[str, str] = {}
    for name, reasons in counts.exclusion_reasons_by_origin.items():
        if name != SEARCHES:
            for r in reasons:
                other_reasons[r.id] = other_reasons.get(r.id, 0) + r.count
                labels[r.id] = r.label
    other = [
        Reason(i, labels[i], c)
        for i, c in sorted(other_reasons.items(), key=lambda kv: (-kv[1], kv[0]))
    ]
    return [
        (
            SEARCHES,
            "Identification of studies via databases and registers",
            counts.by_origin.get(SEARCHES, Funnel()),
            counts.exclusion_reasons_by_origin.get(SEARCHES, []),
        ),
        ("other", "Identification of studies via other methods", counts.other_methods, other),
    ]


def _box(canvas: cv.Canvas, x: float, y: float, w: float, h: float, items: list[_Line]) -> None:
    canvas.add(cv.Rect(x, y, w, h, "surface"), cv.Rect(x, y, w, h, "ink", fill=False))
    for index, line in enumerate(_lines(items, w)):
        canvas.add(
            cv.Text(
                x + _PAD,
                y + _PAD + _FS + index * _LH - 2,
                line.text,
                line.cls,
                size=_FS,
                bold=line.bold,
            )
        )


def _arrow(canvas: cv.Canvas, x1: float, y1: float, x2: float, y2: float) -> None:
    canvas.add(cv.Line(x1, y1, x2, y2, "ink", width=1.2))
    if abs(x2 - x1) > abs(y2 - y1):
        sign = 1 if x2 > x1 else -1
        canvas.add(
            cv.Polygon(((x2, y2), (x2 - sign * 7, y2 - 3.5), (x2 - sign * 7, y2 + 3.5)), "ink")
        )
    else:
        sign = 1 if y2 > y1 else -1
        canvas.add(
            cv.Polygon(((x2, y2), (x2 - 3.5, y2 - sign * 7), (x2 + 3.5, y2 - sign * 7)), "ink")
        )


def _summary(counts: Counts) -> str:
    t = counts.totals
    return (
        f"{t.identified} records identified, {t.duplicates_removed} duplicates removed, "
        f"{t.records_screened} screened, {t.records_excluded_tiab} excluded, "
        f"{t.reports_sought} reports sought, {t.reports_not_retrieved} not retrieved, "
        f"{t.reports_assessed} assessed, {t.reports_excluded_ft} excluded with reasons, "
        f"{counts.studies_included} studies included in {t.reports_included} reports."
    )


def build_canvas(counts: Counts, *, columns: str = "one", draft: bool | None = None) -> cv.Canvas:
    if columns not in COLUMNS:
        raise FlowError(f"--columns must be one of {', '.join(COLUMNS)}, got {columns!r}")
    is_draft = (not counts.complete) if draft is None else draft
    specs = _column_funnels(counts, columns)
    per_column = [
        _rows(counts, funnel, reasons, key, columns, is_draft) for key, _t, funnel, reasons in specs
    ]
    group_w = _MAIN_W + _GAP_X + _SIDE_W
    left = _MARGIN + _BAND_W + _GAP_X / 2
    xs = [left + i * (group_w + _GAP_X) for i in range(len(specs))]
    width = xs[-1] + group_w + _MARGIN
    n_rows = len(per_column[0])

    title_h = 2 * _LH + _GAP_Y / 2
    heights = []
    for r in range(n_rows):
        heights.append(
            max(max(_height(col[r][0], _MAIN_W), _height(col[r][1], _SIDE_W)) for col in per_column)
        )
    included = [
        _Line(_n("Studies included in review", counts.studies_included), bold=True),
        _Line(_n("Reports of included studies", counts.reports_of_included_studies)),
    ]
    included_w = _MAIN_W if len(specs) == 1 else (xs[-1] + _MAIN_W - xs[0])
    included_h = max(_height(included, included_w), 66.0)  # tall enough for the rotated band label
    ys = []
    top = _MARGIN + (20.0 if is_draft else 0.0)  # room for the draft banner
    y = top + title_h
    for h in heights:
        ys.append(y)
        y += h + _GAP_Y
    included_y = y
    height = included_y + included_h + _MARGIN

    canvas = cv.Canvas(width, height, "PRISMA 2020 flow diagram", _summary(counts))
    for (_key, heading, _f, _r), x, rows in zip(specs, xs, per_column, strict=True):
        canvas.add(cv.Text(x, top + _FS + 2, heading, "ink", size=_FS, bold=True))
        for r, (main, side) in enumerate(rows):
            _box(canvas, x, ys[r], _MAIN_W, heights[r], main)
            _box(canvas, x + _MAIN_W + _GAP_X, ys[r], _SIDE_W, heights[r], side)
            _arrow(
                canvas,
                x + _MAIN_W,
                ys[r] + heights[r] / 2,
                x + _MAIN_W + _GAP_X,
                ys[r] + heights[r] / 2,
            )
            if r + 1 < n_rows:
                _arrow(canvas, x + _MAIN_W / 2, ys[r] + heights[r], x + _MAIN_W / 2, ys[r + 1])
        _arrow(canvas, x + _MAIN_W / 2, ys[-1] + heights[-1], x + _MAIN_W / 2, included_y)
    _box(canvas, xs[0], included_y, included_w, included_h, included)
    # Stage bands down the left edge.
    bands = [
        ("Identification", ys[0], ys[0] + heights[0]),
        ("Screening", ys[1], ys[-1] + heights[-1]),
        ("Included", included_y, included_y + included_h),
    ]
    for label, top, bottom in bands:
        canvas.add(cv.Rect(_MARGIN, top, _BAND_W - 4, bottom - top, "band"))
        canvas.add(
            cv.Text(
                _MARGIN + (_BAND_W - 4) / 2 + 4,
                (top + bottom) / 2,
                label,
                "ink",
                anchor="middle",
                size=_FS,
                bold=True,
                rotate=-90,
            )
        )
    if is_draft:
        # Over the boxes, in a light tint, so it cannot be cropped away: a draft stays a draft.
        canvas.add(
            cv.Text(
                width / 2,
                height / 2,
                DRAFT_TEXT,
                "tint3",
                anchor="middle",
                size=26,
                bold=True,
                rotate=-20,
            ),
            cv.Text(
                width / 2,
                _MARGIN + _FS - 2,
                DRAFT_TEXT,
                "accent2",
                anchor="middle",
                size=_FS,
                bold=True,
            ),
        )
    canvas.add(
        cv.Text(
            width / 2,
            height - 3,
            "PRISMA 2020 flow diagram, CC BY 4.0 (Page et al., BMJ 2021;372:n71)",
            "muted",
            anchor="middle",
            size=8,
        )
    )
    return canvas


def render(
    counts: Counts, *, fmt: str = "svg", columns: str = "one", draft: bool | None = None
) -> bytes:
    if fmt not in ("svg", "pdf", "png"):
        raise FlowError(f"format must be one of svg, pdf, png or json, got {fmt!r}")
    try:
        return render_canvas(build_canvas(counts, columns=columns, draft=draft), fmt)
    except PlotError as exc:
        raise FlowError(str(exc)) from None


# --- JSON, including the PRISMA2020 R package's input -------------------------------------------


def _join_pairs(pairs: list[tuple[str, int]]) -> str:
    return "; ".join(f"{label}, {n}" for label, n in pairs)


def prisma2020_rows(
    counts: Counts, search_names: dict[str, str], columns: str
) -> list[dict[str, str]]:
    """Rows in the shape the `PRISMA2020` R package reads (its `data` and `n` columns)."""
    box = counts.identification
    other = box["other_methods"]["by_via"]
    f = counts.totals if columns == "one" else counts.by_origin.get(SEARCHES, Funnel())
    o = counts.other_methods if columns == "both" else Funnel()
    dbr_reasons = (
        counts.exclusion_reasons
        if columns == "one"
        else counts.exclusion_reasons_by_origin.get(SEARCHES, [])
    )
    other_reasons: dict[str, int] = {}
    if columns == "both":
        for name, reasons in counts.exclusion_reasons_by_origin.items():
            if name != SEARCHES:
                for r in reasons:
                    other_reasons[r.label] = other_reasons.get(r.label, 0) + r.count

    def specific(kind: str) -> str:
        pairs = [(search_names.get(i, i), n) for i, n in box[kind]["by_search"].items()]
        return _join_pairs(pairs)

    rows: list[tuple[str, Any]] = [
        ("previous_studies", 0),
        ("previous_reports", 0),
        ("database_results", box["databases"]["total"]),
        ("database_specific_results", specific("databases")),
        ("register_results", box["registers"]["total"]),
        ("register_specific_results", specific("registers")),
        ("website_results", other.get("website", 0)),
        ("organisation_results", other.get("organisation", 0)),
        ("citations_results", other.get("citation-searching", 0)),
        ("duplicates", f.duplicates_removed),
        ("excluded_automatic", f.marked_ineligible_by_automation),
        ("excluded_other", f.removed_other),
        ("records_screened", f.records_screened),
        ("records_excluded", f.records_excluded_tiab),
        ("dbr_sought_reports", f.reports_sought),
        ("dbr_notretrieved_reports", f.reports_not_retrieved),
        ("other_sought_reports", o.reports_sought),
        ("other_notretrieved_reports", o.reports_not_retrieved),
        ("dbr_assessed", f.reports_assessed),
        ("dbr_excluded", _join_pairs([(r.label, r.count) for r in dbr_reasons])),
        ("other_assessed", o.reports_assessed),
        ("other_excluded", _join_pairs(list(other_reasons.items()))),
        ("new_studies", counts.studies_included),
        ("new_reports", counts.reports_of_included_studies),
        ("total_studies", counts.studies_included),
        ("total_reports", counts.reports_of_included_studies),
        ("total_studies_ma", 0),
        ("total_reports_ma", 0),
    ]
    return [{"data": key, "n": str(value)} for key, value in rows]


def flow_json(
    counts: Counts, search_names: dict[str, str], *, columns: str = "one"
) -> dict[str, Any]:
    shown, collapsed = collapse_reasons(counts.exclusion_reasons)
    return {
        "attribution": ATTRIBUTION,
        "columns": columns,
        "draft": not counts.complete,
        "counts": counts.to_dict(),
        "exclusion_reasons_shown": [
            {"id": r.id, "label": r.label, "count": r.count} for r in shown
        ],
        "exclusion_reasons_collapsed": collapsed,
        "prisma2020": prisma2020_rows(counts, search_names, columns),
    }
