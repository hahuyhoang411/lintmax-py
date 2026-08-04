# Copyright (c) lintmax-py contributors. Licensed under the MIT License.
from __future__ import annotations

from typing import TYPE_CHECKING

from lintmax_py.config import confusables, ruff_toml

if TYPE_CHECKING:
    from pathlib import Path

FULLWIDTH_PAREN = chr(0xFF08)
"""A character the ambiguous-name rule hunts, built rather than written.

A gate that scans its own repository flags its own fixtures, and a finding it raises against itself
reads as a real one — so the literal exists only in the config each test writes.
"""
DECLARED = f'[lint]\nallowed-confusables = ["{FULLWIDTH_PAREN}"]\n'


def test_a_dedicated_ruff_file_declares_the_writing_system(tmp_path: Path) -> None:
    (tmp_path / "ruff.toml").write_text(DECLARED, encoding="utf-8")
    assert confusables(tmp_path) == [FULLWIDTH_PAREN]


def test_the_hidden_filename_is_read_too(tmp_path: Path) -> None:
    (tmp_path / ".ruff.toml").write_text(DECLARED, encoding="utf-8")
    assert confusables(tmp_path) == [FULLWIDTH_PAREN]


def test_pyproject_carries_it_under_the_tool_table(tmp_path: Path) -> None:
    body = f'[tool.ruff.lint]\nallowed-confusables = ["{FULLWIDTH_PAREN}"]\n'
    (tmp_path / "pyproject.toml").write_text(body, encoding="utf-8")
    assert confusables(tmp_path) == [FULLWIDTH_PAREN]


def test_a_project_declaring_none_gets_none(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "x"\n', encoding="utf-8")
    assert confusables(tmp_path) == []


def test_the_declaration_reaches_the_generated_config(tmp_path: Path) -> None:
    (tmp_path / "ruff.toml").write_text(DECLARED, encoding="utf-8")
    body = ruff_toml([], tmp_path)
    assert f'allowed-confusables = ["{FULLWIDTH_PAREN}"]' in body


def test_a_silent_project_leaves_the_key_out_entirely(tmp_path: Path) -> None:
    body = ruff_toml([], tmp_path)
    assert "allowed-confusables" not in body
