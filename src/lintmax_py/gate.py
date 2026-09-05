# Copyright (c) lintmax-py contributors. Licensed under the MIT License.
from __future__ import annotations

import os
import shlex
from dataclasses import dataclass
from pathlib import Path

import tomllib

from . import config, dprint, rules, staleness, tools
from .paths import SKIP_DIRS, skipped
from .proc import Result, run

DEV_EXTRA_NAMES = frozenset(
    {"dev", "development", "docs", "lint", "test", "testing", "tests", "typing"},
)
"""Extras that name a development role rather than a runtime feature.

An extra is a shipped capability by default — a project declaring `receiver = ["flask"]` means the
receiver imports flask at runtime — so telling the dependency checker that every extra is
development-only makes each of those imports read as misplaced. PEP 735 `[dependency-groups]` is the
mechanism for development dependencies and the checker already recognises it unaided; only the
conventional development EXTRA names are forwarded, for projects that predate that section.
"""

SHELLCHECK_FLAGS = ("--enable=all", "--severity=style", "--external-sources")
SHFMT_FLAGS = ("-s", "-ci", "-bn", "-sr", "-i", "2")
ENV_OPTIONS_WITH_OPERAND = frozenset({"-u", "-C", "-P", "--unset", "--chdir"})
ENV_OPTIONS_WITH_ATTACHED_OPERAND = ("-u", "-C", "-P", "--unset=", "--chdir=")
UNKNOWN_RUFF_SELECTOR = "Unknown rule selector"


@dataclass(frozen=True, slots=True)
class Finding:
    stage: str
    detail: str


def _stage(name: str, res: Result) -> list[Finding]:
    is_ruff_stage = name.startswith("ruff ")
    has_unknown_selector = UNKNOWN_RUFF_SELECTOR in res.out
    if res.code == 0 and not (is_ruff_stage and has_unknown_selector):
        return []
    detail = res.out or f"exit {res.code} with no output"
    return [Finding(stage=name, detail=detail)]


def _python_stages(
    root: Path,
    cfg: Path,
    toolchain: tools.Toolchain,
    *,
    fix: bool,
) -> list[Finding]:
    """Run Python analyzers from the immutable managed toolchain snapshot.

    Returns:
        Findings from Ruff, Ty, and Vulture.

    """
    found: list[Finding] = []
    ruff = toolchain.path("ruff")
    ruff_common = ["--config", str(cfg / "ruff.toml"), "--no-cache"]
    if fix:
        found += _stage(
            "ruff format",
            run([ruff, "format", *ruff_common, "."], cwd=str(root)),
        )
        found += _stage(
            "ruff check",
            run([ruff, "check", "--fix", *ruff_common, "."], cwd=str(root)),
        )
    else:
        found += _stage(
            "ruff format",
            run([ruff, "format", "--check", *ruff_common, "."], cwd=str(root)),
        )
        found += _stage(
            "ruff check",
            run([ruff, "check", *ruff_common, "."], cwd=str(root)),
        )
    project_root = _project_root(root)
    environment, environment_error = _environment(root)
    if environment_error:
        found.append(Finding(stage="ty", detail=environment_error))
    else:
        found += _stage(
            "ty",
            run(
                [
                    toolchain.path("ty"),
                    "check",
                    "--error",
                    "all",
                    "--project",
                    str(project_root),
                    *environment,
                    str(root),
                ],
                cwd=str(project_root),
            ),
        )
    excluded = ",".join(f"*/{name}/*" for name in sorted(SKIP_DIRS))
    allowances = config.vulture_allowances(root)
    vulture_args = [
        toolchain.path("vulture"),
        "--exclude",
        excluded,
        "--min-confidence",
        "80",
    ]
    for key, values in sorted(allowances.items()):
        vulture_args += [f"--{key.replace('_', '-')}", ",".join(values)]
    found += _stage("vulture", run([*vulture_args, str(root)]))
    return found


