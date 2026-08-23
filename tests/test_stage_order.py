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


def test_zsh_scripts_are_parsed_by_zsh_and_never_sent_to_shellcheck(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ShellCheck cannot parse zsh syntax, so zsh owns zsh syntax validation."""
    script = tmp_path / "zsh-script.sh"
    script.write_text("#!/usr/bin/env zsh\nprint -r -- hello\n", encoding="utf-8")
    commands: list[list[str]] = []

    def record(cmd: list[str], **_kwargs: object) -> Result:
        commands.append(cmd)
        return Result(code=0, out="")

    monkeypatch.setattr(gate, "run", record)

    gate._repo_stages(tmp_path, tmp_path, fix=False)

    assert ["zsh", "-n", str(script)] in commands
    assert all(str(script) not in command for command in commands if command[0] == "shellcheck")


def test_zsh_env_options_that_consume_an_operand_stay_on_the_zsh_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Env option operands are setup, never the interpreter the gate must classify."""
    scripts = {
        tmp_path / "unset-zsh.sh": "#!/usr/bin/env -u PYTHONPATH zsh\n",
        tmp_path / "chdir-zsh.sh": "#!/usr/bin/env -C /tmp zsh\n",
        tmp_path / "path-zsh.sh": "#!/usr/bin/env -P /usr/local/bin zsh\n",
        tmp_path / "split-zsh.sh": "#!/usr/bin/env -S 'zsh -f'\n",
    }
    for script, shebang in scripts.items():
        script.write_text(f"{shebang}print -r -- hello\n", encoding="utf-8")
    commands: list[list[str]] = []

    def record(cmd: list[str], **_kwargs: object) -> Result:
        commands.append(cmd)
        return Result(code=0, out="")

    monkeypatch.setattr(gate, "run", record)

    gate._repo_stages(tmp_path, tmp_path, fix=False)

    for script in scripts:
        assert ["zsh", "-n", str(script)] in commands
        assert all(str(script) not in command for command in commands if command[0] == "shellcheck")


def test_supported_shell_shebangs_stay_formatted_before_shellcheck(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Supported POSIX-family scripts retain the formatter-before-checker contract."""
    scripts = [tmp_path / f"{interpreter}.sh" for interpreter in ("sh", "bash", "dash", "ksh", "busybox")]
    for interpreter, script in zip(("sh", "bash", "dash", "ksh", "busybox"), scripts, strict=True):
        script.write_text(f"#!/usr/bin/env {interpreter}\necho hi\n", encoding="utf-8")
    commands: list[list[str]] = []

    def record(cmd: list[str], **_kwargs: object) -> Result:
        commands.append(cmd)
        return Result(code=0, out="")

    monkeypatch.setattr(gate, "run", record)

    gate._repo_stages(tmp_path, tmp_path, fix=True)

    shfmt_index = next(index for index, command in enumerate(commands) if command[0] == "shfmt")
    shellcheck_index = next(index for index, command in enumerate(commands) if command[0] == "shellcheck")
    assert shfmt_index < shellcheck_index
    for script in scripts:
        assert str(script) in commands[shfmt_index]
        assert str(script) in commands[shellcheck_index]
    assert all(command[0] != "zsh" for command in commands)
