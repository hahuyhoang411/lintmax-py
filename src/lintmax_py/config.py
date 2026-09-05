# Copyright (c) lintmax-py contributors. Licensed under the MIT License.
from __future__ import annotations

import hashlib
import json
import tempfile
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath
from typing import TYPE_CHECKING, TypeGuard

import tomllib

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence


from . import rules
from .dprint import bump
from .paths import GLOB_EXCLUDES

LINE_LENGTH = 123
MIN_PROJECT_MAX_ARGS = 1
MAX_PROJECT_MAX_ARGS = 6
SUPPORTED_RUFF_TARGET_VERSIONS = (
    "py37",
    "py38",
    "py39",
    "py310",
    "py311",
    "py312",
    "py313",
    "py314",
)


class ProjectConfigurationError(ValueError):
    """A project declaration prevents lintmax-py from producing a truthful gate."""


@dataclass(frozen=True, slots=True)
class ProjectConfiguration:
    """The only Ruff declarations a project may contribute to the managed config."""

    max_args: int | None = None
    target_version: str | None = None
    namespace_packages: tuple[str, ...] | None = None


DPRINT_SEED = [
    "https://plugins.dprint.dev/json-0.23.0.wasm",
    "https://plugins.dprint.dev/markdown-0.22.1.wasm",
    "https://plugins.dprint.dev/toml-0.7.0.wasm",
    "https://plugins.dprint.dev/dockerfile-0.4.1.wasm",
    "https://plugins.dprint.dev/g-plane/pretty_yaml-v0.6.0.wasm",
    "https://plugins.dprint.dev/g-plane/malva-v0.16.0.wasm",
    "https://plugins.dprint.dev/g-plane/markup_fmt-v0.27.3.wasm",
    "https://plugins.dprint.dev/g-plane/pretty_graphql-v0.2.3.wasm",
    "https://plugins.dprint.dev/bartlomieju/lax-sql-0.3.0.wasm",
]

EXCLUDES = GLOB_EXCLUDES

TEST_GLOBS = ("**/tests/**/*.py", "**/test_*.py", "**/*_test.py", "**/conftest.py")
TEST_IGNORES = ("S101", "PLR2004", "INP001", "PLC2701", "SLF001")
"""Rules whose own purpose statement excludes test code, scoped to test files ONLY.

`assert` is pytest's assertion API rather than a production shortcut, a test's expected value IS a
literal so naming it only restates the assertion, a test directory carries no `__init__.py` by
design, and a test that never reaches its subject's internals cannot pin them. Nothing that ships
loses a rule: every one of these stays enforced on every other file in the tree.
"""


def _test_scoping() -> str:
    body = json.dumps(list(TEST_IGNORES))
    return "".join(f"{json.dumps(glob)} = {body}\n" for glob in TEST_GLOBS)


def confusables(root: Path) -> list[str]:
    """Read the characters a project declares as belonging to its own writing system.

    The ambiguous-character rule hunts homoglyphs, and on a codebase whose domain language is not
    Latin its correct punctuation reads as an attack: full-width parentheses inside Japanese prose
    are right, and rewriting them alters the text the product ships. That is vocabulary rather than
    strictness, exactly like the spelling dictionary, so the project declares it and the rule stays
    on for every character it did not name.

    Returns:
        The declared characters, or nothing when the project names none.

    """
    for name in ("ruff.toml", ".ruff.toml", "pyproject.toml"):
        path = root / name
        try:
            parsed = tomllib.loads(path.read_text(encoding="utf-8"))
        except (OSError, tomllib.TOMLDecodeError):
            continue
        node = parsed.get("tool", {}).get("ruff") if path.name == "pyproject.toml" else parsed
        section = node.get("lint") if isinstance(node, dict) else None
        declared = section.get("allowed-confusables") if isinstance(section, dict) else None
        if isinstance(declared, list) and declared:
            return [str(char) for char in declared]
    return []


