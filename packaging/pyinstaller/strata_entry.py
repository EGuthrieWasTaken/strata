"""The entry point a standalone `strata` binary runs (`packaging/pyinstaller/strata.spec`)."""

from strata.cli.main import app

if __name__ == "__main__":
    app()
