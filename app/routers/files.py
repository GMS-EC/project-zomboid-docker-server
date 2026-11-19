import asyncio
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel

from app.core.security import require_auth
from app.core.file_manager import file_manager
from app.core.activity_manager import activity_manager

router = APIRouter(tags=["files"])


class FileSaveRequest(BaseModel):
    path: str
    content: str


class FolderCreateRequest(BaseModel):
    path: str


class UnzipRequest(BaseModel):
    path: str
    target_dir: str = ""


class FileRenameRequest(BaseModel):
    path: str
    new_name: str


class FileDuplicateRequest(BaseModel):
    path: str


class FileCompressRequest(BaseModel):
    path: str


class FileCreateRequest(BaseModel):
    path: str


class BulkDeleteRequest(BaseModel):
    paths: List[str]


class BulkCompressRequest(BaseModel):
    paths: List[str]
    target_dir: Optional[str] = ""
    archive_name: Optional[str] = ""


@router.get("/api/files/list", dependencies=[Depends(require_auth)])
async def file_list(path: str = Query("")):
    return await asyncio.to_thread(file_manager.list_directory, path)


@router.get("/api/files/read", dependencies=[Depends(require_auth)])
async def file_content(path: str = Query(...)):
    return await asyncio.to_thread(file_manager.read_file, path)


@router.post("/api/files/write", dependencies=[Depends(require_auth)])
async def file_save(req: FileSaveRequest):
    res = await asyncio.to_thread(file_manager.write_file, req.path, req.content)
    activity_manager.log("Archivos", f"Archivo guardado: {req.path}")
    return res


@router.post("/api/files/create-folder", dependencies=[Depends(require_auth)])
async def file_folder(req: FolderCreateRequest):
    res = await asyncio.to_thread(file_manager.create_folder, req.path)
    activity_manager.log("Archivos", f"Carpeta creada: {req.path}")
    return res


@router.delete("/api/files/delete", dependencies=[Depends(require_auth)])
async def file_delete(path: str = Query(...)):
    res = await asyncio.to_thread(file_manager.delete_item, path)
    activity_manager.log("Archivos", f"Elemento eliminado: {path}")
    return res


@router.post("/api/files/upload", dependencies=[Depends(require_auth)])
async def file_upload(path: str = Form(""), file: UploadFile = File(...)):
    res = await file_manager.save_upload(path, file)
    activity_manager.log("Archivos", f"Archivo subido: {res.get('filename')}")
    return res


@router.post("/api/files/extract", dependencies=[Depends(require_auth)])
async def file_unzip(req: UnzipRequest):
    res = await asyncio.to_thread(file_manager.extract_zip, req.path, req.target_dir)
    activity_manager.log("Archivos", f"Archivo extraído: {req.path}")
    return res


@router.get("/api/files/download", dependencies=[Depends(require_auth)])
async def file_download(path: str = Query(...)):
    safe_path = file_manager._resolve_safe_path(path)
    if not safe_path.exists() or not safe_path.is_file():
        raise HTTPException(status_code=404, detail="Archivo no encontrado")
    return FileResponse(str(safe_path), filename=safe_path.name, media_type="application/octet-stream")


@router.post("/api/files/rename", dependencies=[Depends(require_auth)])
async def file_rename(req: FileRenameRequest):
    res = await asyncio.to_thread(file_manager.rename_item, req.path, req.new_name)
    activity_manager.log("Archivos", f"Renombrado: {req.path} -> {res.get('name')}")
    return res


@router.post("/api/files/duplicate", dependencies=[Depends(require_auth)])
async def file_duplicate(req: FileDuplicateRequest):
    res = await asyncio.to_thread(file_manager.duplicate_item, req.path)
    activity_manager.log("Archivos", f"Duplicado: {req.path} -> {res.get('new_name')}")
    return res


@router.post("/api/files/compress", dependencies=[Depends(require_auth)])
async def file_compress(req: FileCompressRequest):
    res = await asyncio.to_thread(file_manager.compress_item, req.path)
    activity_manager.log("Archivos", f"Comprimido: {res.get('archive_name')}")
    return res


@router.post("/api/files/create-file", dependencies=[Depends(require_auth)])
async def file_create(req: FileCreateRequest):
    res = await asyncio.to_thread(file_manager.create_file, req.path)
    activity_manager.log("Archivos", f"Archivo creado: {req.path}")
    return res


@router.post("/api/files/bulk-delete", dependencies=[Depends(require_auth)])
async def file_bulk_delete(req: BulkDeleteRequest):
    res = await asyncio.to_thread(file_manager.bulk_delete, req.paths)
    activity_manager.log("Archivos", f"Eliminación múltiple ({res.get('deleted_count', 0)} elementos)")
    return res


@router.post("/api/files/bulk-compress", dependencies=[Depends(require_auth)])
async def file_bulk_compress(req: BulkCompressRequest):
    res = await asyncio.to_thread(file_manager.bulk_compress, req.paths, req.target_dir or "", req.archive_name or "")
    activity_manager.log("Archivos", f"Compresión múltiple: {res.get('archive_name')}")
    return res
