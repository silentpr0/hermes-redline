"""Redline agent-side hooks: make the ::redline{...} card automatic.

post_tool_call  — remember Markdown/source files this agent turn wrote (write_file/patch).
transform_llm_output — if the final response delivered a reviewable file
and the agent did not emit a ::redline directive itself, append one (desktop only).

Observer/transform only; no core overrides. Fail-soft by design: any error here
must never affect the response.
"""
from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path, PurePosixPath

_DIRECTIVE_RE = re.compile(r"::redline\{")
_MD_EXT = {".md", ".markdown"}
_CODE_EXT = (".py", ".sh", ".js", ".ts", ".tsx", ".c", ".h", ".cpp", ".go", ".rs", ".rb",
             ".yaml", ".yml", ".json", ".toml", ".sql")
# ponytail: path heuristics instead of a config knob; add config_schema if users want opt-out granularity.
_MIN_BYTES = 200

_written: dict[str, str] = {}


def _register_review_root(path: str) -> None:
    try:
        policy_path = Path(__file__).resolve().parent / "dashboard" / "workspace_policy.py"
        name = "redline_workspace_policy"
        mod = sys.modules.get(name)
        if mod is None:
            spec = importlib.util.spec_from_file_location(name, policy_path)
            if spec is None or spec.loader is None:
                return
            mod = importlib.util.module_from_spec(spec)
            sys.modules[name] = mod
            spec.loader.exec_module(mod)
        mod.register_agent_path(path)
    except Exception:
        pass


def _skip_path(path: str | Path) -> bool:
    parts = tuple(part.lower() for part in PurePosixPath(str(path).replace("\\", "/")).parts)
    return (
        any(parts[i:i + 2] == (".hermes", "cache") for i in range(len(parts) - 1))
        or "skills" in parts
        or ".git" in parts
        or bool(parts and parts[-1].endswith(".redline.json"))
    )


def _eligible(path: str) -> bool:
    try:
        p = Path(path).expanduser()
    except Exception:
        return False
    ext = p.suffix.lower()
    if ext not in _MD_EXT and ext not in _CODE_EXT:
        return False
    if _skip_path(path):
        return False
    if p.name.lower() in {"readme.md", "skill.md", "agents.md", "changelog.md"}:
        return False
    try:
        if not p.is_file() or p.stat().st_size < (_MIN_BYTES if ext in _MD_EXT else 40):
            return False
    except OSError:
        return False
    return True


def _post_tool_call(tool_name: str, args: dict, result, session_id: str = "", **kwargs):
    try:
        # post_tool_call dispatch (model_tools.py) carries no platform kwarg; gating it here
        # would disable tracking even on desktop. The leak gate is in _transform_llm_output,
        # which does receive platform (turn_finalizer.py). State is bounded + cleared on session end.
        if tool_name not in {"write_file", "patch"}:
            return
        path = (args or {}).get("path") or ""
        if path and _eligible(path):
            resolved = str(Path(path).expanduser().resolve())
            _written[session_id or "_"] = resolved
            _register_review_root(resolved)
    except Exception:
        pass  # observers must never break a turn


def _transform_llm_output(response_text: str, session_id: str = "", **kwargs):
    try:
        if kwargs.get("platform") != "desktop" or not response_text or _DIRECTIVE_RE.search(response_text):
            return None
        path = _written.pop(session_id or "_", None)
        if not path:
            return None
        return response_text + f"\n\n::redline{{file={json.dumps(path)}}}"
    except Exception:
        return None  # fail-soft: never touch the response on error


def _on_session_end(session_id: str = "", **kwargs):
    try:
        _written.pop(session_id or "_", None)
    except Exception:
        pass  # observers must never break a turn


def register(ctx):
    ctx.register_hook("post_tool_call", _post_tool_call)
    ctx.register_hook("transform_llm_output", _transform_llm_output)
    ctx.register_hook("on_session_end", _on_session_end)
    skill_md = Path(__file__).resolve().parent / "SKILL.md"
    if skill_md.is_file():
        ctx.register_skill(
            "reading", skill_md,
            description="Use when a redline batch arrives from the desktop panel, or after delivering a Markdown document or source file the user will review.",
        )
