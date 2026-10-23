"""The PRISMA 2020 checklist, with each item auto-filled, auto-located, or left to the author.

Implements openspec:prisma-reporting#the-checklist. An item is **auto-filled** when the repository
holds the answer and this module writes it out, **auto-located** when the repository holds the
material and the item says where, and **author** when only the author can supply it (a rationale, a
judgement, the discussion, certainty of evidence). Items 22 (certainty) and 23 (discussion) are
author work in v1 by design.

`WORDING_VERIFIED` is True: the item wording below was compared, item by item, with Table 1 of the PRISMA
2020 statement (Page et al., BMJ 2021;372:n71, CC BY 4.0), and tests/fixtures/prisma2020/checklist.json
(parsed from that article) pins it. The wording is the article's word for word, including its British
spelling and the cross-references in items 2 and 16a to the article's own table 2 and figure 1.
"""

# ruff: noqa: E501  (the checklist wording and generated sentences are single long strings)
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from strata.report import amendments as amendments_mod
from strata.report.facts import AnalysisFacts, Facts

WORDING_VERIFIED = True
AUTO_FILLED, AUTO_LOCATED, AUTHOR = "auto-filled", "auto-located", "author"
ATTRIBUTION = (
    "PRISMA 2020 checklist: Page MJ, McKenzie JE, Bossuyt PM, et al. The PRISMA 2020 statement: an "
    "updated guideline for reporting systematic reviews. BMJ 2021;372:n71. "
    "https://doi.org/10.1136/bmj.n71 (CC BY 4.0, https://creativecommons.org/licenses/by/4.0/)."
)

