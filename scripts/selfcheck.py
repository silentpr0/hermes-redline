#!/usr/bin/env python3
"""Minimal cross-surface extension and Windows-path regression check."""
import ast
import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load_plugin_api():
    if "fastapi" not in sys.modules:
        fastapi = types.ModuleType("fastapi")

        class HTTPException(Exception):
            def __init__(self, status_code, detail=""):
                self.status_code = status_code
                self.detail = detail

        class APIRouter:
            def get(self, *_args, **_kwargs):
                def decorator(fn):
                    return fn

                return decorator

            def post(self, *_args, **_kwargs):
                return self.get

        fastapi.HTTPException = HTTPException
        fastapi.APIRouter = APIRouter
        fastapi.Query = lambda *_args, **_kwargs: None
        sys.modules["fastapi"] = fastapi

    spec = importlib.util.spec_from_file_location("redline_api", ROOT / "dashboard/plugin_api.py")
    assert spec is not None and spec.loader is not None
    api = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(api)
    return api


def _load_workspace_policy():
    name = "redline_workspace_policy"
    existing = sys.modules.get(name)
    if existing is not None:
        return existing
    spec = importlib.util.spec_from_file_location(name, ROOT / "dashboard/workspace_policy.py")
    assert spec is not None and spec.loader is not None
    wp = importlib.util.module_from_spec(spec)
    sys.modules[name] = wp
    spec.loader.exec_module(wp)
    return wp


def _temp_parent_outside_hermes(api) -> Path:
    hh = api._hermes_home()
    for candidate in (Path("/tmp"), Path("/var/tmp"), Path.home()):
        try:
            resolved = candidate.expanduser().resolve()
        except OSError:
            continue
        try:
            resolved.relative_to(hh)
        except ValueError:
            return resolved
    raise AssertionError("could not find temp parent outside HERMES_HOME")


def python_extensions(path: Path) -> tuple[str, ...]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "_CODE_EXT" for target in node.targets
        ):
            return tuple(ast.literal_eval(node.value))
    raise AssertionError(f"_CODE_EXT missing from {path}")


