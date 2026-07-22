"""Backup ingestion endpoints (device-authenticated).

Flow per run:
1. POST /api/backup/run            -> {run_id}
2. POST /api/backup/manifest       -> {missing: [sha256, ...]}   (dedup check)
3. PUT  /api/backup/object/{sha}   (raw plaintext body)          (upload missing)
4. POST /api/backup/run/{id}/complete

Uploaded bytes are hashed and verified against {sha}, then encrypted at rest.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import storage
from app.auth import authenticate_device
from app.db import get_session
from app.models import BackupObject, BackupRun, Device
from app.schemas import (
    ManifestRequest,
    ManifestResponse,
    RunCompleteRequest,
    RunStartResponse,
)
from app.util import utcnow

router = APIRouter(prefix="/backup", tags=["backup"])


@router.post("/run", response_model=RunStartResponse)
def start_run(
    device: Device = Depends(authenticate_device),
    session: Session = Depends(get_session),
) -> RunStartResponse:
    run = BackupRun(device_id=device.id)
    session.add(run)
    device.last_seen = utcnow()
    session.commit()
    return RunStartResponse(run_id=run.id)


@router.post("/manifest", response_model=ManifestResponse)
def manifest(
    body: ManifestRequest,
    device: Device = Depends(authenticate_device),
    session: Session = Depends(get_session),
) -> ManifestResponse:
    wanted = {f.sha256 for f in body.files}
    if not wanted:
        return ManifestResponse(missing=[])
    have = set(
        session.scalars(
            select(BackupObject.sha256).where(
                BackupObject.device_id == device.id,
                BackupObject.sha256.in_(wanted),
            )
        )
    )
    return ManifestResponse(missing=[s for s in wanted if s not in have])


@router.put("/object/{sha256}")
async def upload_object(
    sha256: str,
    request: Request,
    path: str = Query(..., description="Original path on the device"),
    category: str = Query("file"),
    device: Device = Depends(authenticate_device),
    session: Session = Depends(get_session),
) -> dict:
    existing = session.scalar(
        select(BackupObject).where(
            BackupObject.device_id == device.id, BackupObject.sha256 == sha256
        )
    )
    if existing is not None:
        existing.last_seen = utcnow()
        existing.rel_path = path
        session.commit()
        return {"stored": False, "deduped": True, "size": existing.size}

    ok, size, message = await storage.store(device.id, sha256, request.stream())
    if not ok:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=message
        )

    session.add(
        BackupObject(
            device_id=device.id,
            sha256=sha256,
            category=category,
            rel_path=path,
            size=size,
        )
    )
    device.last_seen = utcnow()
    session.commit()
    return {"stored": True, "deduped": False, "size": size}


@router.post("/run/{run_id}/complete")
def complete_run(
    run_id: str,
    body: RunCompleteRequest,
    device: Device = Depends(authenticate_device),
    session: Session = Depends(get_session),
) -> dict:
    run = session.get(BackupRun, run_id)
    if run is None or run.device_id != device.id:
        raise HTTPException(status_code=404, detail="Unknown run")
    run.status = body.status
    run.file_count = body.file_count
    run.total_bytes = body.total_bytes
    run.completed_at = utcnow()
    device.last_seen = utcnow()
    session.commit()
    return {"ok": True}
