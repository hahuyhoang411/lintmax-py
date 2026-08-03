# Copyright (c) lintmax-py contributors. Licensed under the MIT License.
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__
from .gate import rules_text, run_gate

COMMANDS = ("fix", "check", "version", "rules")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="lintmax-py", description="maximum-strictness python gate")
    parser.add_argument("command", nargs="?", default="fix", choices=COMMANDS)
    parser.add_argument("path", nargs="?", default=".")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv if argv is not None else sys.argv[1:])
    if args.command == "version":
        sys.stdout.write(f"{__version__}\n")
        return 0
    if args.command == "rules":
        sys.stdout.write(rules_text() + "\n")
        return 0

    root = Path(args.path).resolve()
    if not root.is_dir():
        sys.stderr.write(f"not a directory: {root}\n")
        return 2

    findings = run_gate(root, fix=args.command == "fix")
    if not findings:
        sys.stdout.write("ok\n")
        return 0
    for finding in findings:
        sys.stderr.write(f"{finding.stage}: {finding.detail}\n")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
