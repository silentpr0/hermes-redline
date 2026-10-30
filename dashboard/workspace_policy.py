"""Shared workspace allowlist for redline backend reads and sidecar writes."""
from __future__ import annotations

import os
from pathlib import Path

_WORKSPACE_ROOTS_ENV = "REDLINE_WORKSPACE_ROOTS"
_INCLUDE_GATEWAY_CWD_ENV = "REDLINE_INCLUDE_GATEWAY_CWD"
_HERMES_WORKSPACE_ENVS = (
    "HERMES_WORKSPACE",
    "HERMES_AGENT_CWD",
    "HERMES_PROJECT_ROOT",
    "WORKSPACE",
)

_agent_roots: set[str] = set()


def register_agent_path(path: str) -> None:
    """Remember the parent directory of a file the agent wrote this gateway lifetime."""
    try:
        parent = Path(os.path.expanduser(str(path).strip())).expanduser().resolve().parent
    except OSError:
        return
    _agent_roots.add(str(parent))


def clear_agent_roots() -> None:
    """Test helper."""
    _agent_roots.clear()


def agent_roots() -> tuple[Path, ...]:
    out: list[Path] = []
    for raw in _agent_roots:
        try:
            out.append(Path(raw))
        except OSError:
            continue
    return tuple(out)


def _truthy_env(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _add_root(raw: str, roots: list[Path], seen: set[str]) -> None:
    part = str(raw).strip()
    if not part:
        return
    try:
        root = Path(part).expanduser().resolve()
    except OSError:
        return
    key = str(root)
    if key not in seen:
        seen.add(key)
        roots.append(root)


def configured_workspace_roots() -> list[Path]:
    """Explicit and gateway-provided roots (never the whole filesystem)."""
    roots: list[Path] = []
    seen: set[str] = set()
    extra = os.environ.get(_WORKSPACE_ROOTS_ENV, "").replace(",", os.pathsep)
    for part in extra.split(os.pathsep):
        _add_root(part, roots, seen)
    for name in _HERMES_WORKSPACE_ENVS:
        _add_root(os.environ.get(name, ""), roots, seen)
    if _truthy_env(_INCLUDE_GATEWAY_CWD_ENV) or not roots:
        _add_root(os.getcwd(), roots, seen)
    return roots


def all_workspace_roots() -> list[Path]:
    roots = configured_workspace_roots()
    seen = {str(root) for root in roots}
    for root in agent_roots():
        key = str(root)
        if key not in seen:
            seen.add(key)
            roots.append(root)
    return roots


def under_root(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def in_workspace(path: Path) -> bool:
    return any(under_root(path, root) for root in all_workspace_roots())
