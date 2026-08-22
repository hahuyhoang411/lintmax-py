# Copyright (c) lintmax-py contributors. Licensed under the MIT License.
"""The gate owns its own toolchain, so installing one of its tools must not be refusable."""

from __future__ import annotations

import inspect

from lintmax_py import tools


def test_installing_a_tool_overwrites_whatever_holds_its_name() -> None:
    """A stale entry left by an earlier install must not be able to disable a stage.

    A tool store that has been wiped leaves the launcher behind as a DANGLING symlink, so the
    installer refuses with "executable already exists" while the executable resolves to nothing.
    The stage then reports itself not installed on every run and stops judging anything, which
    reads as a gate with fewer rules rather than a gate that is broken.
    """
    source = inspect.getsource(tools.ensure)
    install = next(line for line in source.splitlines() if '"install"' in line)
    assert '"--force"' in install, "an install that can be refused is a stage that can silently vanish"
