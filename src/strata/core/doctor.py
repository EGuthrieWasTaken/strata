"""`strata doctor`: diagnose and repair a repository's git-level setup.

Implements openspec:git-integration#merge-drivers ("`strata doctor` MUST detect
missing drivers and offer to install them") and openspec:git-integration#versioned-hooks (hooks).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from strata import gitio
from strata.core.hooks import HOOK_SCRIPTS, HOOKS_DIR
from strata.core.init import MERGE_DRIVERS
from strata.core.repo import Repo

MIN_GIT_VERSION = (2, 30)


@dataclass
class DoctorFinding:
    ok: bool
    message: str
    fixed: bool = False


@dataclass
class DoctorReport:
    findings: list[DoctorFinding] = field(default_factory=list)

    @property
    def healthy(self) -> bool:
        return all(f.ok or f.fixed for f in self.findings)


def _git_version(repo: Repo) -> tuple[int, int] | None:
    result = gitio.run(["--version"], cwd=repo.root, check=False)
    if result.returncode != 0:
        return None
    parts = result.stdout.strip().split()
    if len(parts) < 3:
        return None
    try:
        major, minor, *_ = parts[2].split(".")
        return (int(major), int(minor))
    except ValueError:
        return None


def run_doctor(repo: Repo, *, fix: bool = False) -> DoctorReport:
    report = DoctorReport()

    version = _git_version(repo)
    if version is None:
        report.findings.append(DoctorFinding(ok=False, message="could not determine git version"))
    elif version < MIN_GIT_VERSION:
        report.findings.append(
            DoctorFinding(
                ok=False,
                message=f"git {version} is older than the minimum supported {MIN_GIT_VERSION}",
            )
        )
    else:
        report.findings.append(DoctorFinding(ok=True, message=f"git {version[0]}.{version[1]} ok"))

    hooks_path = gitio.get_config(repo.root, "core.hooksPath")
    if hooks_path != HOOKS_DIR:
        if fix:
            gitio.set_config(repo.root, "core.hooksPath", HOOKS_DIR)
            report.findings.append(
                DoctorFinding(ok=False, fixed=True, message=f"set core.hooksPath = {HOOKS_DIR}")
            )
        else:
            report.findings.append(
                DoctorFinding(ok=False, message=f"core.hooksPath is not set to {HOOKS_DIR}")
            )
    else:
        report.findings.append(DoctorFinding(ok=True, message="core.hooksPath ok"))

    for name, script in HOOK_SCRIPTS.items():
        hook_path = repo.path(*HOOKS_DIR.split("/"), name)
        if not hook_path.exists():
            if fix:
                hook_path.parent.mkdir(parents=True, exist_ok=True)
                hook_path.write_text(script, encoding="utf-8")
                hook_path.chmod(0o755)
                report.findings.append(
                    DoctorFinding(ok=False, fixed=True, message=f"installed missing hook {name}")
                )
            else:
                report.findings.append(DoctorFinding(ok=False, message=f"hook {name} is missing"))
        else:
            report.findings.append(DoctorFinding(ok=True, message=f"hook {name} ok"))

    for driver_name, cfg in MERGE_DRIVERS.items():
        configured = gitio.get_config(repo.root, f"merge.{driver_name}.driver")
        if configured != cfg["driver"]:
            if fix:
                gitio.set_config(repo.root, f"merge.{driver_name}.name", cfg["name"])
                gitio.set_config(repo.root, f"merge.{driver_name}.driver", cfg["driver"])
                report.findings.append(
                    DoctorFinding(
                        ok=False, fixed=True, message=f"installed merge driver {driver_name}"
                    )
                )
            else:
                report.findings.append(
                    DoctorFinding(ok=False, message=f"merge driver {driver_name} is not installed")
                )
        else:
            report.findings.append(DoctorFinding(ok=True, message=f"merge driver {driver_name} ok"))

    repo_size = sum(f.stat().st_size for f in repo.root.rglob("*") if f.is_file())
    if repo_size > 500 * 1024 * 1024:
        report.findings.append(
            DoctorFinding(
                ok=False,
                message=f"repository is {repo_size / (1024 * 1024):.0f} MB; consider `git gc`",
            )
        )

    return report
