"""Tests that talk to a real Zotero. Not in the default test paths (`pyproject.toml`): they run in
`.github/workflows/zotero-live.yml`, or by hand with `uv run pytest tests/live`.

Each module says what it needs and skips when it is absent, so a bare run never fails for want
of a key or a running Zotero.
"""
