# Copyright (c) lintmax-py contributors. Licensed under the MIT License.
"""The managed toolchain rejects mutable or PATH-selected analyzer launchers."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from lintmax_py import cli, dprint, gate, rules, tools
from lintmax_py.proc import Result, run

INSTALL_FAILURE = "install failed"
STAMP_FAILURE = "refresh stamp failed"
SECONDARY_CLEANUP_FAILURE = "unpublished generation cleanup failed"


def _executable(path: Path, version: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"#!/bin/sh\necho {version!r}\n", encoding="utf-8")
    path.chmod(0o755)


def _uvx() -> tools.UvxLauncher:
    path = Path(shutil.which("uvx") or "/opt/homebrew/bin/uvx").resolve()
    metadata = path.stat()
    version = run([str(path), "--version"]).out.splitlines()[0]
    return tools.UvxLauncher(path, metadata.st_dev, metadata.st_ino, version)


def _generation(root: Path, identifier: str = "0123456789abcdef0123456789abcdef") -> Path:
    generation = root / f"generation-{identifier}"
    for package, executable in tools.TOOLS.items():
        managed = generation / "tools" / package / "bin" / executable
        _executable(managed, f"{executable} managed")
        launcher = generation / "bin" / executable
        launcher.parent.mkdir(parents=True, exist_ok=True)
        launcher.symlink_to(managed)
    return generation


def _snapshot(generation: Path) -> tools.Toolchain:
    selected = {
        executable: tools.Tool(
            package=package,
            executable=executable,
            path=(generation / "bin" / executable).resolve(),
            version=f"{executable} managed",
        )
        for package, executable in tools.TOOLS.items()
    }
    return tools.Toolchain(
        tools=selected,
        generation=generation,
        uvx=_uvx(),
        zsh=None,
    )


def test_clean_private_bootstrap_installs_into_a_generation_and_publishes_atomically(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A clean cache installs every tool under a private unpublished generation before current moves."""
    root = tmp_path / "cache"
    uvx = _uvx()
    commands: list[tuple[list[str], dict[str, str] | None]] = []

    def fake_capture() -> tools.UvxLauncher:
        return uvx

    def fake_run(command: list[str], **kwargs: object) -> Result:
        environment = kwargs.get("env")
        assert environment is None or isinstance(environment, dict)
        commands.append((command, environment))
        if command == [str(uvx.path), "--version"]:
            return Result(0, uvx.version)
        if command[2:4] == ["tool", "install"]:
            assert environment is not None
            generation = Path(environment["UV_TOOL_BIN_DIR"]).parent
            package = command[-1].partition("@")[0]
            executable = tools.TOOLS[package]
            managed = generation / "tools" / package / "bin" / executable
            _executable(managed, f"{executable} managed")
            launcher = generation / "bin" / executable
            launcher.parent.mkdir(parents=True, exist_ok=True)
            launcher.symlink_to(managed)
            return Result(0, "installed")
        if command[-1] == "--version":
            return Result(0, "managed 1.0")
        message = f"unexpected command: {command}"
        raise AssertionError(message)

    monkeypatch.setattr(tools, "cache_root", lambda: root)
    monkeypatch.setattr(tools, "_capture_uvx", fake_capture)
    monkeypatch.setattr(tools, "run", fake_run)
    monkeypatch.setattr(tools, "fresh", lambda: False)
    monkeypatch.setattr(tools, "mark", lambda: None)

    snapshot = tools.ensure()

    assert snapshot.generation.parent == root
    assert (root / "current").read_text(encoding="utf-8") == snapshot.generation.name
    assert all(tool.path.is_absolute() for tool in snapshot.tools.values())
    installs = [command for command, _env in commands if command[2:4] == ["tool", "install"]]
    assert len(installs) == len(tools.TOOLS)
    assert all(command[:2] == [str(uvx.path), tools.UV_VERSION] for command in installs)
    assert all(
        environment is not None and environment["UV_TOOL_BIN_DIR"].startswith(str(snapshot.generation))
        for command, environment in commands
        if command in installs
    )


