# lintmax-py

Maximum-strictness Python quality gate. One command, always-latest, never stale.

The Python counterpart to [lintmax](https://github.com/1qh/lintmax) (TypeScript), [lintmax-go](https://github.com/1qh/lintmax-go) and [lintmax-rs](https://github.com/1qh/lintmax-rs). Designed for coding agents, not humans.

## Why

Python ships no strictness by default: no compiler, no unused-import error, no type enforcement. lintmax-py closes that gap and pushes past it — every rule ruff carries including the preview set, every ty diagnostic at error severity, plus the layers neither tool covers: dead code, unused dependencies, vulnerabilities, spelling, shell scripts and every non-Python file in the tree.

## Never stale

No tool version is ever pinned. Ruff, ty and every child tool are fetched at latest on each run, and the rule set is DERIVED from the installed ruff rather than listed — so the moment ruff ships a new rule, your gate runs it. Dependency staleness is scanned against upstream every run.

dprint plugins resolve through each plugin's `latest.json` and the concrete versioned URL is written back. A constant floating URL is deliberately NOT used: dprint caches a plugin by its URL, so an unchanging URL resolves once and then freezes silently, which is the exact staleness the floating form appears to solve.

## Use

Exactly four commands — the lean agent-first surface:

```
lintmax-py fix      # format + autofix + full gate — the default action
lintmax-py check    # verify only, no writes (CI mode) — same exhaustive scanner set
lintmax-py version  # print version
lintmax-py rules    # list every enabled rule under the maxed config
```

Prints `ok` on a single line on success, exit 0 = clean. Tool output is shown only on failure. A clean run that is cached prints `ok (cached)`.

## Self-evolving (automatic, never a command)

- Child tools reinstalled at latest on a refresh cadence; CI always forces latest.
- The binary refreshes itself in CI before gating.
- Green-tree-hash cache skips a `check` whose tree is unchanged.
- Dependency staleness scanned against upstream every run.

## What runs

| Layer | Tool | Catches |
| --- | --- | --- |
| comments | native (`tokenize`) | deletes every `#` comment except directives; docstrings survive |
| format | ruff format | deterministic formatting |
| lint | ruff, every rule including preview | 968 rules across 59 linters at ruff 0.16.1 |
| types | ty, every rule at error | type errors, including unannotated bodies mypy skips |
| dead code | vulture | unreachable functions, classes and names |
| unused deps | deptry | declared-but-unused and used-but-undeclared |
| vulnerabilities | pip-audit | PyPI Advisory Database plus OSV |
| spelling | typos | misspellings in code, identifiers and filenames |
| shell | shellcheck, shfmt | every shell script, every optional check on |
| other files | dprint | toml, json, markdown, yaml, dockerfile, css, html |

## Strictness policy

- The ruff rule set is derived from `ruff rule --all`, so a newly shipped rule is enabled the run after it lands. `ALL` alone is not enough: preview rules require their exact code.
- Every rule is error or off, never warn.
- ty runs with all rules at error severity.
- Ruff's own conflicting-rule pairs resolve to the stricter member.
- The disable list starts EMPTY. Each entry is earned by a concrete conflict found on real code, never anticipated, and carries its reason.

## Earned disables

| Rule | Reason |
| --- | --- |
| `D100`-`D107` | operator decision: code is self-explanatory rather than docstring-documented |

## Configless

Every config is embedded in the tool. Your project stays clean — no ruff.toml, no ty.toml, no dprint.json, no typos.toml. Updating lintmax-py updates every project's strictness. The bundled config is generic only and carries no project or ecosystem opinion.

## License

MIT
