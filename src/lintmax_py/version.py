# Copyright (c) lintmax-py contributors. Licensed under the MIT License.
"""The version the package was installed as, read from its own metadata.

A literal in the source is a second home for a fact the manifest already owns, and the two drift
silently: only a release exposes it, by which point the registry serves one number and the installed
tool reports another.
"""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

DISTRIBUTION = "lintmax-py"
UNINSTALLED = "0+unknown"


def installed() -> str:
    """Read the installed distribution's version.

    Returns:
        The version, or a marker when the package is run from a checkout that was never installed.

    """
    try:
        return version(DISTRIBUTION)
    except PackageNotFoundError:
        return UNINSTALLED