COPYRIGHT_RULE = "CPY001"
DEFAULT_NOTICE = "(?i)Copyright\\s+(\\(c\\)|©)"


def copyright_notice(root: Path) -> str:
    """Read the copyright notice a project requires in its files.

    The notice rule enforces nothing until a project states whose notice it wants: the holder is a
    legal fact about that codebase, not something a gate can supply. Enabled unconditionally it
    reports every file of every project that has made no such decision, which is noise rather than
    strictness. Declared, it is enforced on every file; undeclared, the rule stands down and nothing
    else relaxes.

    Returns:
        The notice pattern the project declares, or nothing when it declares none.

    """
    for name in ("ruff.toml", ".ruff.toml", "pyproject.toml"):
        path = root / name
        try:
            parsed = tomllib.loads(path.read_text(encoding="utf-8"))
        except (OSError, tomllib.TOMLDecodeError):
            continue
        node = parsed.get("tool", {}).get("ruff") if path.name == "pyproject.toml" else parsed
        section = node.get("lint") if isinstance(node, dict) else None
        table = section.get("flake8-copyright") if isinstance(section, dict) else None
        declared = table.get("notice-rgx") if isinstance(table, dict) else None
        if isinstance(declared, str) and declared:
            return declared
    return ""


def project_configuration(root: Path) -> ProjectConfiguration:
    """Read and validate the bounded Ruff declarations from `pyproject.toml`.

    Projects contribute only `[tool.ruff] target-version`, `namespace-packages`,
    `[tool.ruff.lint.pylint] max-args`, `[tool.ruff.lint] allowed-confusables`, and
    `[tool.ruff.lint.flake8-copyright] notice-rgx` to managed Ruff policy. This
    function validates the first three. The dedicated readers handle the latter two.
    Parsing before the managed toolchain starts makes malformed declarations cheap
    configuration findings rather than analyzer work.

    Returns:
        The validated declarations, with defaults when no project file is present.

    Raises:
        ProjectConfigurationError: If a bounded declaration is malformed or unsupported.

    """
    path = root / "pyproject.toml"
    if not path.is_file():
        return ProjectConfiguration()
    try:
        parsed = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as error:
        message = "cannot read bounded Ruff configuration from pyproject.toml"
        raise ProjectConfigurationError(message) from error
    tool = parsed.get("tool")
    ruff = tool.get("ruff") if isinstance(tool, dict) else None
    lint = ruff.get("lint") if isinstance(ruff, dict) else None
    pylint = lint.get("pylint") if isinstance(lint, dict) else None
    max_args: int | None = None
    if pylint is not None:
        if not isinstance(pylint, dict):
            message = "[tool.ruff.lint.pylint] must be a table"
            raise ProjectConfigurationError(message)
        value = pylint.get("max-args")
        if value is not None:
            if type(value) is not int or not MIN_PROJECT_MAX_ARGS <= value <= MAX_PROJECT_MAX_ARGS:
                message = (
                    "[tool.ruff.lint.pylint].max-args must be an integer from "
                    f"{MIN_PROJECT_MAX_ARGS} through {MAX_PROJECT_MAX_ARGS}"
                )
                raise ProjectConfigurationError(message)
            max_args = value

    target_version: str | None = None
    target_value = ruff.get("target-version") if isinstance(ruff, dict) else None
    if target_value is not None:
        if type(target_value) is str and target_value in SUPPORTED_RUFF_TARGET_VERSIONS:
            target_version = target_value
        else:
            allowed = ", ".join(SUPPORTED_RUFF_TARGET_VERSIONS)
            message = f"[tool.ruff].target-version must be one of: {allowed}"
            raise ProjectConfigurationError(message)

    return ProjectConfiguration(
        max_args=max_args,
        target_version=target_version,
        namespace_packages=_namespace_packages(root, ruff),
    )


