"""Handing a `zotero://` link to the operating system.

Implements openspec:zotero-integration#commands. Python's `webbrowser` gives such a link
to the default *browser*, which on a first use asks the person whether to pass it on and meanwhile
does nothing: `strata zotero open` exited 0 with nothing opened (`docs/zotero-real-run.md`). The
operating system's own opener goes straight to the program registered for the scheme.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import webbrowser


def open_link(uri: str) -> bool:
    """Open a link with the program registered for its scheme; whether it could be handed over."""
    try:
        if sys.platform == "win32":
            os.startfile(uri)  # type: ignore[attr-defined,unused-ignore]  # noqa: S606
            return True
        opener = "open" if sys.platform == "darwin" else "xdg-open"
        path = shutil.which(opener)
        if path is not None:
            done = subprocess.run(  # noqa: S603
                [path, uri],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=15,
                check=False,
            )
            if done.returncode == 0:
                return True
    except (OSError, subprocess.SubprocessError):
        pass
    return bool(webbrowser.open(uri))