def _environment(root: Path) -> tuple[list[str], str | None]:
    """Point the type checker at the TARGET project's environment rather than the gate's own.

    A checker resolving imports against whatever venv the gate happens to run from reports every
    third-party import in the project as unresolvable — a wall of findings about the invocation,
    identical in shape to a project with no dependencies installed, and it appears only when the
    gate is run from a different checkout than the one it is checking.

    uv resolves a relative ``UV_PROJECT_ENVIRONMENT`` from the workspace root. The gate discovers
    that root from the checked project instead of inheriting the gate process's current directory.
    An empty setting behaves as unset, so it retains the default workspace ``.venv``.

    Returns:
        The environment flag and no error, or an error for an explicit invalid environment.

    """
    configured = os.environ.get("UV_PROJECT_ENVIRONMENT")
    if configured:
        candidate = Path(configured)
        if candidate.is_absolute():
            venv = candidate
        else:
            workspace_root = _workspace_root(_project_root(root))
            venv = workspace_root / candidate
        venv = venv.resolve()
        if not venv.is_dir():
            return [], f"UV_PROJECT_ENVIRONMENT must name an existing directory: {venv}"
        return ["--python", str(_environment_python(venv))], None
    workspace_root = _workspace_root(_project_root(root))
    venv = workspace_root / ".venv"
    return (["--python", str(_environment_python(venv))], None) if venv.is_dir() else ([], None)


def _environment_python(venv: Path) -> Path:
    """Return the environment's interpreter when it exists, preserving directory-only test fixtures.

    Returns:
        The interpreter executable when the environment contains one, otherwise the environment directory.

    """
    for candidate in (venv / "bin" / "python", venv / "Scripts" / "python.exe"):
        if candidate.is_file():
            return candidate
    return venv


def _project_root(root: Path) -> Path:
    """Return the nearest ancestor declaring a Python project, or the resolved checked directory.

    Both uv and Ty discover project configuration by walking up from a supplied directory. The
    gate must make that discovery before it looks for a workspace or chooses Ty's working directory
    because a source subdirectory is not itself the project whose environment owns its imports.

    Returns:
        The nearest directory with ``pyproject.toml``, or the resolved checked directory.

    """
    target = root.resolve()
    for candidate in (target, *target.parents):
        if (candidate / "pyproject.toml").is_file():
            return candidate
    return target


def _workspace_root(root: Path) -> Path:
    """Return the workspace root that owns ``root``, or ``root`` when it is standalone.

    uv treats the directory declaring ``[tool.uv.workspace]`` as the workspace root, but only
    projects selected by its ``members`` globs inherit that root. A neighboring project outside
    those globs remains standalone even when the gate runs beneath the same repository.

    Returns:
        The matching workspace root, or the resolved checked root when no workspace owns it.

    """
    target = _project_root(root)
    for candidate in (target, *target.parents):
        workspace = _workspace_config(candidate)
        if workspace is not None and _workspace_includes(target, candidate, workspace):
            return candidate
    return target


def _workspace_config(root: Path) -> dict[str, object] | None:
    """Read the workspace declaration from one candidate root, if it has one.

    Returns:
        The declaration with string keys, or nothing when the candidate is not a workspace root.

    """
    try:
        manifest = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return None
    tool = manifest.get("tool")
    if not isinstance(tool, dict):
        return None
    uv = tool.get("uv")
    if not isinstance(uv, dict):
        return None
    workspace = uv.get("workspace")
    if not isinstance(workspace, dict):
        return None
    configuration: dict[str, object] = {key: value for key, value in workspace.items() if isinstance(key, str)}
    return configuration


def _workspace_includes(target: Path, root: Path, workspace: dict[str, object]) -> bool:
    """Return whether one target project is the root or a non-excluded workspace member.

    Returns:
        Whether the workspace owns the target project.

    """
    if target == root:
        return True
    return _matches_workspace_glob(
        target,
        root,
        workspace.get("members"),
    ) and not _matches_workspace_glob(
        target,
        root,
        workspace.get("exclude"),
    )


def _matches_workspace_glob(target: Path, root: Path, patterns: object) -> bool:
    """Match one resolved project directory against uv's workspace member-style path globs.

    Returns:
        Whether any valid glob expands to the target project directory.

    """
    if not isinstance(patterns, list):
        return False
    for pattern in patterns:
        if not isinstance(pattern, str):
            continue
        try:
            candidates = root.glob(pattern)
            if any(candidate.resolve() == target for candidate in candidates):
                return True
        except (NotImplementedError, OSError, ValueError):
            continue
    return False


