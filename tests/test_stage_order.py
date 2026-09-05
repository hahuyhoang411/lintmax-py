# Copyright (c) lintmax-py contributors. Licensed under the MIT License.
from __future__ import annotations

import shutil
from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING

from lintmax_py import cli, gate, tools
from lintmax_py.proc import Result, run

if TYPE_CHECKING:
    from collections.abc import Callable

    import pytest


def _toolchain(root: Path, *, ruff: Path | None = None) -> tools.Toolchain:
    managed_bin = root / "managed-tools"
    paths = {
        executable: (ruff if executable == "ruff" and ruff is not None else managed_bin / executable)
        for executable in (
            "ruff",
            "ty",
            "vulture",
            "deptry",
            "pip-audit",
            "typos",
            "shellcheck",
            "shfmt",
            "dprint",
        )
    }
    selected = {
        executable: tools.Tool(
            package=executable,
            executable=executable,
            path=path,
            version=f"{executable} test",
        )
        for executable, path in paths.items()
    }
    uvx_path = Path(shutil.which("uvx") or "/opt/homebrew/bin/uvx").resolve()
    metadata = uvx_path.stat()
    version = run([str(uvx_path), "--version"]).out.splitlines()[0]
    return tools.Toolchain(
        tools=MappingProxyType(selected),
        generation=managed_bin,
        uvx=tools.UvxLauncher(uvx_path, metadata.st_dev, metadata.st_ino, version),
        zsh=managed_bin / "zsh",
    )


def _record(calls: list[str]) -> Callable[..., Result]:
    def fake(cmd: list[str], **_kwargs: object) -> Result:
        calls.append(Path(cmd[0]).name)
        return Result(code=0, out="")

    return fake


def test_explicit_absolute_uv_project_environment_selects_the_shared_environment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An explicit uv environment belongs to the checked project, not the gate checkout."""
    root = tmp_path / "project"
    root.mkdir()
    shared_environment = tmp_path / "shared-environment"
    shared_environment.mkdir()
    monkeypatch.setenv("UV_PROJECT_ENVIRONMENT", str(shared_environment))

    environment, error = gate._environment(root)

    assert environment == ["--python", str(shared_environment)]
    assert error is None


def test_absolute_uv_project_environment_bypasses_an_invalid_workspace_member_glob(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An absolute environment needs no workspace lookup and cannot be broken by its config."""
    workspace = tmp_path / "workspace"
    member = workspace / "member"
    member.mkdir(parents=True)
    (workspace / "pyproject.toml").write_text(
        '[project]\nname = "workspace"\nversion = "0.0.0"\n\n[tool.uv.workspace]\nmembers = ["/not-a-relative-glob"]\n',
        encoding="utf-8",
    )
    (member / "pyproject.toml").write_text(
        '[project]\nname = "member"\nversion = "0.0.0"\n',
        encoding="utf-8",
    )
    shared_environment = tmp_path / "shared-environment"
    shared_environment.mkdir()
    monkeypatch.setenv("UV_PROJECT_ENVIRONMENT", str(shared_environment))

    environment, error = gate._environment(member)

    assert environment == ["--python", str(shared_environment)]
    assert error is None


def test_relative_uv_project_environment_is_resolved_from_a_standalone_checked_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The caller's checkout cannot reinterpret a target project's relative uv path."""
    root = tmp_path / "project"
    root.mkdir()
    environment_directory = root / ".shared-environment"
    environment_directory.mkdir()
    caller_directory = tmp_path / "different-checkout"
    caller_directory.mkdir()
    monkeypatch.chdir(caller_directory)
    monkeypatch.setenv("UV_PROJECT_ENVIRONMENT", ".shared-environment")

    environment, error = gate._environment(root)

    assert environment == ["--python", str(environment_directory)]
    assert error is None


def test_relative_uv_project_environment_is_resolved_from_the_workspace_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A member uses the shared workspace path even when the gate is invoked for that member."""
    workspace = tmp_path / "workspace"
    member = workspace / "packages" / "member"
    member.mkdir(parents=True)
    (workspace / "pyproject.toml").write_text(
        '[project]\nname = "workspace"\nversion = "0.0.0"\n\n[tool.uv.workspace]\nmembers = ["packages/*"]\n',
        encoding="utf-8",
    )
    (member / "pyproject.toml").write_text(
        '[project]\nname = "member"\nversion = "0.0.0"\n',
        encoding="utf-8",
    )
    shared_environment = workspace / ".shared-environment"
    shared_environment.mkdir()
    monkeypatch.setenv("UV_PROJECT_ENVIRONMENT", ".shared-environment")

    environment, error = gate._environment(member)

    assert environment == ["--python", str(shared_environment)]
    assert error is None


