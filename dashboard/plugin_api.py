"""Redline backend: read Markdown/code files and persist annotation sidecars.

Mounted at /api/plugins/redline/ when the dashboard plugin is discovered.
Code files are lexed with Pygments (already in the gateway venv) into a flat
token list the desktop pane renders; any lexer failure degrades to plain text.
"""
import json
import os
import tempfile
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query

try:  # Pygments ships in the gateway venv transitively (via rich/pytest); a
# minimal install may lack it — then code renders as plain text, never 500.
    from pygments import lex
    from pygments.lexers import TextLexer, get_lexer_for_filename
    from pygments.util import ClassNotFound
    _HAVE_PYGMENTS = True
except ImportError:
    _HAVE_PYGMENTS = False
    lex = TextLexer = get_lexer_for_filename = None
    ClassNotFound = Exception

router = APIRouter()

MAX_BYTES = 1_000_000
# Comma- or OS-pathsep-separated extra workspace roots (expanded, resolved).
_WORKSPACE_ROOTS_ENV = "REDLINE_WORKSPACE_ROOTS"
_ALLOW_HERMES_HOME_ENV = "REDLINE_ALLOW_HERMES_HOME"
_ALLOW_SENSITIVE_ENV = "REDLINE_ALLOW_SENSITIVE_PATHS"
_SENSITIVE_NAMES = frozenset(
    {
        ".env",
        "auth.json",
        "credentials.json",
        "secrets.json",
        "id_rsa",
        "id_dsa",
        "id_ecdsa",
        "id_ed25519",
    }
)
_SENSITIVE_SUFFIXES = (".pem", ".key", ".p12", ".pfx")
MAX_TOKENS = 200_000
_MD_EXT = {".md", ".markdown"}
_CODE_EXT = (".py", ".sh", ".js", ".ts", ".tsx", ".c", ".h", ".cpp", ".go", ".rs", ".rb",
             ".yaml", ".yml", ".json", ".toml", ".sql")

# Pygments token dotted name -> redline CSS class; walk prefixes so
# Token.Keyword.Constant -> Keyword, Token.Name.Function -> Name.Function.
# Unmapped types render plain.
_TOKEN_CLASS = {
    "Keyword": "kw", "Name.Function": "fn", "Name.Class": "typ",
    "String": "str", "Comment": "com", "Number": "num",
    "Operator": "op", "Name.Decorator": "dec",
}


def _token_class(ttype) -> str:
    s = str(ttype)  # canonical dotted name, e.g. Token.Literal.String.Doc
    for key, cls in _TOKEN_CLASS.items():
        if ("." + key + ".") in s or s.endswith("." + key):
            return cls
    return ""


def _tokens(p: Path, content: str) -> list:
    if not _HAVE_PYGMENTS:
        return []
    try:
        lexer = get_lexer_for_filename(p.name, text=content, stripnl=False,
                                        ensurenl=False, encoding="utf-8")
    except (ClassNotFound, Exception):
        lexer = TextLexer(stripnl=False, ensurenl=False)
    out = []
    try:
        for ttype, value in lex(content, lexer):
            cls = _token_class(ttype)
            if out and out[-1][0] == cls:
                out[-1][1] += value
            else:
                out.append([cls, value])
            if len(out) > MAX_TOKENS:
                return []  # pathological file: pane falls back to plain content
    except Exception:
        return []
    return out


def _truthy_env(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _hermes_home() -> Path:
    return Path(os.environ.get("HERMES_HOME", Path.home() / ".hermes")).expanduser().resolve()


def _workspace_roots() -> list[Path]:
    roots: list[Path] = []
    seen: set[str] = set()
    for raw in (os.getcwd(), *os.environ.get(_WORKSPACE_ROOTS_ENV, "").replace(",", os.pathsep).split(os.pathsep)):
        part = str(raw).strip()
        if not part:
            continue
        try:
            root = Path(part).expanduser().resolve()
        except OSError:
            continue
        key = str(root)
        if key not in seen:
            seen.add(key)
            roots.append(root)
    return roots


def _under_root(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _in_workspace(path: Path) -> bool:
    return any(_under_root(path, root) for root in _workspace_roots())


def _under_hermes_home(path: Path) -> bool:
    return _under_root(path, _hermes_home())


def _is_sensitive_path(path: Path) -> bool:
    name = path.name.lower()
    if name in _SENSITIVE_NAMES or name.startswith(".env."):
        return True
    if name.startswith("id_rsa") or name.startswith("id_dsa"):
        return True
    return name.endswith(_SENSITIVE_SUFFIXES)


def _assert_workspace_access(path: Path) -> None:
    if not _in_workspace(path):
        raise HTTPException(403, "path is outside redline workspace roots")
    if _under_hermes_home(path) and not _truthy_env(_ALLOW_HERMES_HOME_ENV):
        raise HTTPException(403, "paths under HERMES_HOME are blocked by redline policy")
    if _is_sensitive_path(path) and not _truthy_env(_ALLOW_SENSITIVE_ENV):
        raise HTTPException(403, "sensitive path blocked by redline policy")


def _resolve(path: str) -> Path:
    # resolve() first: a symlink named .md must not smuggle a non-markdown target
    try:
        p = Path(os.path.expanduser(str(path).strip())).resolve(strict=True)
    except OSError as exc:
        raise HTTPException(404, f"file not found: {path}") from exc
    if p.suffix.lower() not in (_MD_EXT | set(_CODE_EXT)):
        raise HTTPException(400, "redline reads Markdown and source files only")
    if not p.is_file():
        raise HTTPException(404, f"not a file: {p}")
    if p.stat().st_size > MAX_BYTES:
        raise HTTPException(413, "file too large for redline")
    _assert_workspace_access(p)
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
    content = p.read_text(encoding="utf-8", errors="replace").replace("\r\n", "\n")
    tokens = _tokens(p, content) if p.suffix.lower() in _CODE_EXT else []
    return {"path": str(p), "content": content, "tokens": tokens}


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