def _deptry_args(root: Path) -> list[str]:
    """Tell deptry what the project's OWN packages and dev groups are, derived from the project.

    Without them every import of the package under test reads as an undeclared dependency and every
    test-only import of a dev tool reads as a misplaced one — findings about the invocation rather
    than about the tree. The sets come from the manifest and the source layout, never a hand-kept
    list, so a package or group added tomorrow is covered without touching this.

    Returns:
        The arguments deptry is invoked with.

    """
    args: list[str] = ["."]
    packages = sorted(
        {
            entry.name
            for parent in (root, root / "src")
            for entry in (parent.iterdir() if parent.is_dir() else [])
            if entry.is_dir() and (entry / "__init__.py").is_file() and not skipped(entry)
        },
    )
    for name in packages:
        args += ["--known-first-party", name]
    dev_extras = [name for name in _groups(root, "project", "optional-dependencies") if name in DEV_EXTRA_NAMES]
    if dev_extras:
        args += ["--optional-dependencies-dev-groups", ",".join(dev_extras)]
    return args


def _groups(root: Path, *path: str) -> list[str]:
    """Names of the dependency groups at the given manifest path.

    PEP 735 `[dependency-groups]` are recognised as development dependencies without being named,
    so passing them to the flag that reads `[project.optional-dependencies]` finds nothing and
    warns about groups that do not exist there.

    Returns:
        The group names, or nothing when the section is absent.

    """
    try:
        manifest = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return []
    node: object = manifest
    for key in path:
        if not isinstance(node, dict):
            return []
        node = node.get(key)
    return sorted(node) if isinstance(node, dict) else []


def _zsh_script(path: Path) -> bool:
    """Return whether a shell script declares zsh as its interpreter.

    ShellCheck does not support zsh syntax. Treating its parse failure as a shell-quality finding
    makes valid zsh scripts permanently unclean, so the shebang selects zsh's own parser instead.

    Returns:
        Whether ``path`` has a direct or ``env``-resolved zsh shebang.

    """
    try:
        header = path.read_text(encoding="utf-8").splitlines()[0]
    except (IndexError, OSError, UnicodeDecodeError):
        return False
    if not header.startswith("#!"):
        return False
    try:
        parts = shlex.split(header[2:].strip())
    except ValueError:
        return False
    if not parts:
        return False
    interpreter = parts[0].rsplit("/", maxsplit=1)[-1]
    if interpreter == "env":
        interpreter = _env_interpreter(parts[1:])
    return interpreter == "zsh"


def _env_interpreter(args: list[str]) -> str:
    """Extract the command selected by an ``env`` shebang without mistaking option data for it.

    ``env -u NAME``, ``env -C DIRECTORY`` and macOS ``env -P PATH`` consume their next token.
    Treating that token as an interpreter routes valid zsh scripts through ShellCheck, which cannot
    parse them. ``-S`` introduces a second argv string, so parse it with the same option rules
    before classifying the command.

    Returns:
        The selected command name, or an empty string when the shebang has no command.

    """
    index = 0
    while index < len(args):
        arg = args[index]
        if arg == "--":
            index += 1
            break
        if arg in {"-S", "--split-string"}:
            if index + 1 == len(args):
                return ""
            return _split_env_interpreter(args[index + 1], args[index + 2 :])
        if arg.startswith("--split-string="):
            return _split_env_interpreter(arg.partition("=")[2], args[index + 1 :])
        if arg in ENV_OPTIONS_WITH_OPERAND:
            index += 2
            continue
        if any(arg.startswith(prefix) and arg != prefix for prefix in ENV_OPTIONS_WITH_ATTACHED_OPERAND):
            index += 1
            continue
        if arg.startswith("-") or "=" in arg:
            index += 1
            continue
        return arg.rsplit("/", maxsplit=1)[-1]
    if index < len(args):
        return args[index].rsplit("/", maxsplit=1)[-1]
    return ""


def _split_env_interpreter(spec: str, trailing: list[str]) -> str:
    """Parse the command string that ``env -S`` injects into its argv.

    Returns:
        The interpreter selected by the split argv, or an empty string when the value is malformed.

    """
    try:
        split_args = shlex.split(spec)
    except ValueError:
        return ""
    return _env_interpreter([*split_args, *trailing])