def test_spoofed_generation_launcher_is_rejected_before_a_path_tool_can_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A launcher symlink leaving the private generation fails closed even when PATH has that name."""
    generation = tmp_path / "generation-spoofed"
    path_bin = tmp_path / "path"
    _executable(path_bin / "ruff", "ruff PATH")
    monkeypatch.setenv("PATH", str(path_bin))
    (generation / "bin").mkdir(parents=True)
    (generation / "bin" / "ruff").symlink_to(path_bin / "ruff")

    with pytest.raises(tools.ToolchainUnavailableError, match="outside managed package"):
        tools._version("ruff", "ruff", generation)


def test_missing_managed_launcher_fails_closed_even_when_path_has_the_tool(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """PATH is not a fallback when the selected generation omitted its expected launcher."""
    generation = tmp_path / "generation-missing"
    path_bin = tmp_path / "path"
    _executable(path_bin / "ruff", "ruff PATH")
    monkeypatch.setenv("PATH", str(path_bin))

    with pytest.raises(tools.ToolchainUnavailableError, match="cannot resolve managed executable"):
        tools._version("ruff", "ruff", generation)


def test_managed_launcher_cannot_resolve_to_another_package_in_the_same_generation(
    tmp_path: Path,
) -> None:
    """A valid sibling package executable is not provenance for the declared package."""
    generation = _generation(tmp_path)
    launcher = generation / "bin" / "ruff"
    launcher.unlink()
    launcher.symlink_to(generation / "tools" / "ty" / "bin" / "ty")

    with pytest.raises(tools.ToolchainUnavailableError, match="managed package 'ruff'"):
        tools._version("ruff", "ruff", generation)


def test_existing_snapshot_keeps_resolved_ruff_after_current_pointer_and_bin_symlink_change(
    tmp_path: Path,
) -> None:
    """A concurrent publish or launcher swap cannot alter the executable held by an existing gate."""
    first = _generation(tmp_path / "first")
    snapshot = _snapshot(first)
    original = snapshot.path("ruff")
    second = _generation(tmp_path / "second")
    pointer = tmp_path / "current"
    pointer.write_text(second.name, encoding="utf-8")
    launcher = first / "bin" / "ruff"
    launcher.unlink()
    launcher.symlink_to(second / "bin" / "ruff")

    assert snapshot.path("ruff") == original
    assert Path(snapshot.path("ruff")).read_text(encoding="utf-8") == "#!/bin/sh\necho 'ruff managed'\n"


def test_windows_fails_before_the_cache_or_uvx_can_be_used(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(tools, "fcntl", None)

    with pytest.raises(tools.ToolchainUnavailableError, match="require Unix file locking"):
        tools.ensure()


def test_missing_system_zsh_is_an_explicit_supported_platform_exception(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    generation = _generation(tmp_path)
    path_bin = tmp_path / "path"
    _executable(path_bin / "zsh", "zsh PATH")
    monkeypatch.setenv("PATH", str(path_bin))
    monkeypatch.setattr(tools, "SYSTEM_ZSH", tmp_path / "no-zsh")
    snapshot = tools._snapshot(_uvx(), generation)
    assert snapshot.zsh is None


def test_unwritable_private_cache_fails_closed_as_a_toolchain_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A cache root that cannot become a directory must never fall back to global tool bins."""
    cache_file = tmp_path / "cache-file"
    cache_file.write_text("not a directory", encoding="utf-8")
    monkeypatch.setattr(tools, "cache_root", lambda: cache_file)

    with pytest.raises(tools.ToolchainUnavailableError, match="cannot create"):
        tools.ensure()


def test_staleness_rejects_a_changed_uvx_launcher_before_running_uv(
    tmp_path: Path,
) -> None:
    launcher = tmp_path / "uvx"
    _executable(launcher, "uv 0.12.3")
    original = launcher.stat()
    captured = tools.UvxLauncher(launcher, original.st_dev, original.st_ino, "uv 0.12.3")
    launcher.unlink()
    _executable(launcher, "uv 99")
    snapshot = _snapshot(_generation(tmp_path / "generation"))
    snapshot = tools.Toolchain(snapshot.tools, snapshot.generation, captured, None)

    with pytest.raises(tools.ToolchainUnavailableError, match="changed after toolchain snapshot"):
        snapshot.uv_command()


