"""Project and session routes. The tenant comes from the session, not the body."""

from __future__ import annotations

import re
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from rxycode_server.api.auth import current_record, db_session, require_write
from rxycode_server.persistence.models import Project, SessionRow

router = APIRouter()
_SECRET_KEY = re.compile(r"(api[_-]?key|secret|token|password|authorization)", re.IGNORECASE)


class ProjectIn(BaseModel):
    name: str
    repo_config: dict = Field(default_factory=dict)
    tenant_id: str | None = None


class SessionIn(BaseModel):
    title: str = ""


def _reject_plaintext_keys(value: object, key: str = "") -> None:
    if _SECRET_KEY.search(key):
        raise HTTPException(status_code=400, detail="INVALID_INPUT")
    if isinstance(value, dict):
        for child_key, child in value.items():
            _reject_plaintext_keys(child, str(child_key))
    elif isinstance(value, list):
        for child in value:
            _reject_plaintext_keys(child)


@router.get("/api/v1/projects")
def list_projects(request: Request, db: Session = Depends(db_session)) -> dict[str, list]:
    record = current_record(request)
    rows = db.scalars(select(Project).where(Project.tenant_id == record.tenant_id)).all()
    return {
        "projects": [
            {"id": row.id, "name": row.name, "tenant_id": row.tenant_id} for row in rows
        ]
    }


@router.post("/api/v1/projects")
def create_project(
    request: Request,
    payload: ProjectIn,
    db: Session = Depends(db_session),
) -> dict[str, str]:
    require_write(request)
    record = current_record(request)
    _reject_plaintext_keys(payload.repo_config)
    name = payload.name.strip()
    if not name or len(name) > 200:
        raise HTTPException(status_code=400, detail="INVALID_INPUT")
    project = Project(
        id=uuid.uuid4().hex,
        tenant_id=record.tenant_id,
        name=name,
        repo_config=payload.repo_config,
    )
    db.add(project)
    db.flush()
    return {"id": project.id, "name": project.name, "tenant_id": project.tenant_id}


@router.get("/api/v1/projects/{project_id}")
def get_project(
    project_id: str,
    request: Request,
    db: Session = Depends(db_session),
) -> dict[str, str]:
    record = current_record(request)
    project = db.scalars(
        select(Project).where(Project.id == project_id, Project.tenant_id == record.tenant_id)
    ).one_or_none()
    if project is None:
        raise HTTPException(status_code=404, detail="PROJECT_NOT_FOUND")
    return {"id": project.id, "name": project.name, "tenant_id": project.tenant_id}


@router.get("/api/v1/projects/{project_id}/sessions")
def list_sessions(
    project_id: str,
    request: Request,
    db: Session = Depends(db_session),
) -> dict[str, list]:
    record = current_record(request)
    project = db.scalars(
        select(Project).where(Project.id == project_id, Project.tenant_id == record.tenant_id)
    ).one_or_none()
    if project is None:
        raise HTTPException(status_code=404, detail="PROJECT_NOT_FOUND")
    rows = db.scalars(
        select(SessionRow).where(
            SessionRow.project_id == project.id,
            SessionRow.tenant_id == record.tenant_id,
        )
    ).all()
    return {
        "sessions": [
            {"id": row.id, "title": row.title, "project_id": project.id} for row in rows
        ]
    }


@router.post("/api/v1/projects/{project_id}/sessions")
def create_session(
    project_id: str,
    request: Request,
    payload: SessionIn,
    db: Session = Depends(db_session),
) -> dict[str, str]:
    require_write(request)
    record = current_record(request)
    project = db.scalars(
        select(Project).where(Project.id == project_id, Project.tenant_id == record.tenant_id)
    ).one_or_none()
    if project is None:
        raise HTTPException(status_code=404, detail="PROJECT_NOT_FOUND")
    row = SessionRow(
        id=uuid.uuid4().hex,
        tenant_id=project.tenant_id,
        project_id=project.id,
        title=payload.title[:200],
    )
    db.add(row)
    db.flush()
    return {"id": row.id, "title": row.title, "project_id": project.id}


@router.get("/api/v1/sessions/{session_id}")
def get_session(
    session_id: str,
    request: Request,
    db: Session = Depends(db_session),
) -> dict[str, str]:
    record = current_record(request)
    row = db.scalars(
        select(SessionRow).where(SessionRow.id == session_id, SessionRow.tenant_id == record.tenant_id)
    ).one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="SESSION_NOT_FOUND")
    return {"id": row.id, "title": row.title, "project_id": row.project_id}
