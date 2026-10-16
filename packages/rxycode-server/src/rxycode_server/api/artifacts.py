"""Artifact list and download. The tenant comes from the session."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

from rxycode_server.api.auth import current_record
from rxycode_server.artifacts.service import ArtifactForbidden, read_download
from rxycode_server.persistence.models import Artifact, Run

router = APIRouter()


def _content_type(database_url: str, artifact_id: str) -> str:
    engine = create_engine(database_url, poolclass=NullPool)
    try:
        with Session(engine) as db:
            row = db.get(Artifact, artifact_id)
            if row is None or not row.content_type:
                return "application/octet-stream"
            return row.content_type
    finally:
        engine.dispose()


def _rows(database_url: str, run_id: str) -> tuple[str, list[dict[str, object]]] | None:
    engine = create_engine(database_url, poolclass=NullPool)
    try:
        with Session(engine) as db:
            run = db.get(Run, run_id)
            if run is None:
                return None
            found = db.scalars(select(Artifact).where(Artifact.run_id == run.id)).all()
            items = [
                {
                    "artifact_id": row.id,
                    "sha256": row.sha256,
                    "size": int(row.size),
                    "content_type": row.content_type,
                }
                for row in found
            ]
            return run.tenant_id, items
    finally:
        engine.dispose()


@router.get("/api/v1/runs/{run_id}/artifacts")
def list_artifacts(run_id: str, request: Request) -> dict:
    record = current_record(request)
    loaded = _rows(request.app.state.database_url, run_id)
    if loaded is None:
        raise HTTPException(status_code=404, detail="RUN_NOT_FOUND")
    tenant_id, items = loaded
    if tenant_id != record.tenant_id:
        raise HTTPException(status_code=403, detail="ARTIFACT_FORBIDDEN")
    return {"artifacts": items}


@router.get("/api/v1/runs/{run_id}/artifacts/{artifact_id}")
def download_artifact(
    run_id: str,
    artifact_id: str,
    request: Request,
    expires: str = "",
    signature: str = "",
) -> Response:
    record = current_record(request)
    state = request.app.state
    try:
        body = read_download(
            state.database_url,
            tenant_id=record.tenant_id,
            artifact_id=artifact_id,
            expires=expires,
            signature=signature,
            signing_key=state.secret,
            s3_endpoint=getattr(state, "s3_endpoint", None),
            bucket=getattr(state, "s3_bucket", None),
            access_key=getattr(state, "s3_access_key", None),
            secret_key=getattr(state, "s3_secret_key", None),
            run_id=run_id,
        )
    except ArtifactForbidden as exc:
        raise HTTPException(status_code=exc.http_status, detail=exc.code) from exc
    return Response(content=body, media_type=_content_type(state.database_url, artifact_id))
