# Fork notes

This is a fork of [1qh/lintmax-py](https://github.com/1qh/lintmax-py). `upstream/main` tracks upstream; reviewed fork patches land on `origin/main`, and the ledger below records the divergence.

## What diverges

| Patch | Files | What it changes |
| --- | --- | --- |
| markdown table token economy | `src/lintmax_py/dprint.py`, `src/lintmax_py/gate.py`, `src/lintmax_py/proc.py`, `tests/test_dprint.py`, `README.md` | markdown tables land compact instead of column-aligned |
| truthful gates (PR #1) | `README.md`, `src/lintmax_py/config.py`, `src/lintmax_py/gate.py`, `src/lintmax_py/rules.py`, `src/lintmax_py/staleness.py`, `tests/test_rules.py`, `tests/test_stage_order.py`, `tests/test_staleness.py` | zsh uses its parser; staleness follows project constraints and fails closed; rule/config inputs are validated at the gate boundary |
| target uv environment (PR #3) | `src/lintmax_py/gate.py`, `tests/test_stage_order.py` | Ty resolves from the checked uv project/workspace environment |
| safe fix policy | `src/lintmax_py/comments.py` (deleted), `src/lintmax_py/gate.py`, `src/lintmax_py/paths.py`, `tests/test_stage_order.py`, `README.md` | no universal comment-deletion stage; `fix` requests only Ruff safe fixes |
| dprint checks the project tree | `src/lintmax_py/config.py`, `src/lintmax_py/dprint.py`, `src/lintmax_py/gate.py`, `tests/test_stage_order.py` | the main `dprint` run formats the checked project instead of the gate's own temporary config directory |
| deptry runtime modules | `src/lintmax_py/config.py`, `tests/test_deptry_configuration.py`, `README.md` | `[tool.deptry.per_rule_ignores] DEP001` must be a list of top-level module names or the gate fails before any tool runs |
| project config cannot weaken a check | `src/lintmax_py/config.py`, `src/lintmax_py/gate.py`, `tests/test_project_config_isolation.py`, `tests/test_stage_order.py`, `README.md` | ty, typos and ShellCheck read only the gate's config; `[tool.deptry]` accepts only fact keys; vulture allowances must name something; ty's runtime-module fact crosses a validated boundary |

### Why

The markdown plugin pads every cell out to its column's widest entry. That alignment serves someone reading the raw file and costs a token per space for the reader this gate states it is built for, and the rendered document is byte-identical either way. Measured on this repo's own `README.md`: 7102 bytes aligned, 6218 compact — 884 bytes of padding, 12% of the file.

The plugin has no option for it. Its config schema at 0.22.1 exposes `deno`, `emphasisKind`, `headingKind`, `ignoreDirective`, `ignoreEndDirective`, `ignoreFileDirective`, `ignoreStartDirective`, `lineWidth`, `listIndentKind`, `locked`, `newLineKind`, `strongKind`, `tags`, `textWrap` and `unorderedListKind` — nothing about tables. The ignore directives are per-file comment markup, so using them would mean annotating every table in every project by hand.

So the compaction is the gate's own pass, applied after the plugin. Markdown is excluded from the main `dprint` invocation and swept separately: each file is formatted by the same plugin under the same config through `--stdin`, then its tables are compacted, then written on `fix` or reported as a finding on `check`. Nothing relaxes — a markdown file that is not in its final form is still a finding, and every other markdown rule the plugin enforces still runs.

### Truthful gates (PR #1)

ShellCheck cannot parse zsh, so zsh shebangs use `zsh -n` while supported POSIX-family scripts remain on the shfmt-then-ShellCheck path. Dependency staleness comes from `uv lock --upgrade --dry-run`, filtered to direct dependencies and their declared constraints; an unavailable resolver is a failing finding, not an unearned clean result. Ruff's external rule inventory is rejected unless it contains rule objects, and project-provided config crosses a typed data boundary before the gate materializes its own config.

### Target uv environment (PR #3)

Ty must resolve imports against the checked project's uv environment, not the gate process's checkout. `UV_PROJECT_ENVIRONMENT` is honored for absolute paths and resolved from the target project or its declared workspace for relative paths; an explicit missing directory fails the Ty stage rather than falling back to another environment.

### Safe fix policy

Comments have no sound universal lint rule: they can carry clinical rationale, provenance, licenses, and directives. The fork therefore has no universal comment-deletion stage or comment finding. `fix` still runs Ruff's safe repairs, but never asks Ruff for unsafe rewrites; those remain explicit review decisions. A comment attached to code that Ruff safely removes may disappear with that code.

### dprint checks the project tree

dprint resolves a config file's `includes` against the directory that holds the config, not the working directory. The gate writes its config into a private temporary directory, so the main `dprint` invocation, which named no files and leaned on `"includes": ["**/*"]`, checked only the gate's generated `dprint.json` and `ruff.toml` and never a project file. A malformed project `data.json` passed while the generated files failed on formatting the gate never asked for. The main invocation now passes `**/*` on the command line, which dprint resolves against the checked project, the same way the markdown sweep already passed `**/*.md`. The config's `**/` excludes still apply to command-line patterns. The meaningless `includes` key is gone from the generated config. The generated files are not reformatted to dprint's taste, because they are tool input that dprint no longer sees.

### deptry runtime modules

A project can inject a module at run time, such as a sibling checkout loaded through `uv run --with <path>`, so deptry reports the import as DEP001 even though declaring it would be false. deptry already reads `[tool.deptry]` from the checked project's `pyproject.toml` itself, so the gate forwards nothing. It validates only the DEP001 list at the config boundary. deptry matches each entry against an import's exact top-level module name, which means a dotted path, a hyphenated distribution name, a glob, or a non-string entry silently matches nothing. Those shapes, a bare string, and a non-table `[tool.deptry]` or `per_rule_ignores` now fail the gate as a `config` finding. Entries for other rules stay deptry's own concern. Forwarding the list with `--per-rule-ignores` was rejected, because that flag replaces deptry's whole per-rule table and would drop a project's entries for other rules.

### Project config cannot weaken a check

The Configless promise says a project may declare facts but cannot switch a check off. Four child tools broke it. Probed on ty 0.0.86, vulture 2.16, typos and ShellCheck from the managed toolchain, invoked with the gate's own flags: `[[tool.ty.overrides]]` silenced `unresolved-reference` in one file and `[tool.ty.src] exclude` skipped another, although `--error all` still beat `[tool.ty.rules]`. `_typos.toml` `extend-exclude` hid a misspelling, and a `.shellcheckrc` with `disable=all` hid SC2086. vulture's `exclude`, `min_confidence` and `paths` are overridden by the gate's flags, and `make_whitelist` still exits non-zero, but `ignore_names = ["*"]` hid every finding because the gate forwards that list itself. ty now gets `--config-file` with a generated `ty.toml`, typos `--isolated`, and ShellCheck `--norc`. Ruff, shfmt and dprint were already isolated by `--config` or explicit flags. vulture allowances must now contain a name, not only wildcards. The facts survive. Vocabulary and vulture allowances were already copied by the gate, and `[tool.ty.analysis] allowed-unresolved-imports` is now validated and written into the generated `ty.toml`. A pattern must start with a module name, so `**` cannot stand in for turning the rule off. deptry cannot be isolated, because it reads dependencies from the same file, so `[tool.deptry]` keys outside a fact allowlist fail the gate as a `config` finding. An allowlist was chosen over a blocklist so a switch deptry adds later fails closed.

## Rebasing onto upstream

```bash
git fetch origin
git fetch upstream
git switch --create sync/upstream-<version> origin/main
git rebase upstream/main
uv run --frozen pytest
git push --set-upstream origin sync/upstream-<version>
```

`switch --create` fails rather than overwriting an existing branch, and this recipe never checks out or rebases the shared `main` branch. Open a PR from the new `sync/upstream-<version>` branch only after its gates pass.

The conflicts to expect are in `_repo_stages` and `_python_stages` in `src/lintmax_py/gate.py`. Preserve the dprint flags/sweep, the main dprint run's command-line `PROJECT_GLOB`, and the target-project Ty environment selection. On every rebase, whether Git reports a conflict or not, review zsh dispatch, the staleness resolver/failure path, the rule-input boundary, `_environment`, its workspace helpers, `_python_stages`, `run_gate`, and the deletion of `comments.py`; do not reintroduce universal comment deletion or Ruff `--unsafe-fixes`. If upstream gains a table option in the plugin config, drop the whole markdown patch: delete `compact_tables`, `markdown_files` and `sweep` from `src/lintmax_py/dprint.py`, `filter_text` from `src/lintmax_py/proc.py`, and restore the plain `dprint` invocation while keeping its `PROJECT_GLOB`.

Never push this branch to `upstream`. `origin` is the fork.
