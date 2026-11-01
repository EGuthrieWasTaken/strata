"""Zotero as a reference manager: Zotero owns the documents, `strata` owns the decisions.

Implements openspec:zotero-integration. The local HTTP API (`127.0.0.1:23119`) is preferred; the
Web API v3 (`api.zotero.org`) is the fallback and is what writes go through.
"""