def main() -> None:
    js = """const fs=require('fs');const s=fs.readFileSync(process.argv[1],'utf8');const m=s.match(/const CODE_EXT = (\\[[\\s\\S]*?\\])/);if(!m)throw Error('CODE_EXT missing');console.log(JSON.stringify(Function('return '+m[1])()));"""
    frontend = tuple(json.loads(subprocess.check_output(["node", "-e", js, str(ROOT / "desktop/plugin.js")], text=True)))
    backend = python_extensions(ROOT / "dashboard/plugin_api.py")
    hooks = python_extensions(ROOT / "__init__.py")
    assert frontend == backend == hooks, (frontend, backend, hooks)

    spec = importlib.util.spec_from_file_location("redline_hooks", ROOT / "__init__.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module._skip_path(r"C:\\Users\\x\\.hermes\\cache\\y.py")
    assert not module._skip_path("/home/x/note.py")

    api = _load_plugin_api()
    wp = api.wp
    wp.clear_agent_paths()

    temp_parent = _temp_parent_outside_hermes(api)
    old_cwd = os.getcwd()
    old_tmpdir = os.environ.get("TMPDIR")
    old_roots = os.environ.get("REDLINE_WORKSPACE_ROOTS")
    old_include_cwd = os.environ.get("REDLINE_INCLUDE_GATEWAY_CWD")
    old_allow_sensitive = os.environ.get("REDLINE_ALLOW_SENSITIVE_PATHS")
    old_allow_hermes = os.environ.get("REDLINE_ALLOW_HERMES_HOME")
    old_hermes_home = os.environ.get("HERMES_HOME")
    old_agent_envs = {name: os.environ.get(name) for name in wp._HERMES_WORKSPACE_ENVS}

    try:
        os.environ["TMPDIR"] = str(temp_parent)
        with tempfile.TemporaryDirectory(dir=temp_parent) as workspace:
            ws = Path(workspace).resolve()
            project = ws / "Desktop" / "project"
            project.mkdir(parents=True)
            doc = project / "report.md"
            doc.write_text("# hello\n", encoding="utf-8")
            secret = project / "auth.json"
            secret.write_text("{}", encoding="utf-8")

            gateway_cwd = ws / "gateway"
            gateway_cwd.mkdir()
            os.chdir(gateway_cwd)
            os.environ.pop("REDLINE_WORKSPACE_ROOTS", None)
            os.environ.pop("REDLINE_INCLUDE_GATEWAY_CWD", None)
            os.environ.pop("REDLINE_ALLOW_SENSITIVE_PATHS", None)
            os.environ.pop("REDLINE_ALLOW_HERMES_HOME", None)
            for name in wp._HERMES_WORKSPACE_ENVS:
                os.environ.pop(name, None)
            wp.clear_agent_paths()

            try:
                api._resolve(str(doc))
            except api.HTTPException as exc:
                assert exc.status_code == 403
            else:
                raise AssertionError("expected doc outside gateway cwd to be blocked before registration")

            # (1) the exact file the agent wrote is allowed for the writing session
            wp.register_agent_path(str(doc), "session-a")
            assert api._resolve(str(doc)) == doc
            assert wp.is_granted(Path(str(doc) + wp.SIDECAR_SUFFIX))

            # (2) a sibling in the same directory was never granted and stays denied
            sibling = project / "unrelated.md"
            sibling.write_text("# sibling\n", encoding="utf-8")
            assert not wp.is_granted(Path(str(sibling) + wp.SIDECAR_SUFFIX))
            try:
                api._resolve(str(sibling))
            except api.HTTPException as exc:
                assert exc.status_code == 403
            else:
                raise AssertionError("expected an unregistered sibling to be blocked")

            # (3) the grant dies with its session
            wp.release_session("session-a")
            assert not wp.is_granted(doc)
            try:
                api._resolve(str(doc))
            except api.HTTPException as exc:
                assert exc.status_code == 403
            else:
                raise AssertionError("expected access to be denied after the session ended")

            # (4) plugins.isolation: host — the hook's registry is in another process,
            # so grants do not cross; configured roots remain the way in.
            iso_spec = importlib.util.spec_from_file_location(
                "redline_workspace_policy_iso", ROOT / "dashboard/workspace_policy.py")
            assert iso_spec is not None and iso_spec.loader is not None
            isolated = importlib.util.module_from_spec(iso_spec)
            iso_spec.loader.exec_module(isolated)
            isolated.register_agent_path(str(doc), "session-host")
            assert not wp.is_granted(doc)
            try:
                api._resolve(str(doc))
            except api.HTTPException as exc:
                assert exc.status_code == 403
            else:
                raise AssertionError("expected an isolated hook's grant not to reach the API")
            os.environ["REDLINE_WORKSPACE_ROOTS"] = str(project)
            assert api._resolve(str(doc)) == doc
            os.environ.pop("REDLINE_WORKSPACE_ROOTS", None)
            isolated.release_session("session-host")

            try:
                api._resolve(str(secret))
            except api.HTTPException as exc:
                assert exc.status_code == 403
            else:
                raise AssertionError("expected sensitive path to be blocked")

            # (5) end to end: the hook's grant is honoured by the API in-process,
            # because both load the policy module under the same name.
            with tempfile.TemporaryDirectory(dir=temp_parent) as wired_dir:
                wired = Path(wired_dir).resolve() / "wired.md"
                wired.write_text("# wired\n" + "text\n" * 60, encoding="utf-8")
                module._on_session_end("session-wired")
                wp.clear_agent_paths()
                try:
                    api._resolve(str(wired))
                except api.HTTPException as exc:
                    assert exc.status_code == 403
                else:
                    raise AssertionError("expected no access before the hook grants it")
                module._post_tool_call("write_file", {"path": str(wired)}, None, session_id="session-wired")
                assert api._resolve(str(wired)) == wired
                module._on_session_end("session-wired")
                try:
                    api._resolve(str(wired))
                except api.HTTPException as exc:
                    assert exc.status_code == 403
                else:
                    raise AssertionError("expected on_session_end to drop the hook grant")

            outside = temp_parent / "redline-outside-target.md"
            outside.write_text("# x\n", encoding="utf-8")
            try:
                api._resolve(str(outside))
            except api.HTTPException as exc:
                assert exc.status_code == 403
            else:
                raise AssertionError("expected path outside workspace to be blocked")

            link = project / "escape.md"
            link.symlink_to(outside)
            try:
                api._resolve(str(link))
            except api.HTTPException as exc:
                assert exc.status_code == 403
            else:
                raise AssertionError("expected symlink escape outside roots to be blocked")
            finally:
                link.unlink(missing_ok=True)
                outside.unlink(missing_ok=True)

            os.environ["HERMES_WORKSPACE"] = str(project)
            wp.clear_agent_paths()
            assert api._resolve(str(doc)) == doc

            with tempfile.TemporaryDirectory(dir=temp_parent) as hermes_dir:
                hh = Path(hermes_dir).resolve()
                os.environ["HERMES_HOME"] = str(hh)
                cfg = hh / "config.yaml"
                cfg.write_text("x: 1\n", encoding="utf-8")
                os.environ["REDLINE_WORKSPACE_ROOTS"] = str(hh)
                wp.clear_agent_paths()
                try:
                    api._resolve(str(cfg))
                except api.HTTPException as exc:
                    assert exc.status_code == 403
                else:
                    raise AssertionError("expected HERMES_HOME path to be blocked")
                os.environ["REDLINE_ALLOW_HERMES_HOME"] = "1"
                assert api._resolve(str(cfg)) == cfg
    finally:
        wp.clear_agent_paths()
        os.chdir(old_cwd)
        if old_tmpdir is None:
            os.environ.pop("TMPDIR", None)
        else:
            os.environ["TMPDIR"] = old_tmpdir
        if old_roots is None:
            os.environ.pop("REDLINE_WORKSPACE_ROOTS", None)
        else:
            os.environ["REDLINE_WORKSPACE_ROOTS"] = old_roots
        if old_include_cwd is None:
            os.environ.pop("REDLINE_INCLUDE_GATEWAY_CWD", None)
        else:
            os.environ["REDLINE_INCLUDE_GATEWAY_CWD"] = old_include_cwd
        if old_allow_sensitive is None:
            os.environ.pop("REDLINE_ALLOW_SENSITIVE_PATHS", None)
        else:
            os.environ["REDLINE_ALLOW_SENSITIVE_PATHS"] = old_allow_sensitive
        if old_allow_hermes is None:
            os.environ.pop("REDLINE_ALLOW_HERMES_HOME", None)
        else:
            os.environ["REDLINE_ALLOW_HERMES_HOME"] = old_allow_hermes
        if old_hermes_home is None:
            os.environ.pop("HERMES_HOME", None)
        else:
            os.environ["HERMES_HOME"] = old_hermes_home
        for name, value in old_agent_envs.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value

    print("redline selfcheck: ok")


if __name__ == "__main__":
    main()
