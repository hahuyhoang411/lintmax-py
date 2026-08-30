# Copyright (c) lintmax-py contributors. Licensed under the MIT License.
from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
import tomllib

from lintmax_py import __version__
from lintmax_py.config import DPRINT_SEED, LINE_LENGTH
from lintmax_py.dprint import compact_tables, plugin_path, sweep

HOST = "https://plugins.dprint.dev/"

PADDED = "| stage | tool | note      |\n| ----- | :--- | --------: |\n| lint  | ruff | all rules |\n"
COMPACT = "| stage | tool | note |\n| --- | :--- | ---: |\n| lint | ruff | all rules |\n"


@pytest.mark.parametrize(
    ("pinned", "expected"),
    [
        (HOST + "json-0.23.0.wasm", "dprint/json"),
        (HOST + "markdown-0.22.1.wasm", "dprint/markdown"),
        (HOST + "g-plane/pretty_yaml-v0.6.0.wasm", "g-plane/pretty_yaml"),
        (HOST + "g-plane/markup_fmt-v0.27.3.wasm", "g-plane/markup_fmt"),
        (HOST + "bartlomieju/lax-sql-0.3.0.wasm", "bartlomieju/lax-sql"),
    ],
)
def test_a_hyphenated_plugin_keeps_its_whole_name(pinned: str, expected: str) -> None:
    """Splitting at the first hyphen resolves `lax-sql` to `lax`, which is a different plugin.

    The wrong name still reads as a name, so the only symptom is a 404 against a plausible URL.
    """
    assert plugin_path(pinned) == expected


def test_a_foreign_host_is_refused() -> None:
    assert plugin_path("https://example.invalid/json-0.23.0.wasm") is None


def test_the_reported_version_is_the_one_the_manifest_declares() -> None:
    """A version duplicated in the code drifts from the manifest, and only a release exposes it.

    Measured: the published package reported 0.0.1 while the registry served 0.0.2, because the
    literal in the source was a second home for a fact the manifest already owned.
    """
    manifest = tomllib.loads((Path(__file__).parent.parent / "pyproject.toml").read_text(encoding="utf-8"))
    assert __version__ == manifest["project"]["version"]


def test_alignment_padding_is_collapsed_and_the_alignment_itself_survives() -> None:
    """Padding a cell to its column's width buys nothing for the reader this gate is designed for.

    A coding agent pays a token per space and reads the same table either way, so the padding is
    pure cost. The colons are not padding: they set how the cell renders, so they stay.
    """
    assert compact_tables(PADDED) == COMPACT


def test_compacting_an_already_compact_table_changes_nothing() -> None:
    """A pass that is not idempotent turns every run of the gate into a diff."""
    assert compact_tables(COMPACT) == COMPACT


def test_a_table_inside_a_fenced_block_is_left_exactly_as_written() -> None:
    """Fenced content is literal text, and the fence may be showing what unformatted input looks like."""
    fenced = "```md\n| a  | b   |\n| -- | --- |\n```\n"
    assert compact_tables(fenced) == fenced


def test_a_pipe_in_prose_is_not_a_table() -> None:
    """Without the delimiter row there is no table, so collapsing the spacing would rewrite prose."""
    prose = "The shell reads a  |  b as a pipeline.\n\n| not  a table |\n"
    assert compact_tables(prose) == prose


def test_a_table_indented_inside_a_list_keeps_its_indentation() -> None:
    """Losing the indent moves the table out of its list item, changing the rendered document."""
    indented = "- item\n\n  | a | bb |\n  | --- | ---- |\n  | c | d |\n"
    assert compact_tables(indented) == "- item\n\n  | a | bb |\n  | --- | --- |\n  | c | d |\n"


def test_an_escaped_pipe_stays_inside_its_cell() -> None:
    """Splitting on every pipe would read an escaped one as a cell boundary and split the content."""
    escaped = "| a | b \\| c |\n| --- | --- |\n"
    assert compact_tables(escaped) == escaped


@pytest.mark.skipif(shutil.which("dprint") is None, reason="the formatter itself is what is under test")
def test_the_sweep_fixes_a_padded_table_and_then_accepts_it(tmp_path: Path) -> None:
    """The end the whole pass exists for: what `fix` writes is what `check` accepts.

    A compaction applied on the way out but not honoured on the way back in makes every markdown
    file a permanent finding, which is worse than the padding it removes.
    """
    config = tmp_path / "dprint.json"
    config.write_text(
        json.dumps({
            "lineWidth": LINE_LENGTH,
            "includes": ["**/*"],
            "plugins": list(DPRINT_SEED),
        }),
        encoding="utf-8",
    )
    page = tmp_path / "page.md"
    page.write_text("# Probe\n\n" + PADDED, encoding="utf-8")

    assert sweep(tmp_path, config, shutil.which("dprint") or "dprint", fix=False) != []
    assert sweep(tmp_path, config, shutil.which("dprint") or "dprint", fix=True) == []
    assert page.read_text(encoding="utf-8") == "# Probe\n\n" + COMPACT
    assert sweep(tmp_path, config, shutil.which("dprint") or "dprint", fix=False) == []