def _namespace_packages(root: Path, ruff: object) -> tuple[str, ...] | None:
    """Read the bounded namespace-package declarations from a Ruff table.

    Returns:
        Validated namespace package directories, or nothing when they are undeclared.

    Raises:
        ProjectConfigurationError: The declaration names a non-directory or leaves the project root.

    """
    namespace_value = ruff.get("namespace-packages") if isinstance(ruff, dict) else None
    if namespace_value is None:
        return None
    if not isinstance(namespace_value, list):
        message = "[tool.ruff].namespace-packages must be a list of relative package directories"
        raise ProjectConfigurationError(message)
    namespace_packages: list[str] = []
    for value in namespace_value:
        if not _namespace_directory(root, value):
            message = (
                "[tool.ruff].namespace-packages must contain existing descendant directories "
                "without symlinks, parent traversal, or globs"
            )
            raise ProjectConfigurationError(message)
        namespace_packages.append(value)
    return tuple(namespace_packages)


def _namespace_directory(root: Path, value: object) -> TypeGuard[str]:
    """Return whether one project declaration is a portable relative directory path.

    Returns:
        Whether ``value`` is an existing descendant directory without parent traversal or globs.

    """
    if not isinstance(value, str) or not value.strip() or any(char in value for char in "*?[]{}"):
        return False
    windows_path = PureWindowsPath(value)
    candidate = root / value
    if (
        Path(value).is_absolute()
        or windows_path.is_absolute()
        or windows_path.drive
        or ".." in Path(value).parts
        or ".." in windows_path.parts
    ):
        return False
    if _namespace_path_has_symlink(root, value):
        return False
    try:
        project_root = root.resolve(strict=True)
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(project_root)
    except (OSError, ValueError):
        return False
    return resolved != project_root and resolved.is_dir()


def _namespace_path_has_symlink(root: Path, value: str) -> bool:
    """Return whether a declared path traverses a symlink below the project root.

    Returns:
        Whether a configured path component is a symlink, including an unreadable one.

    """
    candidate = root
    try:
        for component in Path(value).parts:
            candidate /= component
            if candidate.is_symlink():
                return True
    except OSError:
        return True
    return False


def ruff_toml(
    inventory: Sequence[Mapping[str, object]],
    root: Path,
    project: ProjectConfiguration | None = None,
) -> str:
    """Build managed Ruff config from inventory plus bounded project declarations.

    Returns:
        TOML for the managed Ruff invocation.

    """
    configuration = project if project is not None else project_configuration(root)
    select = json.dumps(rules.selection(inventory))
    ignore = rules.ignored()
    allowed = confusables(root)
    allowed_line = f"allowed-confusables = {json.dumps(allowed, ensure_ascii=False)}\n" if allowed else ""
    notice = copyright_notice(root)
    if not notice:
        ignore.append(COPYRIGHT_RULE)
    pylint_table = f"[lint.pylint]\nmax-args = {configuration.max_args}\n" if configuration.max_args is not None else ""
    target_version_line = (
        f"target-version = {json.dumps(configuration.target_version)}\n"
        if configuration.target_version is not None
        else ""
    )
    namespace_packages_line = (
        f"namespace-packages = {json.dumps(configuration.namespace_packages)}\n"
        if configuration.namespace_packages is not None
        else ""
    )
    return (
        "preview = true\n"
        f"{target_version_line}"
        f"{namespace_packages_line}"
        f"line-length = {LINE_LENGTH}\n"
        f"exclude = {json.dumps(EXCLUDES)}\n"
        "[lint]\n"
        f"select = {select}\n"
        f"ignore = {json.dumps(ignore)}\n"
        f"{allowed_line}"
        f"{pylint_table}"
        f"[lint.per-file-ignores]\n{_test_scoping()}"
        "[lint.flake8-quotes]\n"
        'inline-quotes = "double"\n'
        "[lint.flake8-copyright]\n"
        f"notice-rgx = {json.dumps(notice or DEFAULT_NOTICE)}\n"
        "[format]\n"
        "docstring-code-format = true\n"
    )


