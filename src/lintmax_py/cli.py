# Copyright (c) lintmax-py contributors. Licensed under the MIT License.
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__
from .gate import rules_text, run_gate
from .rules import RuffInventoryUnavailableError

COMMANDS = ("fix", "check", "version", "rules")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="lintmax-py",
        description="maximum-strictness python gate",
    )
    parser.add_argument("command", nargs="?", default="fix", choices=COMMANDS)
    parser.add_argument("path", nargs="?", default=".")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv if argv is not None else sys.argv[1:])
    exit_code = 0
    if args.command == "version":
        sys.stdout.write(f"{__version__}\n")
    elif args.command == "rules":
        try:
            sys.stdout.write(rules_text() + "\n")
        except RuffInventoryUnavailableError as error:
            sys.stderr.write(f"ruff-inventory: {error}\n")
            exit_code = 1
    else:
        root = Path(args.path).resolve()
        if not root.is_dir():
            sys.stderr.write(f"not a directory: {root}\n")
            exit_code = 2
        else:
            try:
                findings = run_gate(root, fix=args.command == "fix")
            except RuffInventoryUnavailableError as error:
                sys.stderr.write(f"ruff-inventory: {error}\n")
                exit_code = 1
            else:
                if not findings:
                    sys.stdout.write("ok\n")
                else:
                    for finding in findings:
                        sys.stderr.write(f"{finding.stage}: {finding.detail}\n")
                    exit_code = 1
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
