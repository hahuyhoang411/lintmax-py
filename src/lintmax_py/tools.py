# Copyright (c) lintmax-py contributors. Licensed under the MIT License.
from __future__ import annotations

import hashlib
import os
import shutil
import stat
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType, TracebackType
from typing import TYPE_CHECKING, Self, cast

from .proc import Result, run

try:
    import fcntl
except ImportError:
    fcntl = None

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator, Mapping
    from typing import IO, Protocol

    class _FileLocking(Protocol):
        LOCK_EX: int
        LOCK_NB: int
        LOCK_SH: int

        flock: Callable[[int, int], None]


UV_VERSION = "uv@0.12.3"
CACHE_ROOT_ENV = "LINTMAX_PY_TOOLCHAIN_DIR"
SYSTEM_ZSH = Path("/bin/zsh")
TOOLS = {
    "ruff": "ruff",
    "ty": "ty",
    "vulture": "vulture",
    "deptry": "deptry",
    "pip-audit": "pip-audit",
    "typos": "typos",
    "shellcheck-py": "shellcheck",
    "shfmt-py": "shfmt",
    "dprint-py": "dprint",
}
REFRESH_TTL_SECONDS = 24 * 60 * 60


class ToolchainUnavailableError(RuntimeError):
    """The private uv-managed toolchain cannot produce attributable executables."""


@dataclass(slots=True)
class _CleanupAttempt:
    """Capture any cleanup failure so the caller can preserve its causal exception."""

    error: BaseException | None = None

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        _exception_type: type[BaseException] | None,
        error: BaseException | None,
        _traceback: TracebackType | None,
    ) -> bool:
        self.error = error
        return error is not None


def _preserve_primary_error(
    primary: BaseException,
    cleanup: Callable[[], None],
    context: str,
) -> None:
    """Run cleanup without replacing the exception that first made the operation fail."""
    attempt = _CleanupAttempt()
    with attempt:
        cleanup()
    if attempt.error is not None:
        primary.add_note(f"{context} also failed: {attempt.error!r}")


def _locking() -> _FileLocking:
    """Return Unix locking primitives after rejecting unsupported platforms.

    Returns:
        The advisory-lock module used by private toolchain generations.

    Raises:
        ToolchainUnavailableError: The host cannot provide Unix file locking.

    """
    if fcntl is None:
        message = "lintmax-py managed toolchains require Unix file locking and /bin/zsh"
        raise ToolchainUnavailableError(message)
    return cast("_FileLocking", fcntl)


@dataclass(frozen=True, slots=True)
class Tool:
    """One resolved executable from a private immutable generation."""

    package: str
    executable: str
    path: Path
    version: str


@dataclass(frozen=True, slots=True)
class UvxLauncher:
    """The uvx launcher captured before tool installation starts."""

    path: Path
    device: int
    inode: int
    version: str

    def command(self) -> tuple[str, str]:
        """Revalidate this launcher immediately before invoking uv.

        Returns:
            The pinned uvx command prefix.

        Raises:
            ToolchainUnavailableError: The launcher changed after the snapshot was captured.

        """
        try:
            current = self.path.stat()
        except OSError as error:
            message = f"captured uvx launcher is unavailable: {self.path}: {error}"
            raise ToolchainUnavailableError(message) from error
        if (current.st_dev, current.st_ino) != (self.device, self.inode):
            message = f"captured uvx launcher changed after toolchain snapshot: {self.path}"
            raise ToolchainUnavailableError(message)
        result = run([str(self.path), "--version"], timeout=60)
        version = result.out.splitlines()[0] if result.out else ""
        if result.code != 0 or version != self.version:
            message = f"captured uvx launcher version changed after toolchain snapshot: {self.path}"
            raise ToolchainUnavailableError(message)
        return str(self.path), UV_VERSION


@dataclass(slots=True)
class _GenerationLease:
    """A shared advisory lock that keeps one published generation alive for a gate."""

    handle: IO[str]

    def close(self) -> None:
        """Release this generation after its gate has finished."""
        if not self.handle.closed:
            self.handle.close()