def dprint_json() -> str:
    return json.dumps(
        {
            "lineWidth": LINE_LENGTH,
            "indentWidth": 2,
            "useTabs": False,
            "newLineKind": "lf",
            "includes": ["**/*"],
            "excludes": EXCLUDES,
            "plugins": bump(DPRINT_SEED),
        },
        indent=2,
    )


VOCABULARY_FILES = ("typos.toml", "_typos.toml", ".typos.toml", "pyproject.toml")
VOCABULARY_TABLES = ("extend-words", "extend-identifiers")


def vocabulary(root: Path) -> dict[str, dict[str, str]]:
    """Read the project's own spelling dictionary from the config the speller itself discovers.

    A spell checker with no project dictionary reports every domain noun a codebase owns — a client
    name, a product name, a protocol token — as a misspelling, and the only escapes are renaming the
    domain or turning the stage off. Neither is acceptable, so the dictionary is merged in. The
    speller resolves one config file and offers no inheritance, and the gate passes its own generated
    config, so a project file would otherwise be ignored entirely.

    Only the two vocabulary tables are read. The switches stay owned by the gate, so a project can
    name the words it uses and cannot weaken the check that reads them.

    Returns:
        The vocabulary tables present in the first config file that carries the speller's section.

    """
    for name in VOCABULARY_FILES:
        section = _typos_section(root / name)
        if section is None:
            continue
        found: dict[str, dict[str, str]] = {}
        for table in VOCABULARY_TABLES:
            entries = section.get(table)
            if isinstance(entries, dict):
                found[table] = {str(word): str(correction) for word, correction in entries.items()}
        if found:
            return found
    return {}


def _typos_section(path: Path) -> dict[str, object] | None:
    try:
        parsed = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return None
    node = parsed.get("tool", {}).get("typos") if path.name == "pyproject.toml" else parsed
    if not isinstance(node, dict):
        return None
    default = node.get("default")
    if not isinstance(default, dict):
        return None
    return {str(key): value for key, value in default.items()}


def typos_toml(root: Path) -> str:
    body = "[default]\ncheck-filename = true\ncheck-file = true\n"
    for table, entries in vocabulary(root).items():
        body += f"[default.{table}]\n"
        body += "".join(f"{json.dumps(word)} = {json.dumps(correction)}\n" for word, correction in sorted(entries.items()))
    return body


def materialize(
    inventory: rules.RuffInventory,
    root: Path,
    project: ProjectConfiguration | None = None,
) -> tuple[Path, str]:
    """Write generated tool configs using already-validated project declarations.

    Returns:
        The temporary config directory and its content digest.

    """
    configuration = project if project is not None else project_configuration(root)
    cfg_root = Path(tempfile.mkdtemp(prefix="lintmax-py-"))
    written = {
        "ruff.toml": ruff_toml(list(inventory.rules), root, configuration),
        "dprint.json": dprint_json(),
        "typos.toml": typos_toml(root),
    }
    for name, body in written.items():
        (cfg_root / name).write_text(body, encoding="utf-8")
    digest = hashlib.sha256("".join(written.values()).encode()).hexdigest()
    return cfg_root, digest


VULTURE_KEYS = ("ignore_decorators", "ignore_names")


def vulture_allowances(root: Path) -> dict[str, list[str]]:
    """Read what a project declares its dead-code analysis cannot see.

    A function reached only through a registration decorator, and an attribute read only by a
    metaclass, are both live and both invisible to a static reachability scan — so the scan reports
    every route handler and every model field as dead. That is a fact about the frameworks a project
    uses, which the gate cannot know and the project can state, exactly like its spelling dictionary.

    Only the two allowance lists are read; nothing a project writes can switch the stage off.

    Returns:
        The declared allowances, keyed by the flag they populate.

    """
    try:
        parsed = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return {}
    section = parsed.get("tool", {}).get("vulture")
    if not isinstance(section, dict):
        return {}
    found: dict[str, list[str]] = {}
    for key in VULTURE_KEYS:
        declared = section.get(key)
        if isinstance(declared, list) and declared:
            found[key] = [str(item) for item in declared]
    return found
