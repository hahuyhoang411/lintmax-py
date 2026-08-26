# Fork notes

This is a fork of [1qh/lintmax-py](https://github.com/1qh/lintmax-py). `upstream/main` tracks upstream; reviewed fork patches land on `origin/main`, and the ledger below records the divergence.

## What diverges

| Patch | Files | What it changes |
| --- | --- | --- |
| markdown table token economy | `src/lintmax_py/dprint.py`, `src/lintmax_py/gate.py`, `src/lintmax_py/proc.py`, `tests/test_dprint.py`, `README.md` | markdown tables land compact instead of column-aligned |
| truthful gates (PR #1) | `README.md`, `src/lintmax_py/config.py`, `src/lintmax_py/gate.py`, `src/lintmax_py/rules.py`, `src/lintmax_py/staleness.py`, `tests/test_rules.py`, `tests/test_stage_order.py`, `tests/test_staleness.py` | zsh uses its parser; staleness follows project constraints and fails closed; rule/config inputs are validated at the gate boundary |
| target uv environment (PR #3) | `src/lintmax_py/gate.py`, `tests/test_stage_order.py` | Ty resolves from the checked uv project/workspace environment |
| safe fix policy | `src/lintmax_py/comments.py` (deleted), `src/lintmax_py/gate.py`, `src/lintmax_py/paths.py`, `tests/test_stage_order.py`, `README.md` | no universal comment-deletion stage; `fix` requests only Ruff safe fixes |

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

The conflicts to expect are in `_repo_stages` and `_python_stages` in `src/lintmax_py/gate.py`. Preserve both the dprint flags/sweep and the target-project Ty environment selection. On every rebase, whether Git reports a conflict or not, review zsh dispatch, the staleness resolver/failure path, the rule-input boundary, `_environment`, its workspace helpers, `_python_stages`, `run_gate`, and the deletion of `comments.py`; do not reintroduce universal comment deletion or Ruff `--unsafe-fixes`. If upstream gains a table option in the plugin config, drop the whole markdown patch: delete `compact_tables`, `markdown_files` and `sweep` from `src/lintmax_py/dprint.py`, `filter_text` from `src/lintmax_py/proc.py`, and restore the plain `dprint` invocation.

Never push this branch to `upstream`. `origin` is the fork.