def test_workspace_member_source_subdirectory_uses_the_workspace_environment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A checked source subdirectory inherits its enclosing member's workspace environment."""
    workspace = tmp_path / "workspace"
    member = workspace / "packages" / "member"
    source_directory = member / "src"
    source_directory.mkdir(parents=True)
    (workspace / "pyproject.toml").write_text(
        '[project]\nname = "workspace"\nversion = "0.0.0"\n\n[tool.uv.workspace]\nmembers = ["packages/*"]\n',
        encoding="utf-8",
    )
    (member / "pyproject.toml").write_text(
        '[project]\nname = "member"\nversion = "0.0.0"\n',
        encoding="utf-8",
    )
    shared_environment = workspace / ".shared-environment"
    shared_environment.mkdir()
    monkeypatch.setenv("UV_PROJECT_ENVIRONMENT", ".shared-environment")

    environment, error = gate._environment(source_directory)

    assert environment == ["--python", str(shared_environment)]
    assert error is None


def test_ancestor_workspace_does_not_capture_a_project_outside_its_members(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Only declared members inherit a workspace environment path."""
    workspace = tmp_path / "workspace"
    outsider = workspace / "outside"
    outsider.mkdir(parents=True)
    (workspace / "pyproject.toml").write_text(
        '[project]\nname = "workspace"\nversion = "0.0.0"\n\n[tool.uv.workspace]\nmembers = ["packages/*"]\n',
        encoding="utf-8",
    )
    (outsider / "pyproject.toml").write_text(
        '[project]\nname = "outside"\nversion = "0.0.0"\n',
        encoding="utf-8",
    )
    (workspace / ".shared-environment").mkdir()
    local_environment = outsider / ".shared-environment"
    local_environment.mkdir()
    monkeypatch.setenv("UV_PROJECT_ENVIRONMENT", ".shared-environment")

    environment, error = gate._environment(outsider)

    assert environment == ["--python", str(local_environment)]
    assert error is None


def test_relative_uv_project_environment_ignores_an_invalid_workspace_member_glob(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A malformed workspace pattern cannot crash the gate or redirect a standalone environment."""
    workspace = tmp_path / "workspace"
    member = workspace / "member"
    member.mkdir(parents=True)
    (workspace / "pyproject.toml").write_text(
        '[project]\nname = "workspace"\nversion = "0.0.0"\n\n[tool.uv.workspace]\nmembers = ["/not-a-relative-glob"]\n',
        encoding="utf-8",
    )
    (member / "pyproject.toml").write_text(
        '[project]\nname = "member"\nversion = "0.0.0"\n',
        encoding="utf-8",
    )
    local_environment = member / ".shared-environment"
    local_environment.mkdir()
    monkeypatch.setenv("UV_PROJECT_ENVIRONMENT", ".shared-environment")

    environment, error = gate._environment(member)

    assert environment == ["--python", str(local_environment)]
    assert error is None


def test_explicit_uv_project_environment_precedes_the_checked_root_dot_venv(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An explicit uv configuration wins even when the checked project has a local environment."""
    root = tmp_path / "project"
    root.mkdir()
    (root / ".venv").mkdir()
    shared_environment = tmp_path / "shared-environment"
    shared_environment.mkdir()
    monkeypatch.setenv("UV_PROJECT_ENVIRONMENT", str(shared_environment))

    environment, error = gate._environment(root)

    assert environment == ["--python", str(shared_environment)]
    assert error is None


def test_unset_uv_project_environment_falls_back_to_checked_root_dot_venv(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The original local-environment behavior remains when uv has no explicit path."""
    root = tmp_path / "project"
    root.mkdir()
    local_environment = root / ".venv"
    local_environment.mkdir()
    monkeypatch.delenv("UV_PROJECT_ENVIRONMENT", raising=False)

    environment, error = gate._environment(root)

    assert environment == ["--python", str(local_environment)]
    assert error is None


def test_standalone_project_source_subdirectory_uses_the_project_environment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A checked source subdirectory inherits its enclosing standalone project's environment."""
    project = tmp_path / "project"
    source_directory = project / "src"
    source_directory.mkdir(parents=True)
    (project / "pyproject.toml").write_text(
        '[project]\nname = "project"\nversion = "0.0.0"\n',
        encoding="utf-8",
    )
    local_environment = project / ".shared-environment"
    local_environment.mkdir()
    monkeypatch.setenv("UV_PROJECT_ENVIRONMENT", ".shared-environment")

    environment, error = gate._environment(source_directory)

    assert environment == ["--python", str(local_environment)]
    assert error is None


def test_invalid_explicit_uv_project_environment_reports_a_ty_finding_without_running_ty(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A configured missing path or file must fail rather than silently selecting another environment."""
    root = tmp_path / "project"
    root.mkdir()
    non_directory = tmp_path / "not-an-environment"
    non_directory.write_text("not a directory", encoding="utf-8")

    for candidate in (tmp_path / "missing-environment", non_directory):
        calls: list[str] = []
        monkeypatch.setenv("UV_PROJECT_ENVIRONMENT", str(candidate))
        monkeypatch.setattr(gate, "run", _record(calls))

        findings = gate._python_stages(root, root, _toolchain(tmp_path), fix=False)

        assert findings == [
            gate.Finding(
                stage="ty",
                detail=f"UV_PROJECT_ENVIRONMENT must name an existing directory: {candidate}",
            ),
        ]
        assert "ty" not in calls


def test_empty_uv_project_environment_falls_back_to_the_workspace_default_environment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Uv treats an empty path as unset and selects the workspace default environment."""
    workspace = tmp_path / "workspace"
    member = workspace / "packages" / "member"
    member.mkdir(parents=True)
    (workspace / "pyproject.toml").write_text(
        '[project]\nname = "workspace"\nversion = "0.0.0"\n\n[tool.uv.workspace]\nmembers = ["packages/*"]\n',
        encoding="utf-8",
    )
    (member / "pyproject.toml").write_text(
        '[project]\nname = "member"\nversion = "0.0.0"\n',
        encoding="utf-8",
    )
    default_environment = workspace / ".venv"
    default_environment.mkdir()
    monkeypatch.setenv("UV_PROJECT_ENVIRONMENT", "")

    environment, error = gate._environment(member)

    assert environment == ["--python", str(default_environment)]
    assert error is None


def test_ty_runs_from_the_checked_projects_root_not_the_gate_callers_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ty must discover target configuration and editable sources from the checked project."""
    project = tmp_path / "project"
    source_directory = project / "src"
    source_directory.mkdir(parents=True)
    (project / "pyproject.toml").write_text(
        '[project]\nname = "project"\nversion = "0.0.0"\n',
        encoding="utf-8",
    )
    (project / ".venv").mkdir()
    other_checkout = tmp_path / "different-checkout"
    other_checkout.mkdir()
    monkeypatch.chdir(other_checkout)
    monkeypatch.delenv("UV_PROJECT_ENVIRONMENT", raising=False)
    calls: list[tuple[list[str], str | None]] = []

    def record(cmd: list[str], **kwargs: object) -> Result:
        cwd = kwargs.get("cwd")
        assert cwd is None or isinstance(cwd, str)
        calls.append((cmd, cwd))
        return Result(code=0, out="")

    monkeypatch.setattr(gate, "run", record)

    findings = gate._python_stages(source_directory, source_directory, _toolchain(tmp_path), fix=False)

    assert findings == []
    ty_command, ty_cwd = next((command, cwd) for command, cwd in calls if Path(command[0]).name == "ty")
    assert ty_command == [
        _toolchain(tmp_path).path("ty"),
        "check",
        "--error",
        "all",
        "--project",
        str(project),
        "--python",
        str(project / ".venv"),
        str(source_directory),
    ]
    assert ty_cwd == str(project)


def test_cli_prints_an_invalid_explicit_uv_project_environment_as_a_ty_finding(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The command exits non-zero with a readable configuration error, not an uncaught exception."""
    root = tmp_path / "project"
    root.mkdir()
    missing_environment = tmp_path / "missing-environment"
    monkeypatch.setenv("UV_PROJECT_ENVIRONMENT", str(missing_environment))
    monkeypatch.setattr(gate, "run", _record([]))
    monkeypatch.setattr(
        cli,
        "run_gate",
        lambda checked_root, *, fix: gate._python_stages(checked_root, checked_root, _toolchain(tmp_path), fix=fix),
    )

    exit_code = cli.main(["check", str(root)])

    assert exit_code == 1
    assert capsys.readouterr().err == (
        f"ty: UV_PROJECT_ENVIRONMENT must name an existing directory: {missing_environment}\n"
    )


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

    gate._repo_stages(tmp_path, tmp_path, _toolchain(tmp_path), fix=True)

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

    gate._repo_stages(tmp_path, tmp_path, _toolchain(tmp_path), fix=False)

    assert [str(_toolchain(tmp_path).zsh), "-n", str(script)] in commands
    assert all(str(script) not in command for command in commands if Path(command[0]).name == "shellcheck")


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

    gate._repo_stages(tmp_path, tmp_path, _toolchain(tmp_path), fix=False)

    for script in scripts:
        assert [str(_toolchain(tmp_path).zsh), "-n", str(script)] in commands
        assert all(str(script) not in command for command in commands if Path(command[0]).name == "shellcheck")


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

    gate._repo_stages(tmp_path, tmp_path, _toolchain(tmp_path), fix=True)

    shfmt_index = next(index for index, command in enumerate(commands) if Path(command[0]).name == "shfmt")
    shellcheck_index = next(index for index, command in enumerate(commands) if Path(command[0]).name == "shellcheck")
    assert shfmt_index < shellcheck_index
    for script in scripts:
        assert str(script) in commands[shfmt_index]
        assert str(script) in commands[shellcheck_index]
    assert all(Path(command[0]).name != "zsh" for command in commands)


def _disable_gate_stages(monkeypatch: pytest.MonkeyPatch, root: Path) -> None:
    """Isolate the orchestration boundary from external linters for safety tests."""
    monkeypatch.setattr(gate.tools, "ensure", lambda: _toolchain(root))
    monkeypatch.setattr(
        gate.rules,
        "inventory",
        lambda tool: gate.rules.RuffInventory(tool.path.as_posix(), tool.version, ()),
    )
    monkeypatch.setattr(gate.config, "materialize", lambda *_args: (root, "digest"))
    monkeypatch.setattr(gate, "_python_stages", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(gate, "_repo_stages", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(gate, "_staleness_stages", lambda *_args, **_kwargs: [])


def test_fix_preserves_an_ordinary_rationale_comment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A quality gate may not erase the rationale a maintainer left beside code."""
    source = tmp_path / "module.py"
    original = "answer = 42  # why this clinical threshold exists\n"
    source.write_text(original, encoding="utf-8")
    _disable_gate_stages(monkeypatch, tmp_path)

    assert gate.run_gate(tmp_path, fix=True) == []
    assert source.read_text(encoding="utf-8") == original


def test_check_does_not_report_an_ordinary_provenance_comment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Comments are not a lint defect without a sound, purpose-built detector."""
    source = tmp_path / "module.py"
    source.write_text("# derived from the published corpus receipt\nanswer = 42\n", encoding="utf-8")
    _disable_gate_stages(monkeypatch, tmp_path)

    assert gate.run_gate(tmp_path, fix=False) == []
    assert source.read_text(encoding="utf-8") == "# derived from the published corpus receipt\nanswer = 42\n"


def test_fix_requests_only_ruff_safe_fixes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Fix mode must retain Ruff's safe fixes while declining unsafe rewrites."""
    commands: list[list[str]] = []

    def record(command: list[str], **_kwargs: object) -> Result:
        commands.append(command)
        return Result(code=0, out="")

    monkeypatch.setattr(gate, "run", record)

    assert (
        gate._python_stages(
            tmp_path,
            tmp_path,
            _toolchain(tmp_path, ruff=Path(shutil.which("ruff") or "ruff")),
            fix=True,
        )
        == []
    )
    ruff_check = next(command for command in commands if Path(command[0]).name == "ruff" and command[1] == "check")
    assert "--fix" in ruff_check
    assert "--unsafe-fixes" not in ruff_check


def test_fix_executes_a_ruff_safe_fix(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The safety boundary must not turn Ruff's ordinary repairs into a no-op."""
    config = tmp_path / "ruff.toml"
    config.write_text('[lint]\nselect = ["F401"]\n', encoding="utf-8")
    source = tmp_path / "module.py"
    source.write_text("import os\n", encoding="utf-8")

    def run_ruff(command: list[str], **kwargs: object) -> Result:
        if Path(command[0]).name == "ruff":
            cwd = kwargs.get("cwd")
            assert cwd is None or isinstance(cwd, str)
            return run(command, cwd=cwd)
        return Result(code=0, out="")

    monkeypatch.setattr(gate, "run", run_ruff)

    assert (
        gate._python_stages(
            tmp_path,
            tmp_path,
            _toolchain(tmp_path, ruff=Path(shutil.which("ruff") or "ruff")),
            fix=True,
        )
        == []
    )
    assert "import os" not in source.read_text(encoding="utf-8")


def test_cli_labels_private_toolchain_failure_without_a_traceback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A cache or launcher failure is an attributable gate finding, not an exception dump."""
    message = "cache is unwritable"

    def unavailable() -> tools.Toolchain:
        raise tools.ToolchainUnavailableError(message)

    monkeypatch.setattr(gate.tools, "ensure", unavailable)

    assert cli.main(["check", str(tmp_path)]) == 1
    assert capsys.readouterr().err == "toolchain: cache is unwritable\n"


def test_vulture_ignores_findings_below_eighty_percent_confidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The dead-code stage accepts only findings backed by sufficient evidence."""
    commands: list[list[str]] = []

    def record(command: list[str], **_kwargs: object) -> Result:
        commands.append(command)
        return Result(code=0, out="")

    monkeypatch.setattr(gate, "run", record)

    assert gate._python_stages(tmp_path, tmp_path, _toolchain(tmp_path), fix=False) == []

    vulture_command = next(command for command in commands if Path(command[0]).name == "vulture")
    assert "--min-confidence" in vulture_command
    assert vulture_command[vulture_command.index("--min-confidence") + 1] == "80"


def test_ruff_runs_from_the_checked_root_with_a_relative_target(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ruff resolves project-relative namespace directories from the checked root."""
    root = tmp_path / "project"
    root.mkdir()
    calls: list[tuple[list[str], str | None]] = []

    def record(command: list[str], **kwargs: object) -> Result:
        cwd = kwargs.get("cwd")
        assert cwd is None or isinstance(cwd, str)
        calls.append((command, cwd))
        return Result(code=0, out="")

    monkeypatch.setattr(gate, "run", record)

    assert gate._python_stages(root, root, _toolchain(tmp_path), fix=False) == []

    ruff_calls = [(command, cwd) for command, cwd in calls if Path(command[0]).name == "ruff"]
    assert all(command[-1] == "." and cwd == str(root) for command, cwd in ruff_calls)


def test_managed_vulture_filters_low_confidence_findings(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The gate keeps Vulture's 90% and 100% findings while dropping a 60% finding."""
    source = tmp_path / "dead_code.py"
    source.write_text(
        "import os\n\n\ndef unused_function():\n    return 1\n\n\ndef reachable():\n    return\n    unreachable = 1\n",
        encoding="utf-8",
    )

    with tools.ensure() as toolchain:

        def run_vulture(command: list[str], **kwargs: object) -> Result:
            if Path(command[0]).name != "vulture":
                return Result(code=0, out="")
            cwd = kwargs.get("cwd")
            assert cwd is None or isinstance(cwd, str)
            return run(command, cwd=cwd)

        monkeypatch.setattr(gate, "run", run_vulture)
        findings = gate._python_stages(tmp_path, tmp_path, toolchain, fix=False)

    assert len(findings) == 1
    detail = findings[0].detail
    assert "unused function 'unused_function' (60% confidence)" not in detail
    assert "unused import 'os' (90% confidence)" in detail
    assert "unreachable code after 'return' (100% confidence)" in detail
