# Copyright (c) lintmax-py contributors. Licensed under the MIT License.
from __future__ import annotations

from typing import TYPE_CHECKING

from lintmax_py.config import COPYRIGHT_RULE, copyright_notice, ruff_toml, vulture_allowances
from lintmax_py.gate import DEV_EXTRA_NAMES, _deptry_args

if TYPE_CHECKING:
    from pathlib import Path

NOTICE = "(?i)Copyright \\\\(c\\\\) Example"


def test_an_undeclared_notice_stands_the_rule_down(tmp_path: Path) -> None:
    assert not copyright_notice(tmp_path)
    assert COPYRIGHT_RULE in ruff_toml([], tmp_path)


def test_a_declared_notice_enforces_the_rule(tmp_path: Path) -> None:
    body = f'[lint.flake8-copyright]\nnotice-rgx = "{NOTICE}"\n'
    (tmp_path / "ruff.toml").write_text(body, encoding="utf-8")
    assert copyright_notice(tmp_path) == NOTICE.replace("\\\\", "\\")
    generated = ruff_toml([], tmp_path)
    assert COPYRIGHT_RULE not in generated


def test_a_runtime_extra_is_not_a_development_group(tmp_path: Path) -> None:
    body = '[project]\nname = "x"\n[project.optional-dependencies]\nreceiver = ["flask"]\n'
    (tmp_path / "pyproject.toml").write_text(body, encoding="utf-8")
    assert "--optional-dependencies-dev-groups" not in _deptry_args(tmp_path)


def test_a_development_named_extra_is_forwarded(tmp_path: Path) -> None:
    body = '[project]\nname = "x"\n[project.optional-dependencies]\ndev = ["pytest"]\n'
    (tmp_path / "pyproject.toml").write_text(body, encoding="utf-8")
    args = _deptry_args(tmp_path)
    assert "--optional-dependencies-dev-groups" in args
    assert "dev" in args
    assert "dev" in DEV_EXTRA_NAMES


def test_a_project_declares_what_the_dead_code_scan_cannot_see(tmp_path: Path) -> None:
    body = '[tool.vulture]\nignore_decorators = ["@app.route"]\nignore_names = ["model_config"]\n'
    (tmp_path / "pyproject.toml").write_text(body, encoding="utf-8")
    assert vulture_allowances(tmp_path) == {
        "ignore_decorators": ["@app.route"],
        "ignore_names": ["model_config"],
    }


def test_a_silent_project_declares_nothing(tmp_path: Path) -> None:
    assert vulture_allowances(tmp_path) == {}
