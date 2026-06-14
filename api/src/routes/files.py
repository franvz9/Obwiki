from __future__ import annotations
from ..paths import INBOX_DIR

import shutil
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from pydantic import BaseModel

from ..services.kb_registry import KBRegistry
from ..services.scanner import Scanner
from ..deps import get_registry, get_scanner

router = APIRouter(prefix="/v1", tags=["files"])


class WritePageRequest(BaseModel):
    path: str
    content: str
    frontmatter: dict = {}


class SearchRequest(BaseModel):
    query: str
    limit: int = 20
    offset: int = 0


class ImportFolderRequest(BaseModel):
    source_path: str


class ImportFileRequest(BaseModel):
    name: str
    content: str           # plain text or base64-encoded binary
    encoding: str = "text" # "text" | "base64"


@router.post("/kbs/{kb_id}/import/files")
async def import_files(
    kb_id: str,
    files: list[UploadFile] = File(...),
    registry: KBRegistry = Depends(get_registry),
):
    kb = await registry.get(kb_id)
    if kb is None:
        raise HTTPException(404, "knowledge base not found")

    raw_dir = Path(kb.root_path) / INBOX_DIR
    raw_dir.mkdir(parents=True, exist_ok=True)

    imported = []
    for f in files:
        content = await f.read()
        dest = raw_dir / (f.filename or "unnamed.md")
        dest.write_bytes(content)
        imported.append(str(dest.relative_to(kb.root_path)))

    return {"imported": imported, "count": len(imported)}


@router.post("/kbs/{kb_id}/import/folder")
async def import_folder(
    kb_id: str,
    source_path: str = Form(None),
    registry: KBRegistry = Depends(get_registry),
):
    """Import a folder into 01_raw. Supports both Form and JSON body."""
    kb = await registry.get(kb_id)
    if kb is None:
        raise HTTPException(404, "knowledge base not found")

    src = Path(source_path)
    if not src.exists():
        raise HTTPException(400, f"source path does not exist: {source_path}")

    raw_dir = Path(kb.root_path) / INBOX_DIR
    raw_dir.mkdir(parents=True, exist_ok=True)

    count = 0
    for md_file in src.rglob("*.md"):
        rel = md_file.relative_to(src)
        dest = raw_dir / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(md_file, dest)
        count += 1

    return {"imported": count, "source": source_path}


@router.post("/kbs/{kb_id}/import/folder-json")
async def import_folder_json(
    kb_id: str,
    body: ImportFolderRequest,
    registry: KBRegistry = Depends(get_registry),
):
    """JSON variant for MCP/non-browser clients."""
    kb = await registry.get(kb_id)
    if kb is None:
        raise HTTPException(404, "knowledge base not found")

    src = Path(body.source_path)
    if not src.exists():
        raise HTTPException(400, f"source path does not exist: {body.source_path}")

    raw_dir = Path(kb.root_path) / INBOX_DIR
    raw_dir.mkdir(parents=True, exist_ok=True)

    count = 0
    for md_file in src.rglob("*.md"):
        rel = md_file.relative_to(src)
        dest = raw_dir / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(md_file, dest)
        count += 1

    return {"imported": count, "source": body.source_path}


@router.get("/kbs/{kb_id}/tree")
async def get_tree(
    kb_id: str,
    registry: KBRegistry = Depends(get_registry),
    scanner: Scanner = Depends(get_scanner),
):
    kb = await registry.get(kb_id)
    if kb is None:
        raise HTTPException(404, "knowledge base not found")
    return await scanner.get_tree(kb_id, kb.root_path)


@router.get("/files/{kb_id}/{path:path}")
async def read_file(
    kb_id: str,
    path: str,
    registry: KBRegistry = Depends(get_registry),
):
    """Read a file from the knowledge base by relative path."""
    kb = await registry.get(kb_id)
    if kb is None:
        raise HTTPException(404, "knowledge base not found")

    file_path = Path(kb.root_path) / path
    if not file_path.exists():
        raise HTTPException(404, f"file not found: {path}")

    try:
        content = file_path.read_text(encoding="utf-8")
        return {
            "path": path,
            "content": content,
            "size": len(content),
        }
    except UnicodeDecodeError:
        raise HTTPException(400, "binary file not supported")


@router.post("/kbs/{kb_id}/import/upload")
async def import_upload(
    kb_id: str,
    file: UploadFile = File(...),
    registry: KBRegistry = Depends(get_registry),
):
    """Multipart upload for large binary files (PDF, DOCX, etc)."""
    kb = await registry.get(kb_id)
    if kb is None:
        raise HTTPException(404, "knowledge base not found")
    raw_dir = Path(kb.root_path) / INBOX_DIR
    raw_dir.mkdir(parents=True, exist_ok=True)
    content = await file.read()
    dest = raw_dir / (file.filename or "unnamed.bin")
    dest.write_bytes(content)
    return {"imported": str(dest.relative_to(kb.root_path)), "size": len(content)}


@router.post("/kbs/{kb_id}/import/file-content")
async def import_file_content(
    kb_id: str,
    body: ImportFileRequest,
    registry: KBRegistry = Depends(get_registry),
):
    """Import a single file with inline content. Supports base64 for binary files."""
    import base64 as b64
    kb = await registry.get(kb_id)
    if kb is None:
        raise HTTPException(404, "knowledge base not found")

    raw_dir = Path(kb.root_path) / INBOX_DIR
    raw_dir.mkdir(parents=True, exist_ok=True)

    dest = raw_dir / body.name
    if body.encoding == "base64":
        dest.write_bytes(b64.b64decode(body.content))
    else:
        dest.write_text(body.content, encoding="utf-8")

    return {"imported": str(dest.relative_to(kb.root_path)), "size": dest.stat().st_size}


@router.post("/kbs/{kb_id}/write")
async def write_page(
    kb_id: str,
    body: WritePageRequest,
    registry: KBRegistry = Depends(get_registry),
):
    """Create or update a wiki page."""
    kb = await registry.get(kb_id)
    if kb is None:
        raise HTTPException(404, "knowledge base not found")

    import yaml

    file_path = Path(kb.root_path) / body.path
    file_path.parent.mkdir(parents=True, exist_ok=True)

    fm = body.frontmatter or {}
    if "title" not in fm:
        fm["title"] = file_path.stem
    if "type" not in fm:
        fm["type"] = "wiki"

    fm_str = yaml.dump(fm, allow_unicode=True, default_flow_style=False).strip()
    full = f"---\n{fm_str}\n---\n\n{body.content}"
    file_path.write_text(full, encoding="utf-8")

    return {
        "path": body.path,
        "written": len(full),
        "status": "created" if not file_path.exists() else "updated",
    }


@router.post("/kbs/{kb_id}/search")
async def search_files(
    kb_id: str,
    body: SearchRequest,
    registry: KBRegistry = Depends(get_registry),
    scanner: Scanner = Depends(get_scanner),
):
    """FTS5 full-text search within a knowledge base."""
    kb = await registry.get(kb_id)
    if kb is None:
        raise HTTPException(404, "knowledge base not found")

    results = await scanner.search(kb_id, body.query, limit=body.limit, offset=body.offset)
    return {"query": body.query, "hits": len(results), "offset": body.offset, "results": results}