# (item, section, topic, wording)
ITEMS: list[tuple[str, str, str, str]] = [
    ("1", "Title", "Title", "Identify the report as a systematic review."),
    ("2", "Abstract", "Abstract", "See the PRISMA 2020 for Abstracts checklist (table 2)."),
    ("3", "Introduction", "Rationale", "Describe the rationale for the review in the context of existing knowledge."),
    ("4", "Introduction", "Objectives", "Provide an explicit statement of the objective(s) or question(s) the review addresses."),
    ("5", "Methods", "Eligibility criteria", "Specify the inclusion and exclusion criteria for the review and how studies were grouped for the syntheses."),
    ("6", "Methods", "Information sources", "Specify all databases, registers, websites, organisations, reference lists and other sources searched or consulted to identify studies. Specify the date when each source was last searched or consulted."),
    ("7", "Methods", "Search strategy", "Present the full search strategies for all databases, registers and websites, including any filters and limits used."),
    ("8", "Methods", "Selection process", "Specify the methods used to decide whether a study met the inclusion criteria of the review, including how many reviewers screened each record and each report retrieved, whether they worked independently, and if applicable, details of automation tools used in the process."),
    ("9", "Methods", "Data collection process", "Specify the methods used to collect data from reports, including how many reviewers collected data from each report, whether they worked independently, any processes for obtaining or confirming data from study investigators, and if applicable, details of automation tools used in the process."),
    ("10a", "Methods", "Data items", "List and define all outcomes for which data were sought. Specify whether all results that were compatible with each outcome domain in each study were sought (e.g. for all measures, time points, analyses), and if not, the methods used to decide which results to collect."),
    ("10b", "Methods", "Data items", "List and define all other variables for which data were sought (e.g. participant and intervention characteristics, funding sources). Describe any assumptions made about any missing or unclear information."),
    ("11", "Methods", "Study risk of bias assessment", "Specify the methods used to assess risk of bias in the included studies, including details of the tool(s) used, how many reviewers assessed each study and whether they worked independently, and if applicable, details of automation tools used in the process."),
    ("12", "Methods", "Effect measures", "Specify for each outcome the effect measure(s) (e.g. risk ratio, mean difference) used in the synthesis or presentation of results."),
    ("13a", "Methods", "Synthesis methods", "Describe the processes used to decide which studies were eligible for each synthesis (e.g. tabulating the study intervention characteristics and comparing against the planned groups for each synthesis (item #5))."),
    ("13b", "Methods", "Synthesis methods", "Describe any methods required to prepare the data for presentation or synthesis, such as handling of missing summary statistics, or data conversions."),
    ("13c", "Methods", "Synthesis methods", "Describe any methods used to tabulate or visually display results of individual studies and syntheses."),
    ("13d", "Methods", "Synthesis methods", "Describe any methods used to synthesise results and provide a rationale for the choice(s). If meta-analysis was performed, describe the model(s), method(s) to identify the presence and extent of statistical heterogeneity, and software package(s) used."),
    ("13e", "Methods", "Synthesis methods", "Describe any methods used to explore possible causes of heterogeneity among study results (e.g. subgroup analysis, meta-regression)."),
    ("13f", "Methods", "Synthesis methods", "Describe any sensitivity analyses conducted to assess robustness of the synthesised results."),
    ("14", "Methods", "Reporting bias assessment", "Describe any methods used to assess risk of bias due to missing results in a synthesis (arising from reporting biases)."),
    ("15", "Methods", "Certainty assessment", "Describe any methods used to assess certainty (or confidence) in the body of evidence for an outcome."),
    ("16a", "Results", "Study selection", "Describe the results of the search and selection process, from the number of records identified in the search to the number of studies included in the review, ideally using a flow diagram (see fig 1)."),
    ("16b", "Results", "Study selection", "Cite studies that might appear to meet the inclusion criteria, but which were excluded, and explain why they were excluded."),
    ("17", "Results", "Study characteristics", "Cite each included study and present its characteristics."),
    ("18", "Results", "Risk of bias in studies", "Present assessments of risk of bias for each included study."),
    ("19", "Results", "Results of individual studies", "For all outcomes, present, for each study: (a) summary statistics for each group (where appropriate) and (b) an effect estimate and its precision (e.g. confidence/credible interval), ideally using structured tables or plots."),
    ("20a", "Results", "Results of syntheses", "For each synthesis, briefly summarise the characteristics and risk of bias among contributing studies."),
    ("20b", "Results", "Results of syntheses", "Present results of all statistical syntheses conducted. If meta-analysis was done, present for each the summary estimate and its precision (e.g. confidence/credible interval) and measures of statistical heterogeneity. If comparing groups, describe the direction of the effect."),
    ("20c", "Results", "Results of syntheses", "Present results of all investigations of possible causes of heterogeneity among study results."),
    ("20d", "Results", "Results of syntheses", "Present results of all sensitivity analyses conducted to assess the robustness of the synthesised results."),
    ("21", "Results", "Reporting biases", "Present assessments of risk of bias due to missing results (arising from reporting biases) for each synthesis assessed."),
    ("22", "Results", "Certainty of evidence", "Present assessments of certainty (or confidence) in the body of evidence for each outcome assessed."),
    ("23a", "Discussion", "Discussion", "Provide a general interpretation of the results in the context of other evidence."),
    ("23b", "Discussion", "Discussion", "Discuss any limitations of the evidence included in the review."),
    ("23c", "Discussion", "Discussion", "Discuss any limitations of the review processes used."),
    ("23d", "Discussion", "Discussion", "Discuss implications of the results for practice, policy, and future research."),
    ("24a", "Other information", "Registration and protocol", "Provide registration information for the review, including register name and registration number, or state that the review was not registered."),
    ("24b", "Other information", "Registration and protocol", "Indicate where the review protocol can be accessed, or state that a protocol was not prepared."),
    ("24c", "Other information", "Registration and protocol", "Describe and explain any amendments to information provided at registration or in the protocol."),
    ("25", "Other information", "Support", "Describe sources of financial or non-financial support for the review, and the role of the funders or sponsors in the review."),
    ("26", "Other information", "Competing interests", "Declare any competing interests of review authors."),
    ("27", "Other information", "Availability of data, code, and other materials", "Report which of the following are publicly available and where they can be found: template data collection forms; data extracted from included studies; data used for all analyses; analytic code; any other materials used in the review."),
]  # fmt: skip