def test_install_revalidates_the_captured_uvx_before_invoking_the_installer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Replacing uvx after capture rejects installation before a replacement can run."""
    launcher = tmp_path / "uvx"
    _executable(launcher, "uv 0.12.3")
    metadata = launcher.stat()
    captured = tools.UvxLauncher(launcher, metadata.st_dev, metadata.st_ino, "uv 0.12.3")
    launcher.unlink()
    _executable(launcher, "uv 99")
    commands: list[list[str]] = []
    monkeypatch.setattr(
        tools,
        "run",
        lambda command, **_kwargs: commands.append(command) or Result(0, ""),
    )

    with pytest.raises(tools.ToolchainUnavailableError, match="changed after toolchain snapshot"):
        tools._install(captured, "ruff", tmp_path / "generation")

    assert commands == []


def test_install_checks_the_captured_uvx_immediately_before_each_install(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    launcher = tmp_path / "uvx"
    _executable(launcher, "uv 0.12.3")
    metadata = launcher.stat()
    captured = tools.UvxLauncher(launcher, metadata.st_dev, metadata.st_ino, "uv 0.12.3")
    commands: list[list[str]] = []

    def fake_run(command: list[str], **_kwargs: object) -> Result:
        commands.append(command)
        if command == [str(launcher), "--version"]:
            return Result(0, "uv 0.12.3")
        return Result(0, "installed")

    monkeypatch.setattr(tools, "run", fake_run)

    tools._install(captured, "ruff", tmp_path / "generation")

    assert commands == [
        [str(launcher), "--version"],
        [
            str(launcher),
            tools.UV_VERSION,
            "tool",
            "install",
            "--force",
            "--quiet",
            "ruff@latest",
        ],
    ]


def test_reaper_keeps_an_active_old_generation_then_removes_it_after_release(
    tmp_path: Path,
) -> None:
    """A gate lease blocks garbage collection until that invocation closes it."""
    root = tmp_path / "cache"
    old = _generation(root, "1" * 32)
    current = _generation(root, "2" * 32)
    old_snapshot = tools._snapshot(_uvx(), old)
    current_snapshot = tools._snapshot(_uvx(), current)
    tools._publish(root, old)
    tools._publish(root, current)

    tools._reap_generations(root, current)
    assert old.exists()
    assert current.exists()

    old_snapshot.close()
    tools._reap_generations(root, current)

    assert not old.exists()
    assert current.exists()
    current_snapshot.close()


def test_reaper_bounds_repeated_refreshes_to_the_current_generation(
    tmp_path: Path,
) -> None:
    """A completed gate does not leave one whole private toolchain per refresh."""
    root = tmp_path / "cache"
    latest: Path | None = None
    for identifier in ("1" * 32, "2" * 32, "3" * 32):
        latest = _generation(root, identifier)
        snapshot = tools._snapshot(_uvx(), latest)
        tools._publish(root, latest)
        snapshot.close()
        tools._reap_generations(root, latest)

    assert latest is not None
    assert sorted(path.name for path in root.glob("generation-*")) == [latest.name]


def test_failed_bootstrap_removes_the_unpublished_generation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A partial install cannot accumulate an unreachable multi-tool generation."""
    root = tmp_path / "cache"
    root.mkdir()
    uvx = _uvx()

    def fail_install(_uvx: tools.UvxLauncher, _package: str, _generation: Path) -> None:
        raise tools.ToolchainUnavailableError(INSTALL_FAILURE)

    monkeypatch.setattr(tools, "_install", fail_install)

    with pytest.raises(tools.ToolchainUnavailableError, match=INSTALL_FAILURE):
        tools._bootstrap(uvx, root)

    assert list(root.glob("generation-*")) == []


