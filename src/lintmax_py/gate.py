# Copyright (c) lintmax-py contributors. Licensed under the MIT License.
from __future__ import annotations

import shlex
from dataclasses import dataclass
from pathlib import Path

import tomllib

from . import comments, config, dprint, rules, staleness, tools
from .paths import SKIP_DIRS, skipped
from .proc import Result, have, run

DEV_EXTRA_NAMES = frozenset({"dev", "development", "docs", "lint", "test", "testing", "tests", "typing"})
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


@dataclass(frozen=True, slots=True)
class Finding:
    stage: str
    detail: str


def _stage(name: str, res: Result) -> list[Finding]:
    if res.code == 0:
        return []
    detail = res.out or f"exit {res.code} with no output"
    return [Finding(stage=name, detail=detail)]


def _python_stages(root: Path, cfg: Path, *, fix: bool) -> list[Finding]:
    found: list[Finding] = []
    ruff_common = ["--config", str(cfg / "ruff.toml"), "--no-cache"]
    if fix:
        found += _stage("ruff format", run(["ruff", "format", *ruff_common, str(root)]))
        found += _stage(
            "ruff check",
            run(["ruff", "check", "--fix", "--unsafe-fixes", *ruff_common, str(root)]),
        )
    else:
        found += _stage("ruff format", run(["ruff", "format", "--check", *ruff_common, str(root)]))
        found += _stage("ruff check", run(["ruff", "check", *ruff_common, str(root)]))
    found += _stage("ty", run(["ty", "check", "--error", "all", *_environment(root), str(root)]))
    excluded = ",".join(f"*/{name}/*" for name in sorted(SKIP_DIRS))
    allowances = config.vulture_allowances(root)
    vulture_args = ["vulture", "--exclude", excluded]
    for key, values in sorted(allowances.items()):
        vulture_args += [f"--{key.replace('_', '-')}", ",".join(values)]
    found += _stage("vulture", run([*vulture_args, str(root)]))
    return found


def _environment(root: Path) -> list[str]:
    """Point the type checker at the TARGET project's environment rather than the gate's own.

    A checker resolving imports against whatever venv the gate happens to run from reports every
    third-party import in the project as unresolvable — a wall of findings about the invocation,
    identical in shape to a project with no dependencies installed, and it appears only when the
    gate is run from a different checkout than the one it is checking.

    Returns:
        The environment flag, or nothing when the project has no environment of its own.

    """
    venv = root / ".venv"
    return ["--python", str(venv)] if venv.is_dir() else []


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
    packages = sorted({
        entry.name
        for parent in (root, root / "src")
        for entry in (parent.iterdir() if parent.is_dir() else [])
        if entry.is_dir() and (entry / "__init__.py").is_file() and not skipped(entry)
    })
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


def _repo_stages(root: Path, cfg: Path, *, fix: bool) -> list[Finding]:
    found: list[Finding] = []
    dprint_config = cfg / "dprint.json"
    dprint_args = [
        "dprint",
        "fmt" if fix else "check",
        "--config",
        str(dprint_config),
        "--excludes",
        dprint.MARKDOWN_GLOB,
        "--allow-no-files",
    ]
    found += _stage("dprint", run(dprint_args, cwd=str(root)))
    found += [Finding(stage="markdown", detail=d) for d in dprint.sweep(root, dprint_config, fix=fix)]
    found += _stage("typos", run(["typos", "--config", str(cfg / "typos.toml"), str(root)]))
    scripts = [
        str(p)
        for p in sorted(root.rglob("*.sh"))
        if not any(part in {".venv", ".git", "node_modules"} for part in p.parts)
    ]
    zsh_scripts = [script for script in scripts if _zsh_script(Path(script))]
    shellcheck_scripts = [script for script in scripts if script not in zsh_scripts]
    if shellcheck_scripts:
        shfmt = ["shfmt", "-w" if fix else "-d", *SHFMT_FLAGS, *shellcheck_scripts]
        found += _stage("shfmt", run(shfmt))
        found += _stage("shellcheck", run(["shellcheck", *SHELLCHECK_FLAGS, *shellcheck_scripts]))
    for script in zsh_scripts:
        found += _stage("zsh", run(["zsh", "-n", script]))
    if (root / "pyproject.toml").is_file():
        found += _stage("deptry", run(["deptry", *_deptry_args(root)], cwd=str(root)))
        found += _stage("pip-audit", run(["pip-audit", "--progress-spinner", "off"], cwd=str(root)))
    return found


def _staleness_stages(root: Path) -> list[Finding]:
    """Return upgrade findings or the resolver failure that prevents a staleness verdict.

    The staleness probe is an evidence-producing gate stage. A failed resolver cannot establish
    that the tree is current, so surface its unaltered diagnostic as a failing finding instead of
    treating the absence of upgrade lines as a pass.

    Returns:
        The direct upgrades found, or one diagnostic when uv could not resolve them.

    """
    try:
        return [Finding(stage="staleness", detail=detail) for detail in staleness.behind(root)]
    except staleness.ResolutionUnavailableError as error:
        return [Finding(stage="staleness", detail=str(error))]


def run_gate(root: Path, *, fix: bool) -> list[Finding]:
    missing = tools.ensure()
    findings = [Finding(stage="toolchain", detail=m) for m in missing]
    inventory = rules.inventory()
    cfg, _digest = config.materialize(inventory, root)

    if fix:
        comments.strip_tree(root)
    else:
        findings += [
            Finding(stage="comments", detail=f"{path}: strippable comment (run fix)") for path in comments.offenders(root)
        ]

    findings += _python_stages(root, cfg, fix=fix)
    findings += _repo_stages(root, cfg, fix=fix)
    findings += _staleness_stages(root)

    return findings


def rules_text() -> str:
    inventory = rules.inventory()
    extra = [t for t in tools.executables() if have(t)]
    return rules.summary(inventory) + "\nactive tools: " + ", ".join(extra)
