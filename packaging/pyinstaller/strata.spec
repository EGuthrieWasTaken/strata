# PyInstaller build of a standalone `strata` (openspec:project-documentation, add-distribution-and-adoption
# task 1.2). Built by `.github/workflows/release.yml` on each platform:
#
#   uv run --with pyinstaller==6.16.0 pyinstaller --noconfirm --clean packaging/pyinstaller/strata.spec
#
# One file, so a person downloads one thing. Everything `strata` reads at run time that is not Python
# (the JSON schemas, the web UI's templates and static files, the MCP server's package metadata) is
# collected with the package.
# ruff: noqa
from PyInstaller.utils.hooks import collect_all, collect_submodules, copy_metadata

datas, binaries, hiddenimports = [], [], []
for package in ("strata", "argon2", "mcp", "uvicorn", "jinja2"):
    pkg_datas, pkg_binaries, pkg_hidden = collect_all(package)
    datas += pkg_datas
    binaries += pkg_binaries
    hiddenimports += pkg_hidden
# SciPy imports its vendored array-API layer by name at run time (`__import__(__package__ + ".fft")`),
# which the analysis cannot follow.
hiddenimports += collect_submodules("scipy._external")
for distribution in ("strata-review", "mcp"):
    datas += copy_metadata(distribution)

a = Analysis(
    ["strata_entry.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["tkinter", "pytest", "hypothesis", "mypy"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="strata",
    console=True,
    strip=False,
    upx=False,
)
