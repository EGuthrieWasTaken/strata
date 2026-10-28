# Installation

`strata` is a command-line program with an optional browser interface. It needs **Python 3.11 or newer** and
**git 2.30 or newer**. It runs on Linux, macOS and Windows (CI runs the whole test suite on all three).

> `strata` is not on PyPI, Homebrew or conda-forge yet. Until it is, install it from the repository with
> [`uv`](https://docs.astral.sh/uv/), or run it in a [container](Running-in-a-Container) without installing
> Python at all.

## What you need first

| You need | Check | If it is missing |
|---|---|---|
| git 2.30 or newer | `git --version` | Linux: your package manager. macOS: `xcode-select --install`. Windows: [Git for Windows](https://gitforwindows.org/) |
| `uv` (installs Python for you) | `uv --version` | See the [uv installation guide](https://docs.astral.sh/uv/getting-started/installation/) |
| A name and email for git | `git config --global user.name` | `git config --global user.name "Your Name"` and `git config --global user.email "you@example.org"` |

You do not need to know git. The name and email only label the history `strata` writes for you.

## Option 1: a `strata` command on your PATH (recommended)

```
uv tool install git+https://github.com/EGuthrieWasTaken/strata.git
strata --version
```

If your shell says `strata: command not found`, `uv` has installed it but your shell has not been told where.
Run `uv tool update-shell`, open a new terminal, and try again.

To update later: `uv tool upgrade strata`. To remove it: `uv tool uninstall strata`.

## Option 2: from a checkout

Use this if you want to read the code, try an unreleased change, or contribute.

```
git clone https://github.com/EGuthrieWasTaken/strata.git
cd strata
uv sync
uv run strata --version
```

Everything in this wiki is written as `strata ...`; from a checkout, write `uv run strata ...` instead (run
from the checkout directory, or point at a review with `-C /path/to/review`).

## Option 3: a container

No Python needed, only a container runtime. See [Running in a container](Running-in-a-Container).

## Check that it works

```
strata --version
mkdir try-it && cd try-it
strata init . --title "Try it" --actor me --actor-name "My Name"
strata status
strata doctor
```

`strata doctor` checks git's version, that the versioned hooks are installed, and that the two merge drivers
`strata` relies on for shared reviews are present. If something is missing, `strata doctor --fix` installs it.

You can delete the `try-it` folder afterwards; nothing is stored anywhere else on your computer.

## Things worth knowing

- **`strata` must be on the PATH of whatever runs your git commands.** `strata` installs small git hooks that
  call `strata` by name. If you run it through an absolute path, a script or an editor that has a different
  PATH, a commit can fail with `strata: not found`. Running it from your normal terminal avoids this.
- **Line endings are handled for you.** A review's `.gitattributes` makes every file use Unix line endings
  whatever your system's git setting (including Git for Windows' default of converting to Windows endings), so
  collaborators on different systems get identical files.
- **Nothing leaves your computer unless you ask.** `strata` makes no network requests unless you turn on
  *enrichment* (looking up open-access links) or run `strata sync`/`strata clone` against a remote.
- **Full texts are never committed.** The PDFs you collect stay on your disk; the review records only an
  identifier and version for each.

## Next

[Quickstart](Quickstart): a whole (tiny) review in one sitting.