@dataclass
class Item:
    id: str
    section: str
    topic: str
    wording: str
    status: str = AUTHOR
    source: str = ""
    content: str = ""
    note: str = ""


_Filled = tuple[str, str, str]  # status, source, content


# --- helpers --------------------------------------------------------------------------------


def _bullets(lines: list[str]) -> str:
    return "\n".join(f"- {line}" for line in lines)


def _names(actors: list[str]) -> str:
    return ", ".join(actors) if actors else "(none recorded)"


def _analyses_with(facts: Facts, key: str) -> list[AnalysisFacts]:
    return [a for a in facts.analyses if a.spec.section(key)]


def _no_analysis(note: str) -> _Filled:
    return AUTHOR, "analysis/*.yaml", note


# --- items ----------------------------------------------------------------------------------


def _eligibility(facts: Facts) -> _Filled:
    if not facts.criteria:
        return AUTHOR, "protocol/criteria.yaml", "No criteria are recorded yet."
    lines = []
    for kind in ("inclusion", "exclusion"):
        for c in facts.criteria:
            if c["kind"] == kind and c["status"] == "active":
                stages = ", ".join(c["applies_at"])
                lines.append(
                    f"{kind.capitalize()} {c['id']} ({c['label']}): {c['definition']} [applies at: {stages}]"
                )
    grouping = [
        f"analysis `{a.id}`: "
        + (
            a.spec.section("include").get("filter")
            or "every included study reporting the effect measure"
        )
        for a in facts.analyses
    ]
    text = f"Criteria version {facts.criteria_version}.\n\n" + _bullets(lines)
    if grouping:
        text += "\n\nStudies were grouped for synthesis as follows:\n\n" + _bullets(grouping)
    return AUTO_FILLED, "protocol/criteria.yaml, analysis/*.yaml", text


def _information_sources(facts: Facts) -> _Filled:
    lines = [
        f"{s['database']} ({s['platform']}), last searched {s['executed']} (search {s['id']})"
        + (f", superseding {s['supersedes']}" if s.get("supersedes") else "")
        for s in facts.searches
    ]
    ids = {s["id"]: s for s in facts.searches}
    for source_id, newer in {
        s.get("supersedes"): s for s in facts.searches if s.get("supersedes")
    }.items():
        if source_id in ids:
            lines.append(
                f"(search {source_id} was repeated as {newer['id']} on {newer['executed']})"
            )
    for m in facts.other_imports:
        lines.append(f"{m['via']}: {m.get('rows_read', 0)} record(s), imported {m['imported']}")
    if not lines:
        return AUTHOR, "protocol/searches/*.yaml", "No searches are recorded yet."
    return AUTO_FILLED, "protocol/searches/*.yaml, imports/", _bullets(lines)


def _search_strategy(facts: Facts) -> _Filled:
    if not facts.searches:
        return AUTHOR, "protocol/searches/*.yaml", "No searches are recorded yet."
    blocks = []
    for s in facts.searches:
        limits = s.get("limits") or {}
        shown = "; ".join(f"{k}: {v}" for k, v in limits.items() if v) or "none recorded"
        blocks.append(
            f"#### {s['database']} ({s['platform']}), {s['executed']}, search {s['id']}\n\n```\n{s['query']}\n```\n\nLimits and filters: {shown}."
        )
    return AUTO_FILLED, "protocol/searches/*.yaml (verbatim)", "\n\n".join(blocks)


