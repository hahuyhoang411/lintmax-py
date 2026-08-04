# Copyright (c) lintmax-py contributors. Licensed under the MIT License.
from __future__ import annotations

from typing import TYPE_CHECKING

from lintmax_py import gate
from lintmax_py.proc import Result

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    import pytest


def _record(calls: list[str]) -> Callable[..., Result]:
    def fake(cmd: list[str], **_kwargs: object) -> Result:
        calls.append(cmd[0])
        return Result(code=0, out="")

    return fake


def test_the_formatter_runs_before_the_checker_it_can_invalidate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A formatter that runs second rewrites the very file the checker just blessed.

    The check then passes against a version that no longer exists on disk, so the finding it owed
    surfaces on the next run against a tree the gate itself rewrote.
    """
    (tmp_path / "s.sh").write_text("#!/usr/bin/env bash\necho hi\n", encoding="utf-8")
    calls: list[str] = []
    monkeypatch.setattr(gate, "run", _record(calls))

    gate._repo_stages(tmp_path, tmp_path, fix=True)

    assert "shfmt" in calls
    assert "shellcheck" in calls
    assert calls.index("shfmt") < calls.index("shellcheck")
