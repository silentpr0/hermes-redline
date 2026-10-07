"""Redline backend: read Markdown files and persist annotation sidecars.

Mounted at /api/plugins/redline/ when the dashboard plugin is discovered.
"""
import json
import os
import tempfile
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query

router = APIRouter()

MAX_BYTES = 1_000_000
_MD_EXT = {".md", ".markdown"}


def _resolve(path: str) -> Path:
    # resolve() first: a symlink named .md must not smuggle a non-markdown target
    try:
        p = Path(os.path.expanduser(str(path).strip())).resolve(strict=True)
    except OSError as exc:
        raise HTTPException(404, f"file not found: {path}") from exc
    if p.suffix.lower() not in _MD_EXT:
        raise HTTPException(400, "redline reads .md/.markdown files only")
    if not p.is_file():
        raise HTTPException(404, f"not a file: {p}")
    if p.stat().st_size > MAX_BYTES:
        raise HTTPException(413, "file too large for redline")
    return p


def _sidecar(p: Path) -> Path:
    return p.with_suffix(p.suffix + ".redline.json")


def _read_sidecar(sc: Path) -> list:
    try:
        items = json.loads(sc.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HTTPException(500, f"sidecar is not valid JSON: {sc}") from exc
    if not isinstance(items, list):
        raise HTTPException(500, f"sidecar must contain a JSON list: {sc}")
    return items


def _write_sidecar(sc: Path, items: list) -> None:
    payload = json.dumps(items, ensure_ascii=False, indent=2)
    # ponytail: replace is atomic on one filesystem; add locking only if concurrent editors matter.
    fd, temp_path = tempfile.mkstemp(prefix=f".{sc.name}.", suffix=".tmp", dir=sc.parent, text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(payload)
        os.replace(temp_path, sc)
    except BaseException:
        try:
            os.unlink(temp_path)
        except FileNotFoundError:
            pass
        raise


@router.get("/doc")
def read_doc(path: str = Query(...)):
    p = _resolve(path)
    return {"path": str(p), "content": p.read_text(encoding="utf-8", errors="replace")}


@router.get("/annotations")
def get_annotations(path: str = Query(...)):
    sc = _sidecar(_resolve(path))
    return {"items": [] if not sc.is_file() else _read_sidecar(sc)}


@router.post("/annotations")
def save_annotations(body: dict):
    p = _resolve(str(body.get("path", "")))
    items = body.get("items")
    if not isinstance(items, list):
        raise HTTPException(400, "items must be a list")
    if len(items) > 200 or len(json.dumps(items)) > 512_000:
        raise HTTPException(413, "too many/too large annotations")
    _write_sidecar(_sidecar(p), items)
    return {"ok": True, "count": len(items)}