def _selection(facts: Facts) -> _Filled:
    s = facts.screening
    mode = s.get("mode", "single")
    reviewers = facts.reviewers("lead", "screener")
    parts = [
        f"Screening stages: {', '.join(facts.stages)}. Mode: {mode}. Reviewers: {_names(reviewers)}."
    ]
    if mode == "single":
        parts.append("Each record was screened by one reviewer.")
    else:
        independently = (
            "independently" if s.get("blind_reviewers", True) else "not blinded to each other"
        )
        parts.append(
            f"Each record and each report was screened by two reviewers, working {independently}."
        )
        if s.get("adjudicators"):
            parts.append(
                f"Disagreements were resolved by adjudication ({_names(list(s['adjudicators']))})."
            )
    for stage, pairs in facts.irr.items():
        for p in pairs:
            parts.append(
                f"Agreement at {stage} between {p.actor_a} and {p.actor_b} (n = {p.n}): {p.raw_agreement:.0%}, Cohen's kappa {p.kappa:.2f}."
            )
    auto = facts.counts.totals
    parts.append(
        "Duplicates were found and merged with strata's deduplication (blocking and scoring; "
        f"{auto.duplicates_removed} duplicate record(s) removed). No records were marked ineligible by "
        "automation tools and no machine-learning prioritisation was used."
    )
    return (
        AUTO_FILLED,
        "strata.toml [screening], events/screen, derived/irr.json",
        "\n\n".join(parts),
    )


def _collection(facts: Facts) -> _Filled:
    if facts.extraction_schema is None:
        return AUTHOR, "extraction/schema.yaml", "No extraction form is recorded yet."
    extractors = facts.reviewers("lead", "extractor")
    text = (
        f"Data were extracted with a versioned coding form (version {facts.extraction_schema.version}) in which every "
        "value carries a source locator. "
    )
    if facts.extraction_mode == "dual":
        rate = facts.agreement or {}
        text += (
            f"Two reviewers ({_names(extractors)}) extracted each study independently and a reconciler settled "
            f"every difference with a recorded rationale; before reconciliation they agreed on {rate.get('agreed', 0)} "
            f"of {rate.get('compared', 0)} compared item(s) ({float(rate.get('rate', 1.0)):.0%})."
        )
    else:
        text += f"One reviewer ({_names(extractors)}) extracted each study."
    return (
        AUTO_FILLED,
        "extraction/schema.yaml, extraction/consensus/, events/reconcile",
        text
        + (
            "\n\nProcesses for obtaining or confirming data from study investigators are not recorded in the repository: the author should describe them."
        ),
    )


def _outcomes(facts: Facts) -> _Filled:
    schema = facts.extraction_schema
    if schema is None or not schema.outcomes:
        return AUTHOR, "extraction/schema.yaml", "No outcomes are declared in the coding form."
    return (
        AUTO_FILLED,
        "extraction/schema.yaml",
        "Outcomes for which data were sought: "
        + ", ".join(schema.outcomes)
        + ".\n\nThe author should state whether all results compatible with each outcome domain were sought and how results were selected.",
    )


def _variables(facts: Facts) -> _Filled:
    schema = facts.extraction_schema
    if schema is None:
        return AUTHOR, "extraction/schema.yaml", "No extraction form is recorded yet."
    lines = []
    for f in schema.fields:
        unit = f" ({f['unit']})" if f.get("unit") else ""
        lines.append(
            f"{f.get('label') or f['name']} [{f['type']}{unit}]"
            + (" (required)" if f.get("required") else "")
        )
    return AUTO_FILLED, "extraction/schema.yaml", _bullets(lines)


def _risk_of_bias(facts: Facts) -> _Filled:
    if facts.instrument is None:
        return AUTHOR, "rob/instrument.yaml", "No risk-of-bias instrument is recorded yet."
    i = facts.instrument
    text = f"Risk of bias was assessed with {i.name} (version {i.version}); overall judgements follow the `{i.overall_algorithm}` rule. "
    if facts.extraction_mode == "dual":
        text += "Two reviewers assessed each study independently and differences were reconciled with a recorded rationale. "
    else:
        text += "One reviewer assessed each study. "
    text += "Algorithmic suggestions, where the instrument defines them, were shown to the reviewer; every judgement that differs from the suggestion is recorded with its justification."
    return AUTO_FILLED, "rob/instrument.yaml, rob/", text


def _effect_measures(facts: Facts) -> _Filled:
    if not facts.analyses:
        return _no_analysis("No analysis is specified yet.")
    lines = [f"Analysis `{a.id}` ({a.spec.title}): {a.spec.measure}" for a in facts.analyses]
    return AUTO_FILLED, "analysis/*.yaml", _bullets(lines)


