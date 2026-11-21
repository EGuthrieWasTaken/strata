"""Build the BCG worked-example review from its published data, through the command line.

    uv run python examples/bcg-vaccine/build.py <empty directory>

The review: the 13 trials of BCG vaccine against tuberculosis that Colditz et al. (1994) pooled
and Viechtbauer (2010) reanalysed with `metafor` (`dat.bcg`). Two reviewers screen every report
in at both stages, every report is retrieved, one reviewer extracts each trial's 2x2 table, the
absolute latitude of the trial site and the method of allocation, and two analyses run: the
random-effects model of the log risk ratio, and the meta-regression on latitude. The generated
results are what `tests/e2e/test_worked_example_bcg.py` compares with the published values and
with `results/` here.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from typer.testing import CliRunner

from strata import gitio
from strata.cli.main import app
from strata.core import records as records_mod
from strata.core.canon import dump_yaml_str
from strata.core.ids import record_id_for_report
from strata.core.repo import open_repo
from strata.protocol import studies as studies_mod

HERE = Path(__file__).resolve().parent
WHY = "Building the BCG worked example from the published trial data."
runner = CliRunner()


def run(root: Path | None, *args: str, input: str | None = None) -> str:  # noqa: A002
    prefix = ["--why", WHY, *(["-C", str(root)] if root else [])]
    result = runner.invoke(app, [*prefix, *args], input=input)
    if result.exit_code != 0:
        raise SystemExit(f"strata {' '.join(args)} failed ({result.exit_code}):\n{result.output}")
    return result.output


def records(trials: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Citation records. `dat.bcg` gives each trial's first author and year only, so the title
    names the trial rather than quoting a paper's title, and there is no DOI to give."""
    out = []
    for trial in trials:
        family = trial["author"].replace(" et al.", "").split(" & ")
        out.append(
            {
                "id": str(trial["trial"]),
                "type": "article-journal",
                "title": f"BCG vaccination against tuberculosis: trial {trial['trial']} of the "
                f"Colditz et al. (1994) meta-analysis, {trial['author']} ({trial['year']})",
                "author": [{"family": f} for f in family],
                "issued": {"date-parts": [[trial["year"]]]},
                "abstract": "A controlled trial of BCG vaccine for the prevention of tuberculosis.",
            }
        )
    return out


def build(root: Path) -> None:
    trials = json.loads((HERE / "trials.json").read_text(encoding="utf-8"))
    run(None, "init", str(root), "--title", "BCG vaccine and tuberculosis (worked example)",
        "--actor", "ethan", "--actor-name", "Ethan")  # fmt: skip
    run(root, "actor", "add", "sam", "Sam")
    run(root, "criteria", "add", "--kind", "inclusion", "--label", "Controlled trial of BCG",
        "--definition", "A trial comparing BCG vaccination with no vaccination, reporting cases "
        "of tuberculosis in each group.", "--applies-at", "title-abstract",
        "--applies-at", "full-text", "--by", "ethan", "--id", "INC-01")  # fmt: skip
    export = root.parent / "bcg-trials.json"
    export.write_text(json.dumps(records(trials), indent=2), encoding="utf-8")
    run(root, "import", str(export), "--by", "ethan", "--via", "citation-searching")

    for stage in ("title-abstract", "full-text"):
        for handle in ("ethan", "sam"):
            run(root, "screen", stage, "--by", handle, input="i\n\n" * len(trials))

    root.joinpath("protocol", "moderators.yaml").write_text(
        dump_yaml_str({"moderators": [
            {"name": "ablat", "label": "Absolute latitude of the trial site", "type": "continuous"},
            {"name": "alloc", "label": "Method of allocation", "type": "categorical",
             "levels": ["random", "alternate", "systematic"]},
        ]}),
        encoding="utf-8",
    )  # fmt: skip
    root.joinpath("protocol", "outcomes.yaml").write_text(
        dump_yaml_str({"outcomes": [{"name": "tuberculosis"}]}), encoding="utf-8"
    )
    gitio.add_all(root)
    gitio.commit(root, "protocol: the moderators and the outcome\n\nStrata-Op: protocol\n"
                 "Strata-Actor: ethan\n")  # fmt: skip
    run(root, "extract", "init", "--by", "ethan")

    # Each trial is one report and so one study; it is found by the trial number in its title.
    repo = open_repo(root)
    number_of = {
        str(r["id"]): int(r["title"].split(": trial ")[1].split(" ")[0])
        for r in records_mod.read_records(repo)
    }
    study_of = {
        number_of[record_id_for_report(reports[0])]: study
        for study, reports in studies_mod.study_map(repo).members.items()
    }
    for trial in trials:
        study = study_of[trial["trial"]]
        effect = {
            "outcome": "tuberculosis", "design": "two-group-binary", "measure": "logRR",
            "events1": trial["tpos"], "n1": trial["tpos"] + trial["tneg"],
            "events2": trial["cpos"], "n2": trial["cpos"] + trial["cneg"],
            "source": "Colditz et al. (1994), Table 1",
        }  # fmt: skip
        run(root, "extract", study, "--by", "ethan",
            "--set", f"n_total={trial['tpos'] + trial['tneg'] + trial['cpos'] + trial['cneg']}",
            "--set", f"ablat={trial['ablat']}", "--set", f"alloc={trial['alloc']}",
            "--effect", json.dumps(effect))  # fmt: skip

    root.joinpath("analysis").mkdir(exist_ok=True)
    common = {
        "preregistered": True,
        "effect_size": {"measure": "logRR"},
        "plots": ["forest"],
        "model": {"type": "random-effects", "tau2_estimator": "REML", "ci_method": "wald"},
    }
    root.joinpath("analysis", "primary.yaml").write_text(
        dump_yaml_str({"id": "primary", "title": "BCG vaccine and tuberculosis", **common}),
        encoding="utf-8",
    )
    root.joinpath("analysis", "latitude.yaml").write_text(
        dump_yaml_str({"id": "latitude", "title": "BCG vaccine efficacy and latitude", **common,
                       "plots": ["bubble"],
                       "moderators": [{"name": "ablat", "type": "continuous",
                                       "centering": "none"}]}),
        encoding="utf-8",
    )  # fmt: skip
    run(root, "analyze", "primary")
    run(root, "analyze", "latitude")
    run(root, "prisma")
    for section in ("methods", "results"):
        run(root, "report", section)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    target = Path(sys.argv[1]).resolve()
    if target.exists() and any(target.iterdir()):
        raise SystemExit(f"{target} is not empty")
    build(target / "review")
    print(f"built {target / 'review'}")
