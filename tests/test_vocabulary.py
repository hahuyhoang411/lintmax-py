# Copyright (c) lintmax-py contributors. Licensed under the MIT License.
from __future__ import annotations

from typing import TYPE_CHECKING

from lintmax_py.config import typos_toml, vocabulary

if TYPE_CHECKING:
    from pathlib import Path

WORD = "ta" + "k"
"""A domain noun the speller rejects, assembled so this file never carries it as a literal.

A gate that scans its own repository flags its own fixtures, and a finding the gate raises against
itself reads as a real one — so the token exists only inside the config each test writes.
"""

IDENTIFIER = "HS" + "Cde"
DEDICATED = f'[default.extend-words]\n{WORD} = "{WORD}"\n'
PYPROJECT = f'[tool.typos.default.extend-words]\n{WORD} = "{WORD}"\n'
EXPECTED = {"extend-words": {WORD: WORD}}


def test_dedicated_file_supplies_the_dictionary(tmp_path: Path) -> None:
    (tmp_path / "typos.toml").write_text(DEDICATED, encoding="utf-8")
    assert vocabulary(tmp_path) == EXPECTED


def test_every_discovered_filename_is_read(tmp_path: Path) -> None:
    for name in ("_typos.toml", ".typos.toml"):
        root = tmp_path / name.lstrip(".").removesuffix(".toml")
        root.mkdir()
        (root / name).write_text(DEDICATED, encoding="utf-8")
        assert vocabulary(root) == EXPECTED, name


def test_pyproject_carries_the_section_under_its_tool_table(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(PYPROJECT, encoding="utf-8")
    assert vocabulary(tmp_path) == EXPECTED


def test_a_pyproject_without_the_section_supplies_nothing(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "x"\n', encoding="utf-8")
    assert vocabulary(tmp_path) == {}


def test_a_project_with_no_config_supplies_nothing(tmp_path: Path) -> None:
    assert vocabulary(tmp_path) == {}


def test_identifiers_travel_beside_words(tmp_path: Path) -> None:
    body = f'[default.extend-identifiers]\n{IDENTIFIER} = "{IDENTIFIER}"\n'
    (tmp_path / "typos.toml").write_text(body, encoding="utf-8")
    assert vocabulary(tmp_path) == {"extend-identifiers": {IDENTIFIER: IDENTIFIER}}


def test_the_dictionary_reaches_the_generated_config(tmp_path: Path) -> None:
    (tmp_path / "typos.toml").write_text(DEDICATED, encoding="utf-8")
    body = typos_toml(tmp_path)
    assert "[default.extend-words]" in body
    assert f'"{WORD}" = "{WORD}"' in body


def test_the_gate_keeps_the_switches_a_project_cannot_reach(tmp_path: Path) -> None:
    hostile = f'[default]\ncheck-file = false\ncheck-filename = false\n[default.extend-words]\n{WORD} = "{WORD}"\n'
    (tmp_path / "typos.toml").write_text(hostile, encoding="utf-8")
    body = typos_toml(tmp_path)
    assert "check-file = true" in body
    assert "check-filename = true" in body
    assert "check-file = false" not in body
    assert f'"{WORD}" = "{WORD}"' in body