def _synthesis_eligibility(facts: Facts) -> _Filled:
    if not facts.analyses:
        return _no_analysis("No analysis is specified yet.")
    lines = []
    for a in facts.analyses:
        include = a.spec.section("include")
        lines.append(
            f"`{a.id}`: stage {include.get('stage', 'last')}; filter {include.get('filter') or 'none (every included study with a computable effect of this measure)'}"
        )
    return AUTO_LOCATED, "analysis/*.yaml (include)", _bullets(lines)


def _preparation(facts: Facts) -> _Filled:
    schema = facts.extraction_schema
    if schema is None:
        return AUTHOR, "extraction/", "No extraction form is recorded yet."
    text = (
        "Effect sizes were computed from the reported statistics by strata's native effect-size module, which follows "
        "`metafor::escalc()` conventions (Hedges' g with the exact small-sample correction; a continuity correction of 0.5 "
        "added to every cell of a 2x2 table with a zero; studies with no events in both arms excluded from ratio analyses). "
        "Quantities were converted to the units declared in the coding form, with the entered value and unit kept."
    )
    return AUTO_FILLED, "extraction/schema.yaml, analysis/*.yaml", text


def _display(facts: Facts) -> _Filled:
    plotted = [a for a in facts.analyses if a.spec.section("plots")]
    if not plotted:
        return AUTHOR, "analysis/*.yaml (plots)", "No plots are specified in any analysis."
    lines = [
        f"`{a.id}`: "
        + ", ".join(a.spec.section("plots"))
        + f" (values in analysis/results/{a.id}/studies.tsv)"
        for a in plotted
    ]
    return AUTO_LOCATED, "analysis/results/<id>/plots/, studies.tsv", _bullets(lines)


def _model_text(a: AnalysisFacts) -> str:
    model, dep = a.spec.section("model"), a.spec.section("dependency")
    text = f"`{a.id}`: {model['type']} model"
    if model["type"] == "random-effects":
        text += f", tau^2 estimated by {model['tau2_estimator']}, {model['ci_method']} intervals"
    handling = dep.get("handling", "none")
    if handling != "none":
        text += f"; dependent effects handled by {handling}" + (
            f" (assumed within-study correlation {dep['rho']})"
            if dep.get("rho") is not None
            else ""
        )
    return text


def _synthesis(facts: Facts) -> _Filled:
    if not facts.analyses:
        return _no_analysis("No analysis is specified yet.")
    lines = [_model_text(a) for a in facts.analyses]
    text = _bullets(lines) + (
        f"\n\nHeterogeneity was assessed with Q, the Q-based I^2 and tau^2 (with a Q-profile interval) and prediction intervals "
        f"(t distribution on k - 2 degrees of freedom). Analyses were run with strata {facts.version}'s native engine, which is validated "
        "against `metafor` and `clubSandwich` to a relative tolerance of 1e-8."
    )
    return AUTO_FILLED, "analysis/*.yaml, analysis/results/<id>/run.json", text


def _heterogeneity(facts: Facts) -> _Filled:
    moderated = _analyses_with(facts, "moderators")
    if not moderated:
        return (
            AUTHOR,
            "analysis/*.yaml (moderators)",
            "No analysis specifies moderators; describe any exploration of heterogeneity.",
        )
    lines = [
        f"`{a.id}`: meta-regression on "
        + ", ".join(m["name"] for m in a.spec.section("moderators"))
        for a in moderated
    ]
    return AUTO_FILLED, "analysis/*.yaml (moderators)", _bullets(lines)


def _sensitivity(facts: Facts) -> _Filled:
    sensitive = _analyses_with(facts, "sensitivity")
    if not sensitive:
        return (
            AUTHOR,
            "analysis/*.yaml (sensitivity)",
            "No sensitivity analysis is specified; describe any that were done.",
        )
    lines = [
        f"`{a.id}`: "
        + ", ".join(
            f"{s['id']} ({s['type'].replace('_', ' ')})" for s in a.spec.section("sensitivity")
        )
        for a in sensitive
    ]
    return AUTO_FILLED, "analysis/*.yaml (sensitivity)", _bullets(lines)


