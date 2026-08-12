# Copyright (c) lintmax-py contributors. Licensed under the MIT License.
from __future__ import annotations

from typing import TYPE_CHECKING

from lintmax_py import staleness
from lintmax_py.proc import Result

if TYPE_CHECKING:
    from pathlib import Path

    import pytest


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
    monkeypatch.setattr(staleness, "latest", lambda _name: "2.0", raising=False)
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
    monkeypatch.setattr(staleness, "latest", lambda _name: "1.0", raising=False)
    monkeypatch.setattr(
        staleness,
        "run",
        lambda *_args, **_kwargs: Result(code=0, out="Update model v1.0 -> v1.1"),
        raising=False,
    )

    assert staleness.behind(tmp_path) == ["model 1.0 -> 1.1"]


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


def test_a_failed_resolution_does_not_invent_staleness(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
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
        lambda *_args, **_kwargs: Result(code=1, out="resolution failed"),
        raising=False,
    )

    assert staleness.behind(tmp_path) == []