@dataclass(frozen=True, slots=True)
class Toolchain:
    """One immutable private generation and its resolved analyzer executables."""

    tools: Mapping[str, Tool]
    generation: Path
    uvx: UvxLauncher
    zsh: Path | None
    lease: _GenerationLease | None = None

    def tool(self, executable: str) -> Tool:
        return self.tools[executable]

    def path(self, executable: str) -> str:
        return str(self.tool(executable).path)

    def version(self, executable: str) -> str:
        return self.tool(executable).version

    def uv_command(self) -> tuple[str, str]:
        return self.uvx.command()

    def close(self) -> None:
        """Release the generation lease captured for this invocation."""
        if self.lease is not None:
            self.lease.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_details: object) -> None:
        self.close()


def is_ci() -> bool:
    return any(os.environ.get(name) for name in ("CI", "GITHUB_ACTIONS"))


def cache_root() -> Path:
    configured = os.environ.get(CACHE_ROOT_ENV)
    return Path(configured).expanduser() if configured else Path.home() / ".cache" / "lintmax-py" / "toolchains"


def stamp() -> Path:
    key = hashlib.sha256(b"lintmax-py-refresh").hexdigest()[:16]
    return cache_root() / f"{key}.refresh"


def fresh() -> bool:
    if is_ci():
        return False
    path = stamp()
    try:
        exists = path.is_file()
    except OSError as error:
        message = f"cannot inspect lintmax-py refresh stamp {path}: {error}"
        raise ToolchainUnavailableError(message) from error
    if not exists:
        return False
    try:
        stamped = float(path.read_text(encoding="utf-8").strip())
    except ValueError:
        return False
    except OSError as error:
        message = f"cannot read lintmax-py refresh stamp {path}: {error}"
        raise ToolchainUnavailableError(message) from error
    return (time.time() - stamped) < REFRESH_TTL_SECONDS


def mark() -> None:
    path = stamp()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(str(time.time()), encoding="utf-8")
    except OSError as error:
        message = f"cannot write lintmax-py refresh stamp {path}: {error}"
        raise ToolchainUnavailableError(message) from error


def _failure(context: str, result: Result) -> ToolchainUnavailableError:
    detail = result.out or f"exit {result.code} with no output"
    return ToolchainUnavailableError(f"{context} (exit {result.code}): {detail}")


