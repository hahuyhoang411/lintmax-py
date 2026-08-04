# Copyright (c) lintmax-py contributors. Licensed under the MIT License.
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import tomllib

from . import comments, config, rules, staleness, tools
from .paths import SKIP_DIRS, skipped
from .proc import Result, have, run

SHELLCHECK_FLAGS = ("--enable=all", "--severity=style", "--external-sources")
SHFMT_FLAGS = ("-s", "-ci", "-bn", "-sr", "-i", "2")

if TYPE_CHECKING:
    from pathlib import Path


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
    found += _stage("vulture", run(["vulture", "--exclude", excluded, str(root)]))
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
    args = ["."]
    packages = sorted({
        entry.name
        for parent in (root, root / "src")
        for entry in (parent.iterdir() if parent.is_dir() else [])
        if entry.is_dir() and (entry / "__init__.py").is_file() and not skipped(entry)
    })
    for name in packages:
        args += ["--known-first-party", name]
    optional = _groups(root, "project", "optional-dependencies")
    if optional:
        args += ["--optional-dependencies-dev-groups", ",".join(optional)]
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


def _repo_stages(root: Path, cfg: Path, *, fix: bool) -> list[Finding]:
    found: list[Finding] = []
    dprint_args = ["dprint", "fmt" if fix else "check", "--config", str(cfg / "dprint.json")]
    found += _stage("dprint", run(dprint_args, cwd=str(root)))
    found += _stage("typos", run(["typos", "--config", str(cfg / "typos.toml"), str(root)]))
    scripts = [
        str(p)
        for p in sorted(root.rglob("*.sh"))
        if not any(part in {".venv", ".git", "node_modules"} for part in p.parts)
    ]
    if scripts:
        shfmt = ["shfmt", "-w" if fix else "-d", *SHFMT_FLAGS, *scripts]
        found += _stage("shfmt", run(shfmt))
        found += _stage("shellcheck", run(["shellcheck", *SHELLCHECK_FLAGS, *scripts]))
    if (root / "pyproject.toml").is_file():
        found += _stage("deptry", run(["deptry", *_deptry_args(root)], cwd=str(root)))
        found += _stage("pip-audit", run(["pip-audit", "--progress-spinner", "off"], cwd=str(root)))
    return found


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
    findings += [Finding(stage="staleness", detail=d) for d in staleness.behind(root)]

    return findings


def rules_text() -> str:
    inventory = rules.inventory()
    extra = [t for t in tools.executables() if have(t)]
    return rules.summary(inventory) + "\nactive tools: " + ", ".join(extra)
