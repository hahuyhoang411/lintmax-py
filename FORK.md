# Fork notes

This is a fork of [1qh/lintmax-py](https://github.com/1qh/lintmax-py). `main` tracks upstream; the divergence lives on `meddies-patches`.

## What diverges

| Patch | Files | What it changes |
| --- | --- | --- |
| markdown table token economy | `src/lintmax_py/dprint.py`, `src/lintmax_py/gate.py`, `src/lintmax_py/proc.py`, `tests/test_dprint.py`, `README.md` | markdown tables land compact instead of column-aligned |

### Why

The markdown plugin pads every cell out to its column's widest entry. That alignment serves someone reading the raw file and costs a token per space for the reader this gate states it is built for, and the rendered document is byte-identical either way. Measured on this repo's own `README.md`: 7102 bytes aligned, 6218 compact — 884 bytes of padding, 12% of the file.

The plugin has no option for it. Its config schema at 0.22.1 exposes `deno`, `emphasisKind`, `headingKind`, `ignoreDirective`, `ignoreEndDirective`, `ignoreFileDirective`, `ignoreStartDirective`, `lineWidth`, `listIndentKind`, `locked`, `newLineKind`, `strongKind`, `tags`, `textWrap` and `unorderedListKind` — nothing about tables. The ignore directives are per-file comment markup, so using them would mean annotating every table in every project by hand.

So the compaction is the gate's own pass, applied after the plugin. Markdown is excluded from the main `dprint` invocation and swept separately: each file is formatted by the same plugin under the same config through `--stdin`, then its tables are compacted, then written on `fix` or reported as a finding on `check`. Nothing relaxes — a markdown file that is not in its final form is still a finding, and every other markdown rule the plugin enforces still runs.

## Rebasing onto upstream

```bash
git fetch upstream
git checkout meddies-patches
git rebase upstream/main
uv run --python 3.13 --with pytest pytest
```

The conflict to expect is in `_repo_stages` in `src/lintmax_py/gate.py`, where the patch adds `--excludes`, `--allow-no-files` and the markdown sweep to the `dprint` stage. Resolve by keeping both sides' flags. If upstream ever gains a table option in the plugin config, drop the whole patch: delete `compact_tables`, `markdown_files` and `sweep` from `src/lintmax_py/dprint.py`, `filter_text` from `src/lintmax_py/proc.py`, and restore the plain `dprint` invocation.

Never push this branch to `upstream`. `origin` is the fork.
