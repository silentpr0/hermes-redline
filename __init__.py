"""Redline agent-side hooks: make the ::redline{...} card automatic.

post_tool_call  — remember Markdown files this agent turn wrote (write_file/patch).
transform_llm_output — if the final response delivered a reviewable Markdown file
and the agent did not emit a ::redline directive itself, append one.

Observer/transform only; no core overrides. Fail-soft by design: any error here
must never affect the response.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

_DIRECTIVE_RE = re.compile(r"::redline\{")
_MD_EXT = {".md", ".markdown"}
# ponytail: path heuristics instead of a config knob; add config_schema if users want opt-out granularity.
_SKIP_SUBSTRINGS = ("/.hermes/cache/", "/.redline.json", "/skills/", "/.git/")
_MIN_BYTES = 200

_written: dict[str, str] = {}


def _eligible(path: str) -> bool:
    try:
        p = Path(path).expanduser()
    except Exception:
        return False
    if p.suffix.lower() not in _MD_EXT:
        return False
    s = str(p)
    if any(sub in s for sub in _SKIP_SUBSTRINGS):
        return False
    if p.name.lower() in {"readme.md", "skill.md", "agents.md", "changelog.md"}:
        return False
    try:
        if not p.is_file() or p.stat().st_size < _MIN_BYTES:
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
            _written[session_id or "_"] = str(Path(path).expanduser().resolve())
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
            description="Use when a redline batch arrives from the desktop panel, or after delivering a Markdown document the user will read.",
        )