def _reporting_bias(facts: Facts) -> _Filled:
    biased = _analyses_with(facts, "publication_bias")
    if not biased:
        return (
            AUTHOR,
            "analysis/*.yaml (publication_bias)",
            "No small-study analysis is specified; describe how reporting bias was assessed.",
        )
    lines = [f"`{a.id}`: " + ", ".join(a.spec.section("publication_bias")) for a in biased]
    return (
        AUTO_FILLED,
        "analysis/*.yaml (publication_bias)",
        _bullets(lines)
        + "\n\nThese are sensitivity analyses; none corrects for publication bias, and they are blocked below ten studies unless forced.",
    )


def _selection_results(facts: Facts) -> _Filled:
    t, c = facts.counts.totals, facts.counts
    text = (
        f"{t.identified} record(s) were identified; {t.removed_before_screening} were removed before screening "
        f"({t.duplicates_removed} duplicates); {t.records_screened} were screened and {t.records_excluded_tiab} excluded; "
        f"{t.reports_sought} report(s) were sought and {t.reports_not_retrieved} could not be retrieved; {t.reports_assessed} were "
        f"assessed for eligibility and {t.reports_excluded_ft} excluded; {c.studies_included} study(ies) in {t.reports_included} "
        f"report(s) were included."
    )
    if not c.complete:
        text += " Screening is not finished, so these counts will change."
    return AUTO_FILLED, "derived/counts.json, reports/prisma.svg (strata prisma)", text


def _excluded(facts: Facts) -> _Filled:
    reasons = facts.counts.exclusion_reasons
    if not reasons:
        return AUTO_LOCATED, "derived/counts.json", "No report was excluded at full text."
    lines = [f"{r.label}: {r.count}" for r in reasons]
    return (
        AUTO_FILLED,
        "derived/counts.json; strata export bibliography --set excluded-at-fulltext",
        _bullets(lines)
        + "\n\nThe excluded reports can be listed with `strata export bibliography --set excluded-at-fulltext`.",
    )


def _characteristics(facts: Facts) -> _Filled:
    if facts.counts.studies_included == 0:
        return AUTHOR, "strata report characteristics", "No study is included yet."
    return (
        AUTO_LOCATED,
        "strata report characteristics",
        "The characteristics table is generated by `strata report characteristics` (one row per included study).",
    )


def _rob_results(facts: Facts) -> _Filled:
    if facts.instrument is None:
        return AUTHOR, "rob/", "No risk-of-bias assessment is recorded."
    return (
        AUTO_LOCATED,
        "strata report rob",
        "Per-study judgements are in `strata report rob` and the `rob/consensus/` files.",
    )


def _individual(facts: Facts) -> _Filled:
    done = [a for a in facts.analyses if a.estimates]
    if not done:
        return _no_analysis("No analysis has been run yet.")
    return (
        AUTO_LOCATED,
        "analysis/results/<id>/studies.tsv, plots/",
        _bullets([f"`{a.id}`: studies.tsv and plots under analysis/results/{a.id}/" for a in done]),
    )


def _pooled_line(a: AnalysisFacts) -> str:
    e = a.estimates or {}
    first = e["pooled"]["coefficients"][0]
    return (
        f"`{a.id}`: {e['k_studies']} studies, pooled {e['measure']} {first['estimate']:.2f} "
        f"(95% CI {first['ci_lb']:.2f} to {first['ci_ub']:.2f})"
    )


def _syntheses(facts: Facts) -> _Filled:
    done = [a for a in facts.analyses if a.estimates]
    if not done:
        return _no_analysis("No analysis has been run yet.")
    return (
        AUTO_FILLED,
        "analysis/results/<id>/estimates.json, summary.md",
        _bullets([_pooled_line(a) for a in done])
        + "\n\nThe full sentences, with heterogeneity, are in `strata report results`.",
    )