def _inside(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def _capture_uvx() -> UvxLauncher:
    candidate = shutil.which("uvx")
    if candidate is None:
        message = "uvx is not installed; lintmax-py requires uvx uv@0.12.3"
        raise ToolchainUnavailableError(message)
    path = Path(candidate).resolve()
    try:
        metadata = path.stat()
    except OSError as error:
        message = f"cannot inspect uvx launcher {path}: {error}"
        raise ToolchainUnavailableError(message) from error
    if not path.is_file() or not os.access(path, os.X_OK):
        message = f"uvx launcher is not executable: {path}"
        raise ToolchainUnavailableError(message)
    result = run([str(path), "--version"], timeout=60)
    if result.code != 0 or not result.out:
        context = f"uvx launcher {path} could not report its version"
        raise _failure(context, result)
    return UvxLauncher(path, metadata.st_dev, metadata.st_ino, result.out.splitlines()[0])


def _tool_environment(generation: Path) -> dict[str, str]:
    return {
        "UV_TOOL_DIR": str(generation / "tools"),
        "UV_TOOL_BIN_DIR": str(generation / "bin"),
    }


@contextmanager
def _publish_lock(root: Path) -> Iterator[None]:
    locking = _locking()
    try:
        root.mkdir(parents=True, exist_ok=True)
        lock = (root / "publish.lock").open("a+", encoding="utf-8")
    except OSError as error:
        message = f"cannot create lintmax-py toolchain cache at {root}: {error}"
        raise ToolchainUnavailableError(message) from error
    try:
        locking.flock(lock.fileno(), locking.LOCK_EX)
    except OSError as error:
        message = f"cannot lock lintmax-py toolchain cache at {root}: {error}"
        lock.close()
        raise ToolchainUnavailableError(message) from error
    try:
        yield
    except BaseException as error:
        _preserve_primary_error(error, lock.close, "closing the toolchain publish lock")
        raise
    else:
        lock.close()


def _current_generation(root: Path) -> Path | None:
    pointer = root / "current"
    try:
        metadata = pointer.lstat()
    except FileNotFoundError:
        return None
    except OSError as error:
        message = f"cannot inspect lintmax-py current generation pointer {pointer}: {error}"
        raise ToolchainUnavailableError(message) from error
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        message = f"lintmax-py current generation pointer must be a regular file: {pointer}"
        raise ToolchainUnavailableError(message)
    try:
        name = pointer.read_text(encoding="utf-8").strip()
    except OSError as error:
        message = f"cannot read lintmax-py current generation pointer {pointer}: {error}"
        raise ToolchainUnavailableError(message) from error
    if not name.startswith("generation-") or Path(name).name != name:
        message = f"lintmax-py current generation pointer is invalid: {pointer}"
        raise ToolchainUnavailableError(message)
    generation = root / name
    try:
        if generation.is_symlink() or not generation.is_dir():
            message = f"lintmax-py current generation is unavailable: {generation}"
            raise ToolchainUnavailableError(message)
    except OSError as error:
        message = f"cannot inspect lintmax-py current generation {generation}: {error}"
        raise ToolchainUnavailableError(message) from error
    return generation


def _publish(root: Path, generation: Path) -> None:
    pointer = root / "current"
    temporary = root / f".current-{uuid.uuid4().hex}"
    try:
        temporary.write_text(generation.name, encoding="utf-8")
        temporary.replace(pointer)
    except OSError as error:
        message = f"cannot publish lintmax-py toolchain generation {generation}: {error}"
        raise ToolchainUnavailableError(message) from error


def _lease(generation: Path) -> _GenerationLease:
    """Acquire the shared lease that prevents a live generation from being reaped.

    Returns:
        The open lease held until the gate calls ``Toolchain.close``.

    Raises:
        ToolchainUnavailableError: The generation lease cannot be opened or locked.

    """
    locking = _locking()
    path = generation / "lease.lock"
    handle: IO[str] | None = None
    try:
        handle = path.open("a+", encoding="utf-8")
        locking.flock(handle.fileno(), locking.LOCK_SH)
    except OSError as error:
        if handle is not None:
            handle.close()
        message = f"cannot lease lintmax-py toolchain generation {generation}: {error}"
        raise ToolchainUnavailableError(message) from error
    return _GenerationLease(handle)


def _remove_generation(generation: Path) -> None:
    """Delete a private generation that this process created but did not publish.

    Raises:
        ToolchainUnavailableError: The private unpublished generation cannot be removed.

    """
    try:
        shutil.rmtree(generation)
    except FileNotFoundError:
        return
    except OSError as error:
        message = f"cannot remove unpublished lintmax-py toolchain generation {generation}: {error}"
        raise ToolchainUnavailableError(message) from error


def _reap_generations(root: Path, current: Path) -> None:
    """Remove only inactive private generations after a new current pointer is published.

    Raises:
        ToolchainUnavailableError: An inactive private generation cannot be removed.

    """
    locking = _locking()
    for generation in root.glob("generation-*"):
        if generation == current or generation.is_symlink() or not generation.is_dir():
            continue
        handle: IO[str] | None = None
        try:
            handle = (generation / "lease.lock").open("a+", encoding="utf-8")
            locking.flock(handle.fileno(), locking.LOCK_EX | locking.LOCK_NB)
        except BlockingIOError:
            if handle is not None and not handle.closed:
                handle.close()
            continue
        except OSError as error:
            if handle is not None and not handle.closed:
                handle.close()
            message = f"cannot inspect superseded lintmax-py toolchain generation {generation}: {error}"
            raise ToolchainUnavailableError(message) from error
        try:
            shutil.rmtree(generation)
        except OSError as error:
            message = f"cannot reap superseded lintmax-py toolchain generation {generation}: {error}"
            raise ToolchainUnavailableError(message) from error
        finally:
            if handle is not None:
                handle.close()


def _install(uvx: UvxLauncher, package: str, generation: Path) -> None:
    command = [
        *uvx.command(),
        "tool",
        "install",
        "--force",
        "--quiet",
        f"{package}@latest",
    ]
    result = run(
        command,
        timeout=900,
        env=_tool_environment(generation),
    )
    if result.code != 0:
        context = f"uv could not install managed tool {package}@latest"
        raise _failure(context, result)


def _missing_tool_error(package: str, expected: Path) -> ToolchainUnavailableError:
    message = f"managed tool {package!r} did not provide expected executable {expected}"
    return ToolchainUnavailableError(message)


def _version(package: str, executable: str, generation: Path) -> Tool:
    launcher = generation / "bin" / executable
    try:
        resolved = launcher.resolve(strict=True)
    except OSError as error:
        message = f"cannot resolve managed executable {launcher}: {error}"
        raise ToolchainUnavailableError(message) from error
    package_root = generation.resolve() / "tools" / package
    if not _inside(resolved, package_root):
        message = f"managed executable {launcher} resolves outside managed package {package!r}: {resolved}"
        raise ToolchainUnavailableError(message)
    if not resolved.is_file() or not os.access(resolved, os.X_OK):
        raise _missing_tool_error(package, launcher)
    result = run([str(resolved), "--version"], timeout=60)
    if result.code != 0 or not result.out:
        context = f"managed executable {resolved} could not report its version"
        raise _failure(context, result)
    return Tool(
        package=package,
        executable=executable,
        path=resolved,
        version=result.out.splitlines()[0],
    )


def _snapshot(uvx: UvxLauncher, generation: Path) -> Toolchain:
    lease = _lease(generation)
    try:
        selected = {executable: _version(package, executable, generation) for package, executable in TOOLS.items()}
        zsh = SYSTEM_ZSH if SYSTEM_ZSH.is_file() and os.access(SYSTEM_ZSH, os.X_OK) else None
        return Toolchain(
            tools=MappingProxyType(selected),
            generation=generation.resolve(),
            uvx=uvx,
            zsh=zsh,
            lease=lease,
        )
    except BaseException as error:
        _preserve_primary_error(
            error,
            lease.close,
            f"releasing the failed toolchain generation lease {generation}",
        )
        raise


def _bootstrap(uvx: UvxLauncher, root: Path) -> Toolchain:
    generation = root / f"generation-{uuid.uuid4().hex}"
    try:
        generation.mkdir(mode=0o700)
    except OSError as error:
        message = f"cannot create temporary lintmax-py generation {generation}: {error}"
        raise ToolchainUnavailableError(message) from error
    try:
        for package in TOOLS:
            _install(uvx, package, generation)
        return _snapshot(uvx, generation)
    except BaseException as error:
        _preserve_primary_error(
            error,
            lambda: _remove_generation(generation),
            f"removing unpublished toolchain generation {generation}",
        )
        raise


def ensure() -> Toolchain:
    """Return a private immutable generation of all analyzers for one gate invocation.

    Returns:
        Absolute executable paths and observed versions from one published generation.

    """
    _locking()
    uvx = _capture_uvx()
    root = cache_root()
    with _publish_lock(root):
        generation = _current_generation(root) if fresh() else None
        if generation is not None:
            return _snapshot(uvx, generation)
        snapshot = _bootstrap(uvx, root)
        published = False
        try:
            _publish(root, snapshot.generation)
            published = True
            _reap_generations(root, snapshot.generation)
            mark()
        except BaseException as error:
            _preserve_primary_error(
                error,
                snapshot.close,
                f"releasing failed toolchain generation {snapshot.generation}",
            )
            if not published:
                _preserve_primary_error(
                    error,
                    lambda: _remove_generation(snapshot.generation),
                    f"removing unpublished toolchain generation {snapshot.generation}",
                )
            raise
        return snapshot
