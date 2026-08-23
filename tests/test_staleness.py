# Copyright (c) lintmax-py contributors. Licensed under the MIT License.
from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from lintmax_py import gate, staleness
from lintmax_py.proc import Result

if TYPE_CHECKING:
    from pathlib import Path


def test_an_exact_pin_is_not_stale_when_the_resolver_keeps_it(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "x"\ndependencies = ["model==1.0"]\n',
        encoding="utf-8",
    )
    (tmp_path / "uv.lock").write_text(
        '[[package]]\nname = "model"\nversion = "1.0"\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(
        staleness,
        "run",
        lambda *_args, **_kwargs: Result(code=0, out="Resolved 1 package"),
        raising=False,
    )

    assert staleness.behind(tmp_path) == []


def test_a_compatible_direct_upgrade_is_reported(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "x"\ndependencies = ["model>=1,<2"]\n',
        encoding="utf-8",
    )
    (tmp_path / "uv.lock").write_text(
        '[[package]]\nname = "model"\nversion = "1.0"\n',
        encoding="utf-8",
    )
    commands: list[list[str]] = []

    def resolver(command: list[str], **_kwargs: object) -> Result:
        commands.append(command)
        return Result(code=0, out="Update model v1.0 -> v1.1")

    monkeypatch.setattr(staleness, "run", resolver)

    assert staleness.behind(tmp_path) == ["model 1.0 -> 1.1"]
    assert commands == [["uv", "lock", "--upgrade", "--dry-run", "--no-progress", "--color", "never"]]


def test_equivalent_distribution_name_spellings_match(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "x"\ndependencies = ["my_package>=1"]\n',
        encoding="utf-8",
    )
    (tmp_path / "uv.lock").write_text(
        '[[package]]\nname = "my-package"\nversion = "1.0"\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(
        staleness,
        "run",
        lambda *_args, **_kwargs: Result(code=0, out="Update my-package v1.0 -> v1.1"),
        raising=False,
    )

    assert staleness.behind(tmp_path) == ["my-package 1.0 -> 1.1"]


def test_a_transitive_upgrade_is_not_reported(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "x"\ndependencies = ["direct>=1"]\n',
        encoding="utf-8",
    )
    (tmp_path / "uv.lock").write_text(
        '[[package]]\nname = "direct"\nversion = "1.0"\n[[package]]\nname = "transitive"\nversion = "1.0"\n',
        encoding="utf-8",
    )
    output = "Update direct v1.0 -> v1.1\nUpdate transitive v1.0 -> v2.0"
    monkeypatch.setattr(
        staleness,
        "run",
        lambda *_args, **_kwargs: Result(code=0, out=output),
        raising=False,
    )

    assert staleness.behind(tmp_path) == ["direct 1.0 -> 1.1"]


@pytest.mark.parametrize(
    ("exit_code", "resolver_output"),
    [
        pytest.param(1, "No solution found when resolving dependencies", id="solver"),
        pytest.param(1, "HTTP status client error (401 Unauthorized)", id="authentication"),
        pytest.param(1, "failed to download package metadata: connection reset", id="network"),
    ],
)
def test_a_failed_resolution_fails_the_gate_instead_of_claiming_a_clean_check(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    exit_code: int,
    resolver_output: str,
) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "x"\ndependencies = ["model>=1"]\n',
        encoding="utf-8",
    )
    (tmp_path / "uv.lock").write_text(
        '[[package]]\nname = "model"\nversion = "1.0"\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(
        staleness,
        "run",
        lambda *_args, **_kwargs: Result(code=exit_code, out=resolver_output),
        raising=False,
    )

    with pytest.raises(staleness.ResolutionUnavailableError) as error:
        staleness.behind(tmp_path)

    assert error.value.result == Result(code=exit_code, out=resolver_output)
    assert str(error.value) == (
        f"uv lock --upgrade --dry-run could not establish staleness evidence (exit {exit_code}): {resolver_output}"
    )


def test_a_resolution_failure_becomes_an_explicit_staleness_finding(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A resolver failure must make `lintmax-py check` nonzero, not look clean."""
    failure = staleness.ResolutionUnavailableError(Result(code=124, out="uv timed out"))

    def unavailable(_root: Path) -> list[str]:
        raise failure

    monkeypatch.setattr(staleness, "behind", unavailable)

    assert gate._staleness_stages(tmp_path) == [
        gate.Finding(
            stage="staleness",
            detail=("uv lock --upgrade --dry-run could not establish staleness evidence (exit 124): uv timed out"),
        ),
    ]
