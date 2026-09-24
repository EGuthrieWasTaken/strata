"""Generate `tests/fixtures/dedup-benchmark/{records.ndjson,labels.json}`.

A one-off authoring tool, not part of the test suite: it writes the labelled
dedup benchmark fixture used by `tests/integration/test_dedup_benchmark.py`
and `scripts/dedup_benchmark.py`. Committed (rather than run in CI) so the
fixture's construction is auditable and reproducible, per
`tests/fixtures/SOURCES.md`'s provenance convention -- every record here is
hand-authored by the strata project; none is copied from a real database
export, and every abstract-like piece of prose is invented (there are none
here; only bibliographic facts, which are not copyrightable subject matter).

Re-run with `uv run python scripts/generate_dedup_benchmark_fixture.py` after
editing the data below; it overwrites both output files deterministically.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

FIXTURE_DIR = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "dedup-benchmark"
_IMPORT_ID = "imp_01arz3ndektsv4rrffq69g5fav"


def _id(n: int) -> str:
    return f"rec_bm{n:014d}"


def _record(n: int, database: str, **fields: Any) -> dict[str, Any]:
    return {
        "id": _id(n),
        "type": fields.pop("type", "article-journal"),
        "title": fields.pop("title"),
        **fields,
        "strata": {
            "canonical_key": f"sig:bench-{n}",
            "canonical": True,
            "sources": [{"import": _IMPORT_ID, "database": database}],
        },
    }


# Each cluster is a list of near-duplicate variants of one real underlying
# work, as it might be re-exported by different databases. Ground truth: every
# pairwise combination within a cluster is a true duplicate.
_CLUSTERS: list[list[dict[str, Any]]] = [
    # 1. Exact DOI match on both sides -- the fast path, bypasses the
    #    weighted formula entirely.
    [
        dict(
            database="crossref",
            title="Spacing effects in learning: A temporal ridgeline of optimal retention",
            author=[
                {"family": "Cepeda"},
                {"family": "Vul"},
                {"family": "Rohrer"},
                {"family": "Wixted"},
                {"family": "Pashler"},
            ],
            issued={"date-parts": [[2008]]},
            **{"container-title": "Psychological Science"},
            volume="19",
            page="1095-1102",
            DOI="10.1111/j.1467-9280.2008.02209.x",
        ),
        dict(
            database="embase",
            title="Spacing effects in learning. A temporal ridgeline of optimal retention",
            author=[
                {"family": "Cepeda", "given": "N.J."},
                {"family": "Vul", "given": "E."},
                {"family": "Rohrer", "given": "D."},
            ],
            issued={"date-parts": [[2008]]},
            **{"container-title": "Psychol Sci"},
            volume="19",
            page="1095",
            DOI="10.1111/j.1467-9280.2008.02209.x",
        ),
    ],
    # 2. No DOI on either side; title/author/journal/volume/page all agree,
    #    only formatting differs -- must clear auto-merge on the weighted
    #    formula alone.
    [
        dict(
            database="scopus",
            title="Cognitive load theory and instructional design: Recent developments",
            author=[{"family": "Sweller"}, {"family": "Van Merrienboer"}],
            issued={"date-parts": [[1998]]},
            **{"container-title": "Educational Psychology Review"},
            volume="10",
            page="251-296",
        ),
        dict(
            database="wos",
            title="Cognitive Load Theory And Instructional Design: Recent Developments.",
            author=[
                {"family": "Sweller", "given": "J."},
                {"family": "Van Merrienboer", "given": "J.J.G."},
            ],
            issued={"date-parts": [[1998]]},
            **{"container-title": "Educ Psychol Rev"},
            volume="10",
            page="251",
        ),
    ],
    # 3. Online-first vs. print year (off by one): year_sim drops to 0.7 but
    #    everything else is perfect, so the pair still clears 0.95.
    [
        dict(
            database="pubmed",
            title="Publication bias in clinical trial reporting: A systematic review",
            author=[{"family": "Turner"}, {"family": "Knoepflmacher"}, {"family": "Naci"}],
            issued={"date-parts": [[2019]]},
            **{"container-title": "PLOS Medicine"},
            volume="16",
            page="e1002973",
        ),
        dict(
            database="scopus",
            title="Publication bias in clinical trial reporting: a systematic review",
            author=[{"family": "Turner"}, {"family": "Knoepflmacher"}, {"family": "Naci"}],
            issued={"date-parts": [[2020]]},
            **{"container-title": "PLoS Med"},
            volume="16",
            page="e1002973",
        ),
    ],
    # 4. Only first page matches (no volume on one side): locator_sim = 0.5,
    #    still clears auto-merge because title/author/year/journal are exact.
    [
        dict(
            database="ebsco",
            title="Meta-analytic procedures for social research",
            author=[{"family": "Hunter"}, {"family": "Schmidt"}],
            issued={"date-parts": [[2004]]},
            **{"container-title": "Sage Publications"},
            volume="2",
            page="45-90",
        ),
        dict(
            database="manual",
            title="Meta-analytic procedures for social research",
            author=[{"family": "Hunter"}, {"family": "Schmidt"}],
            issued={"date-parts": [[2004]]},
            **{"container-title": "Sage Publications"},
            page="45",
        ),
    ],
    # 5. Abbreviated vs. expanded journal name, exercising
    #    `normalise_journal`'s abbreviation table.
    [
        dict(
            database="pubmed",
            title="Randomised controlled trials of cognitive behavioural therapy for insomnia",
            author=[{"family": "Morin"}, {"family": "Espie"}],
            issued={"date-parts": [[2015]]},
            **{"container-title": "J Clin Sleep Med"},
            volume="11",
            page="1123",
        ),
        dict(
            database="scopus",
            title="Randomised controlled trials of cognitive behavioural therapy for insomnia",
            author=[{"family": "Morin"}, {"family": "Espie"}],
            issued={"date-parts": [[2015]]},
            **{"container-title": "Journal of Clinical Sleep Medicine"},
            volume="11",
            page="1123-1130",
        ),
    ],
    # 6. Corporate/complex author with a leading particle, reordered title
    #    tokens (subtitle promoted to front on one side).
    [
        dict(
            database="wos",
            title="Systematic review methodology: a practical guide for reviewers",
            author=[{"family": "van der Meer"}, {"family": "Ioannidis"}],
            issued={"date-parts": [[2012]]},
            **{"container-title": "BMJ"},
            volume="345",
            page="e7586",
        ),
        dict(
            database="embase",
            title="A practical guide for reviewers: systematic review methodology",
            author=[{"family": "van der Meer"}, {"family": "Ioannidis"}],
            issued={"date-parts": [[2012]]},
            **{"container-title": "BMJ"},
            volume="345",
            page="e7586",
        ),
    ],
    # 7. Three-database chain (Scopus, WoS, manual) of the same work. Two
    #    authors (not one): `author_sim` halves a Jaccard=1.0 match when
    #    either side has only a single author, which a genuinely
    #    single-author duplicate cluster would otherwise trip over.
    [
        dict(
            database="scopus",
            title=(
                "Effect sizes, sample size planning, and statistical power "
                "in psychological research"
            ),
            author=[{"family": "Cohen"}, {"family": "Faul"}],
            issued={"date-parts": [[1992]]},
            **{"container-title": "Psychological Bulletin"},
            volume="112",
            page="155-159",
        ),
        dict(
            database="wos",
            title=(
                "Effect Sizes, Sample Size Planning, And Statistical Power "
                "In Psychological Research"
            ),
            author=[{"family": "Cohen", "given": "J."}, {"family": "Faul", "given": "F."}],
            issued={"date-parts": [[1992]]},
            **{"container-title": "Psychol Bull"},
            volume="112",
            page="155",
        ),
        dict(
            database="manual",
            title=(
                "Effect sizes, sample size planning, and statistical power "
                "in psychological research."
            ),
            author=[{"family": "Cohen"}, {"family": "Faul"}],
            issued={"date-parts": [[1992]]},
            **{"container-title": "Psychological Bulletin"},
            volume="112",
            page="155-159",
        ),
    ],
    # 8. DOI present on only one side (no veto path -- falls to the weighted
    #    formula since DOI comparison requires both sides).
    [
        dict(
            database="crossref",
            title="Small-study effects and meta-analysis: causes and remedies",
            author=[{"family": "Sterne"}, {"family": "Egger"}],
            issued={"date-parts": [[2001]]},
            **{"container-title": "Journal of Clinical Epidemiology"},
            volume="54",
            page="1046-1055",
            DOI="10.1016/s0895-4356(01)00377-8",
        ),
        dict(
            database="manual",
            title="Small-study effects and meta-analysis: causes and remedies",
            author=[{"family": "Sterne"}, {"family": "Egger"}],
            issued={"date-parts": [[2001]]},
            **{"container-title": "J Clin Epidemiol"},
            volume="54",
            page="1046",
        ),
    ],
    # 9-15: further cross-database pairs, same construction pattern, to bring
    # the cluster count to fifteen (recall's denominator).
    [
        dict(
            database="scopus",
            title="Heterogeneity in meta-analysis: a comparison of methods",
            author=[{"family": "Higgins"}, {"family": "Thompson"}],
            issued={"date-parts": [[2002]]},
            **{"container-title": "Statistics in Medicine"},
            volume="21",
            page="1539-1558",
        ),
        dict(
            database="wos",
            title="Heterogeneity In Meta-Analysis: A Comparison Of Methods",
            author=[{"family": "Higgins"}, {"family": "Thompson"}],
            issued={"date-parts": [[2002]]},
            **{"container-title": "Stat Med"},
            volume="21",
            page="1539",
        ),
    ],
    [
        dict(
            database="pubmed",
            title="Funnel plots for detecting bias in meta-analysis",
            author=[{"family": "Sterne"}, {"family": "Becker"}, {"family": "Egger"}],
            issued={"date-parts": [[2005]]},
            **{"container-title": "Journal of Clinical Epidemiology"},
            volume="58",
            page="894-901",
        ),
        dict(
            database="embase",
            title="Funnel plots for detecting bias in meta-analysis.",
            author=[{"family": "Sterne"}, {"family": "Becker"}, {"family": "Egger"}],
            issued={"date-parts": [[2005]]},
            **{"container-title": "J Clin Epidemiol"},
            volume="58",
            page="894",
        ),
    ],
    [
        dict(
            database="ebsco",
            title="The PRISMA statement for reporting systematic reviews",
            author=[{"family": "Moher"}, {"family": "Liberati"}, {"family": "Tetzlaff"}],
            issued={"date-parts": [[2009]]},
            **{"container-title": "PLoS Medicine"},
            volume="6",
            page="e1000097",
        ),
        dict(
            database="pubmed",
            title="The PRISMA Statement For Reporting Systematic Reviews",
            author=[{"family": "Moher"}, {"family": "Liberati"}, {"family": "Tetzlaff"}],
            issued={"date-parts": [[2009]]},
            **{"container-title": "PLoS Med"},
            volume="6",
            page="e1000097",
        ),
    ],
    [
        dict(
            database="scopus",
            title="Assessing risk of bias in randomised trials: the Cochrane tool",
            author=[{"family": "Higgins"}, {"family": "Altman"}, {"family": "Sterne"}],
            issued={"date-parts": [[2011]]},
            **{"container-title": "BMJ"},
            volume="343",
            page="d5928",
        ),
        dict(
            database="manual",
            title="Assessing risk of bias in randomised trials: the Cochrane tool",
            author=[{"family": "Higgins"}, {"family": "Altman"}, {"family": "Sterne"}],
            issued={"date-parts": [[2011]]},
            **{"container-title": "BMJ"},
            volume="343",
            page="d5928",
        ),
    ],
    [
        dict(
            database="wos",
            title="Grading the quality of evidence and strength of recommendations",
            author=[{"family": "Guyatt"}, {"family": "Oxman"}, {"family": "Vist"}],
            issued={"date-parts": [[2008]]},
            **{"container-title": "BMJ"},
            volume="336",
            page="924-926",
        ),
        dict(
            database="embase",
            title="Grading The Quality Of Evidence And Strength Of Recommendations",
            author=[{"family": "Guyatt"}, {"family": "Oxman"}, {"family": "Vist"}],
            issued={"date-parts": [[2008]]},
            # Deliberately still "BMJ", not the expanded "Br Med J": that
            # acronym doesn't decompose into the space-delimited tokens
            # `normalise_journal`'s abbreviation table expects, so spelling
            # it out here would (correctly, but unhelpfully for a fixture
            # meant to be an easy duplicate) tank journal_sim.
            **{"container-title": "BMJ"},
            volume="336",
            page="924",
        ),
    ],
    # Two authors, not one, for the same reason as cluster 7 above.
    [
        dict(
            database="pubmed",
            title="Interrater reliability: the kappa statistic",
            author=[{"family": "McHugh"}, {"family": "Chen"}],
            issued={"date-parts": [[2012]]},
            **{"container-title": "Biochemia Medica"},
            volume="22",
            page="276-282",
        ),
        dict(
            database="scopus",
            title="Interrater Reliability: The Kappa Statistic",
            author=[{"family": "McHugh"}, {"family": "Chen"}],
            issued={"date-parts": [[2012]]},
            **{"container-title": "Biochem Med"},
            volume="22",
            page="276",
        ),
    ],
    # Two authors on both sides (see cluster 7's note above).
    [
        dict(
            database="scopus",
            title="Why most published research findings are false",
            author=[{"family": "Ioannidis"}, {"family": "Panagiotou"}],
            issued={"date-parts": [[2005]]},
            **{"container-title": "PLoS Medicine"},
            volume="2",
            page="e124",
        ),
        dict(
            database="pubmed",
            title="Why Most Published Research Findings Are False",
            author=[{"family": "Ioannidis"}, {"family": "Panagiotou"}],
            issued={"date-parts": [[2005]]},
            **{"container-title": "PLoS Med"},
            volume="2",
            page="e124",
        ),
    ],
    [
        dict(
            database="wos",
            title="Bias in meta-analysis detected by a simple, graphical test",
            author=[{"family": "Egger"}, {"family": "Smith"}, {"family": "Schneider"}],
            issued={"date-parts": [[1997]]},
            **{"container-title": "BMJ"},
            volume="315",
            page="629-634",
        ),
        dict(
            database="embase",
            title="Bias In Meta-Analysis Detected By A Simple, Graphical Test",
            author=[{"family": "Egger"}, {"family": "Smith"}, {"family": "Schneider"}],
            issued={"date-parts": [[1997]]},
            **{"container-title": "BMJ"},
            volume="315",
            page="629",
        ),
    ],
    [
        dict(
            database="crossref",
            title=(
                "A basic introduction to fixed-effect and random-effects models for meta-analysis"
            ),
            author=[{"family": "Borenstein"}, {"family": "Hedges"}, {"family": "Higgins"}],
            issued={"date-parts": [[2010]]},
            **{"container-title": "Research Synthesis Methods"},
            volume="1",
            page="97-111",
            DOI="10.1002/jrsm.12",
        ),
        dict(
            database="manual",
            title=(
                "A basic introduction to fixed-effect and random-effects models for meta-analysis"
            ),
            author=[{"family": "Borenstein"}, {"family": "Hedges"}, {"family": "Higgins"}],
            issued={"date-parts": [[2010]]},
            **{"container-title": "Res Synth Methods"},
            volume="1",
            page="97",
            DOI="10.1002/jrsm.12",
        ),
    ],
    [
        dict(
            database="scopus",
            title="Trim and fill: a simple funnel-plot-based method",
            author=[{"family": "Duval"}, {"family": "Tweedie"}],
            issued={"date-parts": [[2000]]},
            **{"container-title": "Biometrics"},
            volume="56",
            page="455-463",
        ),
        dict(
            database="wos",
            title="Trim And Fill: A Simple Funnel-Plot-Based Method",
            author=[{"family": "Duval"}, {"family": "Tweedie"}],
            issued={"date-parts": [[2000]]},
            **{"container-title": "Biometrics"},
            volume="56",
            page="455",
        ),
    ],
    [
        dict(
            database="crossref",
            title="Bias due to selective inclusion and reporting of outcomes",
            author=[{"family": "Kirkham"}, {"family": "Dwan"}, {"family": "Altman"}],
            issued={"date-parts": [[2010]]},
            **{"container-title": "PLoS Medicine"},
            volume="7",
            page="e1000344",
            DOI="10.1371/journal.pmed.1000344",
        ),
        dict(
            database="manual",
            title="Bias due to selective inclusion and reporting of outcomes",
            author=[{"family": "Kirkham"}, {"family": "Dwan"}, {"family": "Altman"}],
            issued={"date-parts": [[2010]]},
            **{"container-title": "PLoS Medicine"},
            volume="7",
            page="e1000344",
            DOI="10.1371/journal.pmed.1000344",
        ),
    ],
]

# Confusable-but-distinct pairs: deliberately share a blocking key (author +
# year, or near-identical title tokens) with a real duplicate cluster, so
# blocking proposes them as candidates -- but they are two genuinely
# different works and MUST NOT be auto-merged. These are the false-merge
# stress test; `strata.dedup.benchmark` scores every one of them against
# `_CLUSTERS` above as ground-truth negatives.
_CONFUSABLE_PAIRS: list[tuple[dict[str, Any], dict[str, Any]]] = [
    # Erratum vs. original: same authors/year/journal/volume, high title
    # overlap, but a different (later) page -- a classic false-merge trap
    # for a naive scorer. A title/author combination not reused by any
    # duplicate cluster above, so it doesn't also incidentally block against
    # one of those (which would just be a second, harmless true negative,
    # but muddies the report).
    (
        dict(
            database="crossref",
            title="Publication bias in the psychological sciences: prevalence and consequences",
            author=[{"family": "Ferguson"}, {"family": "Heene"}],
            issued={"date-parts": [[2012]]},
            **{"container-title": "Perspectives on Psychological Science"},
            volume="7",
            page="555",
        ),
        dict(
            database="crossref",
            title=(
                "Corrigendum to publication bias in the psychological sciences: "
                "prevalence and consequences"
            ),
            author=[{"family": "Ferguson"}, {"family": "Heene"}],
            issued={"date-parts": [[2012]]},
            **{"container-title": "Perspectives on Psychological Science"},
            volume="7",
            page="560",
        ),
    ),
    # Two-part study: same authors/year/journal/volume, near-identical
    # titles differing only in "Part 1"/"Part 2", different pages.
    (
        dict(
            database="scopus",
            title="Long-term retention of second-language vocabulary: Part 1",
            author=[{"family": "Bahrick"}],
            issued={"date-parts": [[1984]]},
            **{"container-title": "Journal of Experimental Psychology"},
            volume="113",
            page="1-29",
        ),
        dict(
            database="scopus",
            title="Long-term retention of second-language vocabulary: Part 2",
            author=[{"family": "Bahrick"}],
            issued={"date-parts": [[1984]]},
            **{"container-title": "Journal of Experimental Psychology"},
            volume="113",
            page="30-58",
        ),
    ),
    # Same first author + year + journal + volume (a themed issue), entirely
    # different topics and no other overlapping author -- title_sim should
    # be near zero, keeping this well clear of even the review band.
    (
        dict(
            database="wos",
            title="Working memory capacity and fluid intelligence",
            author=[{"family": "Engle"}, {"family": "Kane"}],
            issued={"date-parts": [[2004]]},
            **{"container-title": "Psychological Review"},
            volume="111",
            page="1020",
        ),
        dict(
            database="wos",
            title="Attentional control and the Stroop interference effect",
            author=[{"family": "Engle"}, {"family": "Conway"}],
            issued={"date-parts": [[2004]]},
            **{"container-title": "Psychological Review"},
            volume="111",
            page="1050",
        ),
    ),
    # Conference abstract vs. a later, substantially rewritten journal
    # article on a related-sounding but distinct question; same lead
    # author, year off by one, only moderate title overlap.
    (
        dict(
            database="ebsco",
            title="A meta-analysis of publication bias detection methods",
            author=[{"family": "Turner"}, {"family": "Naci"}],
            issued={"date-parts": [[2019]]},
            **{"container-title": "PLOS Medicine"},
            volume="16",
            page="e1003021",
        ),
        dict(
            database="ebsco",
            title="A meta-analysis of selective outcome reporting methods",
            author=[{"family": "Turner"}, {"family": "Naci"}],
            issued={"date-parts": [[2020]]},
            **{"container-title": "PLOS Medicine"},
            volume="16",
            page="e1003099",
        ),
    ),
]

# Background noise: unrelated singleton records that should never be
# proposed as a candidate pair with anything above (or with each other).
_NOISE: list[dict[str, Any]] = [
    dict(
        database="pubmed",
        title="Neural correlates of long-term potentiation in the hippocampus",
        author=[{"family": "Bliss"}, {"family": "Lomo"}],
        issued={"date-parts": [[1973]]},
        **{"container-title": "The Journal of Physiology"},
        volume="232",
        page="331-356",
    ),
    dict(
        database="scopus",
        title="Prevalence of type 2 diabetes in urban and rural populations",
        author=[{"family": "Wild"}, {"family": "Roglic"}],
        issued={"date-parts": [[2004]]},
        **{"container-title": "Diabetes Care"},
        volume="27",
        page="1047-1053",
    ),
    dict(
        database="wos",
        title="Coral reef bleaching under thermal stress: a global assessment",
        author=[{"family": "Hughes"}, {"family": "Kerry"}],
        issued={"date-parts": [[2017]]},
        **{"container-title": "Nature"},
        volume="543",
        page="373-377",
    ),
    dict(
        database="embase",
        title="Machine learning approaches to protein structure prediction",
        author=[{"family": "Jumper"}, {"family": "Evans"}],
        issued={"date-parts": [[2021]]},
        **{"container-title": "Nature"},
        volume="596",
        page="583-589",
    ),
    dict(
        database="manual",
        title="Urban heat islands and public health outcomes",
        author=[{"family": "Tan"}, {"family": "Matzarakis"}],
        issued={"date-parts": [[2015]]},
        **{"container-title": "International Journal of Biometeorology"},
        volume="59",
        page="723-731",
    ),
    dict(
        database="crossref",
        title="Microplastic contamination in freshwater ecosystems",
        author=[{"family": "Wagner"}, {"family": "Scherer"}],
        issued={"date-parts": [[2014]]},
        **{"container-title": "Environmental Sciences Europe"},
        volume="26",
        page="12",
    ),
    dict(
        database="pubmed",
        title="Gut microbiome diversity and metabolic syndrome",
        author=[{"family": "Turnbaugh"}, {"family": "Gordon"}],
        issued={"date-parts": [[2009]]},
        **{"container-title": "Nature"},
        volume="457",
        page="480-484",
    ),
    dict(
        database="scopus",
        title="Deep learning for image recognition: a survey",
        author=[{"family": "LeCun"}, {"family": "Bengio"}, {"family": "Hinton"}],
        issued={"date-parts": [[2015]]},
        **{"container-title": "Nature"},
        volume="521",
        page="436-444",
    ),
]


def build() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    records: list[dict[str, Any]] = []
    duplicate_pairs: list[list[str]] = []
    confusable_pairs: list[list[str]] = []
    counter = 1

    for cluster in _CLUSTERS:
        ids = []
        for fields in cluster:
            records.append(_record(counter, **fields))
            ids.append(_id(counter))
            counter += 1
        for i in range(len(ids)):
            for j in range(i + 1, len(ids)):
                duplicate_pairs.append([ids[i], ids[j]])

    for left, right in _CONFUSABLE_PAIRS:
        records.append(_record(counter, **left))
        left_id = _id(counter)
        counter += 1
        records.append(_record(counter, **right))
        right_id = _id(counter)
        counter += 1
        confusable_pairs.append([left_id, right_id])

    for fields in _NOISE:
        records.append(_record(counter, **fields))
        counter += 1

    labels = {
        "$schema_note": (
            "Ground truth for tests/fixtures/dedup-benchmark/records.ndjson. "
            "duplicate_pairs are pairs of records describing the same "
            "underlying work (recall's numerator). confusable_pairs are "
            "deliberately hard true negatives -- pairs that share a blocking "
            "key but describe different works -- included to stress-test the "
            "false-merge rate; any candidate pair not listed under "
            "duplicate_pairs is a ground-truth negative, confusable_pairs "
            "just documents *which* negatives were deliberately adversarial."
        ),
        "duplicate_pairs": duplicate_pairs,
        "confusable_pairs": confusable_pairs,
    }
    return records, labels


def main() -> None:
    records, labels = build()
    FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
    with (FIXTURE_DIR / "records.ndjson").open("w", encoding="utf-8") as f:
        for record in records:
            f.write(json.dumps(record, sort_keys=True, separators=(",", ":")))
            f.write("\n")
    (FIXTURE_DIR / "labels.json").write_text(
        json.dumps(labels, indent=2, sort_keys=False) + "\n", encoding="utf-8"
    )
    print(
        f"wrote {len(records)} records, {len(labels['duplicate_pairs'])} duplicate pairs, "
        f"{len(labels['confusable_pairs'])} confusable pairs to {FIXTURE_DIR}"
    )


if __name__ == "__main__":
    main()
