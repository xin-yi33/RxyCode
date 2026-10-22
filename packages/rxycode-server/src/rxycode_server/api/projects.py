"""Project and session routes. The tenant comes from the session, not the body."""

from __future__ import annotations

import re
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from rxycode_server.api.auth import current_record, db_session, require_write
from rxycode_server.api.runs import _aware
from rxycode_server.persistence.models import (
    Project,
    SessionRow,
    UserProjectMeta,
    UserSessionMeta,
)

router = APIRouter()
_SECRET_KEY = re.compile(r"(api[_-]?key|secret|token|password|authorization)", re.IGNORECASE)


class ProjectIn(BaseModel):
    name: str
    repo_config: dict = Field(default_factory=dict)
    tenant_id: str | None = None
    memory_mode: str = "default"
    request_id: str | None = None


class SessionIn(BaseModel):
    title: str = ""
    origin: str = "cloud"
    source: str = "chat"
    request_id: str | None = None


class ProjectPatch(BaseModel):
    name: str | None = None
    pinned: bool | None = None
    instructions: str | None = None
    expected_revision: int | None = None


class ProjectDelete(BaseModel):
    expected_revision: int | None = None
    keep_sessions: bool = True


class SidebarOrderIn(BaseModel):
    scope: str
    project_id: str | None = None
    ordered_ids: list[str] = Field(default_factory=list)
    expected_revision: int | None = None


def _iso(value):
    stamp = _aware(value)
    return stamp.isoformat() if stamp is not None else None


def _project_item(db: Session, record, row: Project) -> dict[str, object]:
    meta = db.get(UserProjectMeta, (record.user_id, row.id))
    return {
        "id": row.id,
        "name": row.name,
        "tenant_id": row.tenant_id,
        "memory_mode": row.memory_mode or "default",
        "is_default": bool(row.is_default),
        "pinned": bool(meta.pinned) if meta else False,
        "pin_order": meta.pin_order if meta else None,
        "revision": int(row.revision or 0),
        "created_at": _iso(row.created_at),
        "instructions": (row.repo_config or {}).get("instructions", ""),
    }


def _conflict_name(db: Session, tenant_id: str, name: str, exclude: str = "") -> bool:
    return (
        db.scalars(
            select(Project).where(
                Project.tenant_id == tenant_id,
                Project.name == name,
                Project.id != exclude,
            )
        ).first()
        is not None
    )


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
    metas = {
        row.project_id: row
        for row in db.scalars(
            select(UserProjectMeta).where(UserProjectMeta.user_id == record.user_id)
        ).all()
    }
    items = sorted(
        (
            {
                **_project_item(db, record, row),
                "pinned": bool(metas[row.id].pinned) if row.id in metas else False,
                "pin_order": metas[row.id].pin_order if row.id in metas else None,
            }
            for row in rows
        ),
        key=lambda item: (
            0 if item["pinned"] else 1,
            item["pin_order"] if item["pin_order"] is not None else 1 << 30,
            str(item["name"]).lower(),
        ),
    )
    return {"projects": items}


@router.post("/api/v1/projects")
def create_project(
    request: Request,
    payload: ProjectIn,
    db: Session = Depends(db_session),
) -> dict[str, object]:
    require_write(request)
    record = current_record(request)
    if payload.request_id:
        existing = db.scalars(
            select(Project).where(
                Project.tenant_id == record.tenant_id,
                Project.request_id == payload.request_id,
            )
        ).one_or_none()
        if existing is not None:
            return {"project": _project_item(db, record, existing)}
    config = dict(payload.repo_config)
    config.pop("workspace_root", None)
    config.pop("target_id", None)
    _reject_plaintext_keys(config)
    name = payload.name.strip()
    if not name or len(name) > 200:
        raise HTTPException(status_code=400, detail="INVALID_INPUT")
    # 契约值 project_only（规格 §02）；连字符是早期笔误的兼容别名。
    if payload.memory_mode == "project-only":
        payload = payload.model_copy(update={"memory_mode": "project_only"})
    if payload.memory_mode not in ("default", "project_only"):
        raise HTTPException(status_code=400, detail="INVALID_INPUT")
    if _conflict_name(db, record.tenant_id, name):
        raise HTTPException(status_code=409, detail="PROJECT_NAME_CONFLICT")
    project = Project(
        id=uuid.uuid4().hex,
        tenant_id=record.tenant_id,
        name=name,
        repo_config=config,
        memory_mode=payload.memory_mode,
        request_id=payload.request_id,
    )
    db.add(project)
    db.flush()
    return {"project": _project_item(db, record, project)}