def _located(key: str, what: str):  # type: ignore[no-untyped-def]
    def fill(facts: Facts) -> _Filled:
        done = [a for a in facts.analyses if a.estimates and a.spec.section(key)]
        if not done:
            return AUTHOR, f"analysis/*.yaml ({key})", f"No analysis with {what} has been run."
        return (
            AUTO_LOCATED,
            f"analysis/results/<id>/estimates.json ({what})",
            _bullets([f"`{a.id}`" for a in done]),
        )

    return fill


def _registration(facts: Facts) -> _Filled:
    registry = facts.project.get("registry") or {}
    if not registry:
        return (
            AUTHOR,
            "strata.toml [project.registry]",
            "No registration is recorded: give the register name and number, or state that the review was not registered.",
        )
    text = ", ".join(f"{k}: {v}" for k, v in registry.items())
    return AUTO_FILLED, "strata.toml [project.registry]", text


def _protocol_location(facts: Facts) -> _Filled:
    where = facts.remote or "this repository"
    return (
        AUTO_LOCATED,
        "protocol/, git history",
        f"The protocol (criteria, searches, forms) is under `protocol/` and `extraction/` in {where}; its history, including every amendment, is in git.",
    )


def _amendments(facts: Facts) -> _Filled:
    return (
        AUTO_FILLED,
        "criteria-change events, commit trailers",
        amendments_mod.text(facts.repo).rstrip(),
    )


def _support(facts: Facts) -> _Filled:
    funding = facts.project.get("funding") or {}
    sources = funding.get("sources") or []
    if not sources:
        return (
            AUTHOR,
            "strata.toml [project.funding]",
            "No funding is recorded: describe the sources of support (or state that there was none) and the role of the funders.",
        )
    text = "Sources of support: " + "; ".join(sources) + "."
    if funding.get("role_of_funders"):
        text += f" Role of the funders: {funding['role_of_funders']}"
    return AUTO_FILLED, "strata.toml [project.funding]", text


def _competing(facts: Facts) -> _Filled:
    ci = facts.project.get("competing_interests") or {}
    if not ci.get("statement") and not ci.get("declarations"):
        return (
            AUTHOR,
            "strata.toml [project.competing_interests]",
            "No declaration is recorded: declare any competing interests of the review authors.",
        )
    parts = [ci["statement"]] if ci.get("statement") else []
    parts += [f"{d['author']}: {d['statement']}" for d in ci.get("declarations", [])]
    return AUTO_FILLED, "strata.toml [project.competing_interests]", "\n\n".join(parts)


def _availability(facts: Facts) -> _Filled:
    where = facts.remote or "(no remote is configured)"
    commit = facts.commit or "(uncommitted)"
    text = (
        f"Repository: {where}, commit `{commit}`. It holds the data collection form (`extraction/schema.yaml`), the extracted data "
        "(`extraction/consensus/`), the data used for each analysis (`analysis/results/<id>/studies.tsv`) and the analysis "
        "specifications and results; `strata export package` bundles them without any full text."
    )
    return AUTO_LOCATED, "git repository, strata export package", text


_FILL: dict[str, Any] = {
    "5": _eligibility, "6": _information_sources, "7": _search_strategy, "8": _selection,
    "9": _collection, "10a": _outcomes, "10b": _variables, "11": _risk_of_bias,
    "12": _effect_measures, "13a": _synthesis_eligibility, "13b": _preparation, "13c": _display,
    "13d": _synthesis, "13e": _heterogeneity, "13f": _sensitivity, "14": _reporting_bias,
    "16a": _selection_results, "16b": _excluded, "17": _characteristics, "18": _rob_results,
    "19": _individual, "20a": _syntheses, "20b": _syntheses,
    "20c": _located("moderators", "meta-regression results"),
    "20d": _located("sensitivity", "sensitivity results"),
    "21": _located("publication_bias", "small-study results"),
    "24a": _registration, "24b": _protocol_location, "24c": _amendments, "25": _support,
    "26": _competing, "27": _availability,
}  # fmt: skip