@pytest.mark.parametrize(
    "secondary_type",
    [RuntimeError, KeyboardInterrupt, SystemExit],
)
def test_primary_install_failure_survives_any_unpublished_generation_cleanup_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    secondary_type: type[BaseException],
) -> None:
    """Cleanup evidence never replaces the causal install failure, including control flow."""
    root = tmp_path / "cache"
    root.mkdir()
    primary = tools.ToolchainUnavailableError(INSTALL_FAILURE)
    secondary = secondary_type(SECONDARY_CLEANUP_FAILURE)

    def fail_install(_uvx: tools.UvxLauncher, _package: str, _generation: Path) -> None:
        raise primary

    def fail_cleanup(_generation: Path) -> None:
        raise secondary

    monkeypatch.setattr(tools, "_install", fail_install)
    monkeypatch.setattr(tools, "_remove_generation", fail_cleanup)

    with pytest.raises(tools.ToolchainUnavailableError) as raised:
        tools._bootstrap(_uvx(), root)

    assert raised.value is primary
    assert any(SECONDARY_CLEANUP_FAILURE in note for note in primary.__notes__)


def test_repeated_refresh_stamp_failures_reap_every_unleased_superseded_generation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failing refresh stamp cannot make the private generation cache grow without bound."""
    root = tmp_path / "cache"
    uvx = _uvx()
    identifiers = iter(("1" * 32, "2" * 32, "3" * 32))

    def bootstrap(_uvx: tools.UvxLauncher, _root: Path) -> tools.Toolchain:
        return tools._snapshot(uvx, _generation(root, next(identifiers)))

    def fail_mark() -> None:
        raise tools.ToolchainUnavailableError(STAMP_FAILURE)

    monkeypatch.setattr(tools, "cache_root", lambda: root)
    monkeypatch.setattr(tools, "_capture_uvx", lambda: uvx)
    monkeypatch.setattr(tools, "_bootstrap", bootstrap)
    monkeypatch.setattr(tools, "fresh", lambda: False)
    monkeypatch.setattr(tools, "mark", fail_mark)

    for identifier in ("1" * 32, "2" * 32, "3" * 32):
        with pytest.raises(tools.ToolchainUnavailableError, match=STAMP_FAILURE):
            tools.ensure()
        assert (root / "current").read_text(encoding="utf-8") == f"generation-{identifier}"
        assert sorted(path.name for path in root.glob("generation-*")) == [f"generation-{identifier}"]


def test_refresh_stamp_failure_survives_a_generation_lease_release_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The stamp failure remains causal even when releasing its published lease also fails."""
    root = tmp_path / "cache"
    uvx = _uvx()
    snapshot = tools._snapshot(uvx, _generation(root))
    primary = tools.ToolchainUnavailableError(STAMP_FAILURE)
    secondary = tools.ToolchainUnavailableError(SECONDARY_CLEANUP_FAILURE)

    def fail_mark() -> None:
        raise primary

    def fail_close(_toolchain: tools.Toolchain) -> None:
        raise secondary

    monkeypatch.setattr(tools, "cache_root", lambda: root)
    monkeypatch.setattr(tools, "_capture_uvx", lambda: uvx)
    monkeypatch.setattr(tools, "_bootstrap", lambda _uvx, _root: snapshot)
    monkeypatch.setattr(tools, "fresh", lambda: False)
    monkeypatch.setattr(tools, "mark", fail_mark)
    monkeypatch.setattr(tools.Toolchain, "close", fail_close)

    with pytest.raises(tools.ToolchainUnavailableError) as raised:
        tools.ensure()

    assert raised.value is primary
    assert any(SECONDARY_CLEANUP_FAILURE in note for note in primary.__notes__)