def _repo_stages(
    root: Path,
    cfg: Path,
    toolchain: tools.Toolchain,
    *,
    fix: bool,
) -> list[Finding]:
    """Run repository-wide analyzers from the immutable managed toolchain snapshot.

    Returns:
        Findings from formatting, spelling, shell, dependency, and audit stages.

    """
    found: list[Finding] = []
    dprint_config = cfg / "dprint.json"
    dprint_executable = toolchain.path("dprint")
    dprint_args = [
        dprint_executable,
        "fmt" if fix else "check",
        "--config",
        str(dprint_config),
        "--excludes",
        dprint.MARKDOWN_GLOB,
        "--allow-no-files",
    ]
    found += _stage("dprint", run(dprint_args, cwd=str(root)))
    found += [
        Finding(stage="markdown", detail=detail)
        for detail in dprint.sweep(root, dprint_config, dprint_executable, fix=fix)
    ]
    found += _stage(
        "typos",
        run([toolchain.path("typos"), "--config", str(cfg / "typos.toml"), str(root)]),
    )
    scripts = [
        str(path)
        for path in sorted(root.rglob("*.sh"))
        if not any(part in {".venv", ".git", "node_modules"} for part in path.parts)
    ]
    zsh_scripts = [script for script in scripts if _zsh_script(Path(script))]
    shellcheck_scripts = [script for script in scripts if script not in zsh_scripts]
    if shellcheck_scripts:
        shfmt = [
            toolchain.path("shfmt"),
            "-w" if fix else "-d",
            *SHFMT_FLAGS,
            *shellcheck_scripts,
        ]
        found += _stage("shfmt", run(shfmt))
        found += _stage(
            "shellcheck",
            run([toolchain.path("shellcheck"), *SHELLCHECK_FLAGS, *shellcheck_scripts]),
        )
    if zsh_scripts and toolchain.zsh is None:
        found.append(Finding(stage="zsh", detail="zsh: not installed"))
    for script in zsh_scripts:
        if toolchain.zsh is not None:
            found += _stage("zsh", run([str(toolchain.zsh), "-n", script]))
    if (root / "pyproject.toml").is_file():
        found += _stage(
            "deptry",
            run([toolchain.path("deptry"), *_deptry_args(root)], cwd=str(root)),
        )
        found += _stage(
            "pip-audit",
            run(
                [toolchain.path("pip-audit"), "--progress-spinner", "off"],
                cwd=str(root),
            ),
        )
    return found


def _staleness_stages(root: Path, toolchain: tools.Toolchain) -> list[Finding]:
    """Return upgrade findings or the resolver failure that prevents a staleness verdict.

    Returns:
        Staleness findings, including a resolver failure when evidence cannot be produced.

    """
    try:
        return [Finding(stage="staleness", detail=detail) for detail in staleness.behind(root, toolchain.uv_command())]
    except staleness.ResolutionUnavailableError as error:
        return [Finding(stage="staleness", detail=str(error))]
    except tools.ToolchainUnavailableError as error:
        return [Finding(stage="toolchain", detail=str(error))]


def run_gate(root: Path, *, fix: bool) -> list[Finding]:
    try:
        project = config.project_configuration(root)
    except config.ProjectConfigurationError as error:
        return [Finding(stage="config", detail=str(error))]
    try:
        toolchain = tools.ensure()
    except tools.ToolchainUnavailableError as error:
        return [Finding(stage="toolchain", detail=str(error))]
    with toolchain:
        inventory = rules.inventory(toolchain.tool("ruff"))
        try:
            cfg, _digest = config.materialize(inventory, root, project)
        except config.ProjectConfigurationError as error:
            return [Finding(stage="config", detail=str(error))]

        findings = _python_stages(root, cfg, toolchain, fix=fix)
        findings += _repo_stages(root, cfg, toolchain, fix=fix)
        findings += _staleness_stages(root, toolchain)
        return findings


def rules_text() -> str:
    with tools.ensure() as toolchain:
        inventory = rules.inventory(toolchain.tool("ruff"))
        active = [
            f"{tool.executable} {tool.version} at {tool.path}"
            for tool in sorted(
                toolchain.tools.values(),
                key=lambda current: current.executable,
            )
        ]
        return rules.summary(inventory) + "\nactive tools: " + ", ".join(active)