_AUTHOR_NOTES = {
    "1": "Name the report a systematic review (and meta-analysis).",
    "2": "Write the abstract against the PRISMA 2020 for Abstracts checklist.",
    "3": "Describe the rationale: strata does not draft introductions.",
    "4": "State the objectives or questions.",
    "15": "Certainty of evidence (for example GRADE) is not assessed by strata.",
    "22": "Certainty of evidence is flagged as author work: strata does not assess it.",
    "23a": "strata does not generate a discussion: it is an argument, and that is the author's.",
    "23b": "Limitations of the evidence: author work.",
    "23c": "Limitations of the review processes: author work.",
    "23d": "Implications: author work.",
}
# Items 20a (summarise characteristics and risk of bias) and 20b share the synthesis summary.


def build(facts: Facts) -> list[Item]:
    items = []
    for item_id, section, topic, wording in ITEMS:
        item = Item(item_id, section, topic, wording)
        fill = _FILL.get(item_id)
        if fill is not None:
            item.status, item.source, item.content = fill(facts)
        else:
            item.note = _AUTHOR_NOTES.get(item_id, "")
        found = _AUTHOR_NOTES.get(item_id)
        if item.status == AUTHOR and found and not item.note:
            item.note = found
        items.append(item)
    return items


def status(items: list[Item]) -> dict[str, Any]:
    by_status = {
        s: [i.id for i in items if i.status == s] for s in (AUTO_FILLED, AUTO_LOCATED, AUTHOR)
    }
    return {
        "items": len(items),
        "auto_filled": len(by_status[AUTO_FILLED]),
        "auto_located": len(by_status[AUTO_LOCATED]),
        "author": len(by_status[AUTHOR]),
        "needs_author": by_status[AUTHOR],
    }


def _cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def render(facts: Facts) -> str:
    items = build(facts)
    summary = status(items)
    commit = (
        f"{facts.commit[:10]} plus uncommitted changes"
        if facts.commit and facts.dirty
        else (facts.commit or "uncommitted state")
    )
    lines = [
        "# PRISMA 2020 checklist",
        "",
        f"*Generated by strata {facts.version} from {commit}.* Items marked **auto-filled** are written below from the "
        "repository; **auto-located** items name where the material is; **author** items are yours to write. "
        "Fill in the last column with the section or page of your manuscript.",
        "",
        f"> {ATTRIBUTION}",
    ]
    if WORDING_VERIFIED:
        lines += [
            "",
            "> The item wording is Table 1 of the statement, word for word; 'table 2' in item 2 and 'fig 1' in item "
            "16a are the article's own abstract checklist and flow diagram.",
        ]
    else:
        lines += [
            "",
            "> **Not yet verified:** the item wording above has not been compared with the official PRISMA 2020 "
            "template. Check it at https://www.prisma-statement.org/ before you submit; the official wording governs.",
        ]
    lines += [
        "",
        f"**Status:** {summary['auto_filled']} auto-filled, {summary['auto_located']} auto-located, "
        f"{summary['author']} for the author (of {summary['items']} items and sub-items).",
        "",
        "| Item | Section / topic | Checklist item | Status | Repository source | Location where item is reported |",
        "|---|---|---|---|---|---|",
    ]
    for it in items:
        lines.append(
            f"| {it.id} | {_cell(it.section + ' / ' + it.topic)} | {_cell(it.wording)} | {it.status} | {_cell(it.source or '')} |  |"
        )
    lines += ["", "## Auto-filled and auto-located content", ""]
    for it in items:
        if it.content:
            lines += [
                f"### Item {it.id} \u2014 {it.topic} ({it.status})",
                "",
                it.content.rstrip(),
                "",
            ]
    lines += ["## Left to the author", ""]
    lines += [
        f"- **{it.id}** {it.topic}" + (f": {it.note}" if it.note else "")
        for it in items
        if it.status == AUTHOR
    ]
    return "\n".join(lines).rstrip() + "\n"
