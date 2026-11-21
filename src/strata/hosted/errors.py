"""Errors shared by the hosted modules, kept apart so that modules which `strata.hosted.instance`
imports can raise them too."""

from __future__ import annotations


class InstanceError(ValueError):
    """Something about the instance or a project is not as the command needs it."""
