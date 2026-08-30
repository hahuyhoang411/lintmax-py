# lintmax-py

Maximum-strictness Python quality gate. One command, always-latest, never stale.

The Python counterpart to [lintmax](https://github.com/1qh/lintmax) (TypeScript), [lintmax-go](https://github.com/1qh/lintmax-go) and [lintmax-rs](https://github.com/1qh/lintmax-rs). Designed for coding agents, not humans.

## Why

Python ships no strictness by default: no compiler, no unused-import error, no type enforcement. lintmax-py closes that gap and pushes past it — every rule ruff carries including the preview set, every ty diagnostic at error severity, plus the layers neither tool covers: dead code, unused dependencies, vulnerabilities, spelling, shell scripts and every non-Python file in the tree.

## Never stale

The gate installs child tools at latest through pinned `uvx uv@0.12.3`. The pin makes the installer reproducible. It does not pin Ruff, ty, or any child tool. Each refresh builds an unpublished, private uv tool generation under lintmax-py's cache, validates the resolved launchers, then atomically publishes that generation. Each launcher must resolve inside its declared package directory, so one managed package cannot impersonate another. One invocation holds a lease on its immutable generation for the full gate, then releases it. Later refreshes retain the current generation and any leased generation, while reaping completed superseded generations. A `PATH` executable cannot replace a managed tool after the snapshot exists. Direct dependency staleness is resolved through the same pinned `uvx uv@0.12.3 lock --upgrade --dry-run`, so the gate reports only releases the project's declared constraints can install. An exact dependency pin is a project decision, not perpetual staleness.

Managed toolchains support Unix hosts only. The gate needs Unix advisory file locks to preserve live generations during refresh and `/bin/zsh` for its shell syntax stage. On Windows it exits with a toolchain error rather than claiming the Unix-only stages ran.

dprint plugins resolve through each plugin's `latest.json` and the concrete versioned URL is written back. A constant floating URL is deliberately NOT used: dprint caches a plugin by its URL, so an unchanging URL resolves once and then freezes silently, which is the exact staleness the floating form appears to solve.

## Use

Exactly four commands — the lean agent-first surface:

```
lintmax-py fix      # format + Ruff safe autofix + full gate — the default action
lintmax-py check    # verify only, no writes (CI mode) — same exhaustive scanner set
lintmax-py version  # print version
lintmax-py rules    # list every enabled rule under the maxed config
```

Prints `ok` on a single line on success, exit 0 = clean. Tool output is shown only on failure. A clean run that is cached prints `ok (cached)`.

## Self-evolving (automatic, never a command)

- Child tools refresh at latest on a 24-hour cadence; CI always forces latest through `uvx uv@0.12.3`.
- The binary refreshes itself in CI before gating.
- No green-tree-hash cache: measured on 10,039 real files with all 968 rules, a full ruff run costs 4.3s while hashing the tree to skip it costs 2.6s, so the cache buys ~40% in its best case and adds a false-green failure mode. The expensive work is the network, and that is TTL-cached instead.
- Direct dependency staleness resolved against the project's constraints every run.

## What runs

| Layer | Tool | Catches |
| --- | --- | --- |
| format | ruff format | deterministic formatting |
| lint | ruff, every rule including preview | 968 rules across 59 linters at ruff 0.16.1 |
| types | ty, every rule at error | type errors, including unannotated bodies mypy skips |
| dead code | vulture | unreachable functions, classes and names |
| unused deps | deptry | declared-but-unused and used-but-undeclared |
| vulnerabilities | pip-audit | PyPI Advisory Database plus OSV |
| spelling | typos | misspellings in code, identifiers and filenames |
| shell | shellcheck, shfmt, zsh -n | ShellCheck and shfmt for supported shells; zsh scripts use zsh's own parser |
| other files | dprint | toml, json, markdown, yaml, dockerfile, css, html |

## Strictness policy

- The ruff rule set is derived from `ruff rule --all`, so a newly shipped rule is enabled the run after it lands. `ALL` alone is not enough: preview rules require an explicit selector, normally their code and otherwise their validated name.
- If Ruff reports a rule without a code, lintmax-py selects its validated rule name; if it has neither selector, the gate fails closed rather than claiming exhaustive coverage.
- Every rule is error or off, never warn.
- ty runs with all rules at error severity.
- `fix` applies only Ruff's safe fixes; unsafe rewrites remain findings for explicit review.
- Ruff's own conflicting-rule pairs resolve to the stricter member.
- The disable list starts EMPTY. Each entry is earned by a concrete conflict found on real code, never anticipated, and carries its reason.

## Earned disables

| Rule | Reason |
| --- | --- |
| `D100`-`D107` | operator decision: code is self-explanatory rather than docstring-documented |
| `CPY001` | stands down unless the project declares its `notice-rgx`; enforced on every file once it does |

## Configless

Every rule config is embedded in the tool. Your project stays clean — no ruff.toml, no ty.toml, no dprint.json. Updating lintmax-py updates every project's strictness. The bundled config is generic only and carries no project or ecosystem opinion.

The single exception is vocabulary, which is data rather than strictness. A spell checker with no project dictionary reports every domain noun a codebase owns — a client name, a product name, a protocol token — as a misspelling, and the only escapes would be renaming the domain or turning the stage off. So the `[default.extend-words]` and `[default.extend-identifiers]` tables are read from whichever of `typos.toml`, `_typos.toml`, `.typos.toml` or `pyproject.toml` (`[tool.typos]`) your project carries, in that order, and merged into the generated config. Nothing else in that file is read: the switches stay owned by the gate, so a project can name the words it uses and cannot weaken the check that reads them.

```toml
# typos.toml
[default.extend-words]
myproduct = "myproduct"
```

The same principle covers the ambiguous-character rule: a codebase whose domain language is not Latin uses punctuation the rule reads as a homoglyph, and rewriting it would change the text the product ships. Declare those characters in `ruff.toml`, `.ruff.toml` or `pyproject.toml` (`[tool.ruff.lint]`) and they are merged into the generated config; every character you do not name stays flagged.

```toml
# ruff.toml
[lint]
allowed-confusables = ["（", "）", "："]
```

Two more facts a gate cannot infer are read the same way. A dead-code scan cannot see a function reached only through a registration decorator, nor an attribute read only by a metaclass, so a project states them and every other name stays scanned:

```toml
# pyproject.toml
[tool.vulture]
ignore_decorators = ["@app.route"]
ignore_names = ["model_config"]
```

And the copyright rule enforces nothing until a project says whose notice it wants — the holder is a legal fact about that codebase. Declare `notice-rgx` and the rule is enforced on every file; declare nothing and it stands down, with no other rule relaxed.

```toml
# ruff.toml
[lint.flake8-copyright]
notice-rgx = "(?i)Copyright\\s+\\(c\\) Example Ltd"
```

## License

MIT