def _locked_project(db: Session, record, project_id: str) -> Project:
    row = db.execute(
        select(Project)
        .where(Project.id == project_id, Project.tenant_id == record.tenant_id)
        .with_for_update()
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="PROJECT_NOT_FOUND")
    return row


def _check_revision(revision: int, expected: int | None) -> None:
    if expected is not None and int(revision) != expected:
        raise HTTPException(status_code=409, detail="REVISION_CONFLICT")


@router.patch("/api/v1/projects/{project_id}")
def patch_project(
    project_id: str,
    payload: ProjectPatch,
    request: Request,
    db: Session = Depends(db_session),
) -> dict[str, object]:
    require_write(request)
    record = current_record(request)
    row = _locked_project(db, record, project_id)
    _check_revision(row.revision, payload.expected_revision)
    if payload.name is not None:
        name = payload.name.strip()
        if not 1 <= len(name) <= 200:
            raise HTTPException(status_code=400, detail="INVALID_INPUT")
        if _conflict_name(db, record.tenant_id, name, exclude=row.id):
            raise HTTPException(status_code=409, detail="PROJECT_NAME_CONFLICT")
        row.name = name
    if payload.instructions is not None:
        config = dict(row.repo_config or {})
        config["instructions"] = payload.instructions
        row.repo_config = config
    if payload.pinned is not None:
        meta = db.get(UserProjectMeta, (record.user_id, row.id))
        if meta is None:
            meta = UserProjectMeta(user_id=record.user_id, project_id=row.id)
            db.add(meta)
        meta.pinned = bool(payload.pinned)
        if meta.pinned and meta.pin_order is None:
            from sqlalchemy import func

            top = db.scalar(
                select(func.max(UserProjectMeta.pin_order)).where(
                    UserProjectMeta.user_id == record.user_id,
                    UserProjectMeta.pinned == True,  # noqa: E712
                )
            )
            meta.pin_order = int(top or 0) + 1
        elif not meta.pinned:
            meta.pin_order = None
    row.revision = int(row.revision or 0) + 1
    db.flush()
    return {"project": _project_item(db, record, row)}


@router.delete("/api/v1/projects/{project_id}", status_code=204)
def delete_project(
    project_id: str,
    payload: ProjectDelete,
    request: Request,
    db: Session = Depends(db_session),
) -> None:
    require_write(request)
    record = current_record(request)
    row = _locked_project(db, record, project_id)
    _check_revision(row.revision, payload.expected_revision)
    if row.is_default:
        raise HTTPException(status_code=403, detail="DEFAULT_PROJECT_PROTECTED")
    from sqlalchemy import func, text

    from rxycode_server.api.sessions import (
        _LIVE_RUN_STATUSES,
        _default_project_id,
    )
    from rxycode_server.persistence.models import Run

    session_ids = db.scalars(select(SessionRow.id).where(SessionRow.project_id == row.id)).all()
    if session_ids:
        busy = db.scalar(
            select(func.count(Run.id)).where(
                Run.session_id.in_(session_ids), Run.status.in_(_LIVE_RUN_STATUSES)
            )
        )
        if busy:
            raise HTTPException(status_code=409, detail="PROJECT_BUSY")
    if payload.keep_sessions:
        default_id = _default_project_id(db, record)
        for session_id in session_ids:
            db.execute(
                SessionRow.__table__.update()
                .where(SessionRow.id == session_id)
                .values(project_id=default_id)
            )
    else:
        from datetime import datetime, timezone

        for session_id in session_ids:
            db.execute(
                SessionRow.__table__.update()
                .where(SessionRow.id == session_id)
                .values(deleted_at=datetime.now(timezone.utc))
            )
        db.execute(
            text(
                "UPDATE web_schedules SET enabled = false, blocked_reason = 'deleted'"
                " WHERE tenant_id = :tenant AND project_id = :project"
            ),
            {"tenant": record.tenant_id, "project": row.id},
        )
    db.delete(row)
    db.flush()
    return None


