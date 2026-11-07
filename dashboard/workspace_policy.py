"""Shared workspace allowlist for redline backend reads and sidecar writes.

Two independent sources grant the backend access:

* **configured roots** — ``REDLINE_WORKSPACE_ROOTS``, the Hermes workspace env vars,
  and (only when nothing else is configured) the gateway cwd. These are directory
  trees and they survive sessions and gateway restarts.
* **agent grants** — exactly the resolved review target the agent wrote with
  ``write_file``/``patch``, plus that file's own ``<file><ext>.redline.json``
  sidecar. Grants are remembered per session and dropped when the session ends.
  There are no directory grants: writing ``Desktop/project/report.md`` authorizes
  that file, never ``Desktop/project/``.

With ``plugins.isolation: host`` the hook and the dashboard API do not share module
state, so agent grants never cross that boundary; configured roots are the route
there. The README documents this.
"""
from __future__ import annotations

import os
import threading
from pathlib import Path

_WORKSPACE_ROOTS_ENV = "REDLINE_WORKSPACE_ROOTS"
_INCLUDE_GATEWAY_CWD_ENV = "REDLINE_INCLUDE_GATEWAY_CWD"
_HERMES_WORKSPACE_ENVS = (
    "HERMES_WORKSPACE",
    "HERMES_AGENT_CWD",
    "HERMES_PROJECT_ROOT",
    "WORKSPACE",
)

# The sidecar suffix the pane and the agent write next to a reviewed file.
SIDECAR_SUFFIX = ".redline.json"

# A hook call without a session id still has to be revocable, so it lands in one
# shared bucket that ``release_session()`` with an empty id removes again.
_NO_SESSION = "-"
_MAX_GRANTED_FILES_PER_SESSION = 64
_MAX_GRANT_SESSIONS = 64

_grants_lock = threading.Lock()
_agent_grants: dict[str, set[str]] = {}


def _resolved(raw: object) -> Path | None:
    try:
        return Path(os.path.expanduser(str(raw).strip())).resolve()
    except (OSError, RuntimeError, ValueError):
        return None


def register_agent_path(path: str, session_id: str = "") -> None:
    """Authorize exactly one review target for the session that wrote it."""
    resolved = _resolved(path)
    if resolved is None:
        return
    key = session_id or _NO_SESSION
    with _grants_lock:
        files = _agent_grants.setdefault(key, set())
        if len(files) < _MAX_GRANTED_FILES_PER_SESSION:
            files.add(str(resolved))
        while len(_agent_grants) > _MAX_GRANT_SESSIONS:
            _agent_grants.pop(next(iter(_agent_grants)))


def release_session(session_id: str = "") -> None:
    """Drop every grant the session accumulated (called from ``on_session_end``)."""
    with _grants_lock:
        _agent_grants.pop(session_id or _NO_SESSION, None)


def clear_agent_paths() -> None:
    """Test helper: forget every agent grant."""
    with _grants_lock:
        _agent_grants.clear()


def granted_paths() -> frozenset[str]:
    """Every exact file currently authorized by a live session."""
    with _grants_lock:
        if not _agent_grants:
            return frozenset()
        merged: set[str] = set()
        for files in _agent_grants.values():
            merged |= files
        return frozenset(merged)


def is_granted(path: Path) -> bool:
    """True for a granted file, and for the sidecar derived from it."""
    key = str(path)
    granted = granted_paths()
    if key in granted:
        return True
    if key.endswith(SIDECAR_SUFFIX):
        return key[: -len(SIDECAR_SUFFIX)] in granted
    return False


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
    """The configured directory roots, for messages and diagnostics."""
    return configured_workspace_roots()


def under_root(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def in_workspace(path: Path) -> bool:
    if is_granted(path):
        return True
    return any(under_root(path, root) for root in configured_workspace_roots())