def test_dprint_markdown_enumeration_failure_is_a_finding_after_primary_success(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    executable = str(tmp_path / "dprint")
    calls: list[list[str]] = []

    def fake_run(command: list[str], **_kwargs: object) -> Result:
        calls.append(command)
        return Result(2, "dprint list failure")

    monkeypatch.setattr(dprint, "run", fake_run)

    assert dprint.sweep(tmp_path, tmp_path / "dprint.json", executable, fix=False) == [
        "dprint output-file-paths failed: dprint list failure",
    ]
    assert calls == [
        [
            executable,
            "output-file-paths",
            "--config",
            str(tmp_path / "dprint.json"),
            dprint.MARKDOWN_GLOB,
        ],
    ]


def test_repo_gate_reports_markdown_enumeration_failure_after_dprint_primary_passes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The primary dprint pass cannot hide a failed authoritative markdown enumeration."""
    snapshot = _snapshot(_generation(tmp_path / "managed"))
    primary_calls: list[list[str]] = []

    def primary_success(command: list[str], **_kwargs: object) -> Result:
        primary_calls.append(command)
        return Result(0, "")

    monkeypatch.setattr(gate, "run", primary_success)
    monkeypatch.setattr(dprint, "run", lambda *_args, **_kwargs: Result(2, "list failed"))

    findings = gate._repo_stages(tmp_path, tmp_path, snapshot, fix=False)

    assert primary_calls[0][:2] == [snapshot.path("dprint"), "check"]
    assert findings == [
        gate.Finding("markdown", "dprint output-file-paths failed: list failed"),
    ]


def test_python_stages_ignore_conflicting_path_ruff_and_ty(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The gate invokes only paths captured from its generation, not same-named PATH binaries."""
    snapshot = _snapshot(_generation(tmp_path / "managed"))
    path_bin = tmp_path / "path"
    _executable(path_bin / "ruff", "ruff PATH")
    _executable(path_bin / "ty", "ty PATH")
    monkeypatch.setenv("PATH", str(path_bin))
    calls: list[list[str]] = []

    def fake_run(command: list[str], **_kwargs: object) -> Result:
        calls.append(command)
        return Result(0, "")

    monkeypatch.setattr(gate, "run", fake_run)
    monkeypatch.setattr(gate, "_environment", lambda _root: ([], None))
    monkeypatch.setattr(gate.config, "vulture_allowances", lambda _root: {})

    assert gate._python_stages(tmp_path, tmp_path, snapshot, fix=False) == []
    assert calls[0][0] == snapshot.path("ruff")
    assert calls[1][0] == snapshot.path("ruff")
    assert calls[2][0] == snapshot.path("ty")
    assert all(call[0] not in {str(path_bin / "ruff"), str(path_bin / "ty")} for call in calls)


def test_gate_uses_one_snapshot_without_another_install_or_network_probe(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Inventory, config, and stages consume one captured generation."""
    snapshot = tools._snapshot(_uvx(), _generation(tmp_path))
    inventory = rules.RuffInventory(snapshot.path("ruff"), "ruff managed", ())
    ensures = 0

    def one_snapshot() -> tools.Toolchain:
        nonlocal ensures
        ensures += 1
        return snapshot

    monkeypatch.setattr(gate.tools, "ensure", one_snapshot)
    monkeypatch.setattr(gate.rules, "inventory", lambda _ruff: inventory)
    monkeypatch.setattr(gate.config, "materialize", lambda *_args: (tmp_path, "digest"))
    monkeypatch.setattr(gate, "_python_stages", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(gate, "_repo_stages", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(gate, "_staleness_stages", lambda *_args, **_kwargs: [])

    assert gate.run_gate(tmp_path, fix=False) == []
    assert ensures == 1
    assert snapshot.lease is not None
    assert snapshot.lease.handle.closed


def test_rules_command_releases_its_generation_lease_when_inventory_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The command boundary releases a live generation after a failing inventory check."""
    snapshot = tools._snapshot(_uvx(), _generation(tmp_path))
    message = "synthetic inventory failure"

    def unavailable(_ruff: tools.Tool) -> rules.RuffInventory:
        raise rules.RuffInventoryUnavailableError(message)

    monkeypatch.setattr(gate.tools, "ensure", lambda: snapshot)
    monkeypatch.setattr(gate.rules, "inventory", unavailable)

    assert cli.main(["rules"]) == 1
    assert snapshot.lease is not None
    assert snapshot.lease.handle.closed
