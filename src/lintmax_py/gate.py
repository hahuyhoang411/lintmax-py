# Copyright (c) lintmax-py contributors. Licensed under the MIT License.
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from . import comments, config, rules, tools
from .proc import Result, have, run

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
    found += _stage("ty", run(["ty", "check", "--error", "all", str(root)]))
    found += _stage("vulture", run(["vulture", str(root)]))
    return found


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
        found += _stage("shellcheck", run(["shellcheck", "--severity=style", *scripts]))
        shfmt = ["shfmt", "-w" if fix else "-d", "-i", "2", "-ci", *scripts]
        found += _stage("shfmt", run(shfmt))
    if (root / "pyproject.toml").is_file():
        found += _stage("deptry", run(["deptry", str(root)]))
        found += _stage("pip-audit", run(["pip-audit", "--progress-spinner", "off"], cwd=str(root)))
    return found


def run_gate(root: Path, *, fix: bool) -> list[Finding]:
    missing = tools.ensure()
    findings = [Finding(stage="toolchain", detail=m) for m in missing]
    inventory = rules.inventory()
    cfg, _digest = config.materialize(inventory)

    if fix:
        comments.strip_tree(root)
    else:
        findings += [
            Finding(stage="comments", detail=f"{path}: strippable comment (run fix)") for path in comments.offenders(root)
        ]

    findings += _python_stages(root, cfg, fix=fix)
    findings += _repo_stages(root, cfg, fix=fix)

    return findings


def rules_text() -> str:
    inventory = rules.inventory()
    extra = [t for t in (*tools.UV_TOOLS, *tools.NATIVE_TOOLS) if have(t)]
    return rules.summary(inventory) + "\nactive tools: " + ", ".join(extra)
