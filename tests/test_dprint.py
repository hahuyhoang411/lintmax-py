# Copyright (c) lintmax-py contributors. Licensed under the MIT License.
from __future__ import annotations

import pytest

from lintmax_py.dprint import plugin_path

HOST = "https://plugins.dprint.dev/"


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