@router.put("/api/v1/me/sidebar-order")
def put_sidebar_order(
    payload: SidebarOrderIn,
    request: Request,
    db: Session = Depends(db_session),
) -> dict[str, object]:
    require_write(request)
    record = current_record(request)
    if payload.scope not in ("pinned_projects", "pinned_sessions", "sessions"):
        raise HTTPException(status_code=400, detail="INVALID_INPUT")
    changed = 0
    if payload.scope == "pinned_projects":
        rows = {
            row.project_id: row
            for row in db.scalars(
                select(UserProjectMeta).where(
                    UserProjectMeta.user_id == record.user_id,
                    UserProjectMeta.project_id.in_(payload.ordered_ids),
                )
            ).all()
        }
        # Only reorder ids that are actually pinned for this user.
        for index, pid in enumerate(payload.ordered_ids):
            meta = rows.get(pid)
            if meta is not None and meta.pinned:
                if meta.pin_order != index + 1:
                    meta.pin_order = index + 1
                    changed += 1
    else:
        rows = {
            row.session_id: row
            for row in db.scalars(
                select(UserSessionMeta).where(
                    UserSessionMeta.user_id == record.user_id,
                    UserSessionMeta.session_id.in_(payload.ordered_ids),
                )
            ).all()
        }
        for index, sid in enumerate(payload.ordered_ids):
            meta = rows.get(sid)
            if meta is None:
                continue
            if payload.scope == "pinned_sessions":
                if meta.pinned and meta.pin_order != index + 1:
                    meta.pin_order = index + 1
                    changed += 1
            elif meta.manual_order != index + 1:
                meta.manual_order = index + 1
                changed += 1
    db.flush()
    return {"updated": True, "scope": payload.scope, "changed": changed}


@router.get("/api/v1/projects/{project_id}")
def get_project(
    project_id: str,
    request: Request,
    db: Session = Depends(db_session),
) -> dict[str, object]:
    record = current_record(request)
    project = db.scalars(
        select(Project).where(Project.id == project_id, Project.tenant_id == record.tenant_id)
    ).one_or_none()
    if project is None:
        raise HTTPException(status_code=404, detail="PROJECT_NOT_FOUND")
    return {"project": _project_item(db, record, project)}


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
        select(SessionRow)
        .where(
            SessionRow.project_id == project.id,
            SessionRow.tenant_id == record.tenant_id,
            SessionRow.deleted_at.is_(None),
        )
        .order_by(SessionRow.updated_at.desc())
    ).all()
    from rxycode_server.api.sessions import _finish

    return {"sessions": [_finish(db, record, row) for row in rows]}


@router.post("/api/v1/projects/{project_id}/sessions")
def create_session(
    project_id: str,
    request: Request,
    payload: SessionIn,
    db: Session = Depends(db_session),
) -> dict[str, object]:
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
        origin=payload.origin if payload.origin in ("local", "cloud") else "cloud",
        source=payload.source if payload.source in ("chat", "scheduled") else "chat",
    )
    db.add(row)
    db.flush()
    from rxycode_server.api.sessions import _finish

    return _finish(db, record, row)


@router.get("/api/v1/sessions/{session_id}")
def get_session(
    session_id: str,
    request: Request,
    db: Session = Depends(db_session),
) -> dict[str, object]:
    record = current_record(request)
    row = db.scalars(
        select(SessionRow).where(
            SessionRow.id == session_id, SessionRow.tenant_id == record.tenant_id
        )
    ).one_or_none()
    if row is None or row.deleted_at is not None:
        raise HTTPException(status_code=404, detail="SESSION_NOT_FOUND")
    from rxycode_server.api.sessions import _finish

    return _finish(db, record, row)
