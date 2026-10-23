"""GET/PATCH /me/preferences — the server-owned copy of locale, sidebar and
appearance. Only whitelisted fields may change; unknown keys are a 422, so the
preference surface can never smuggle CSS/JS/security policy into the store."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from rxycode_server.api.auth import current_record, db_session, require_write
from rxycode_server.persistence.models import UserPreference

router = APIRouter()

_LOCALES = {"auto", "zh-CN", "en"}
_MODES = {"system", "light", "dark"}
_REDUCED = {"system", "on", "off"}
_DIFF = {"color", "symbols"}
_GROUPING = {"project", "merged"}
_SORT = {"updated_at", "manual"}
_PROFILE_KEYS = {
    "theme_id",
    "accent",
    "background",
    "foreground",
    "ui_font_px",
    "code_font_px",
    "contrast",
}
_CONTRAST = {"normal", "high"}
_APPEARANCE_KEYS = {
    "mode",
    "separate_modes",
    "shared",
    "light",
    "dark",
    "reduced_motion",
    "diff_markers",
}
_TOP_KEYS = {"locale", "sidebar", "appearance", "expected_revision"}

_DEFAULT = {
    "locale": "auto",
    "sidebar": {
        "grouping": "project",
        "sort": "updated_at",
        "show_projects": True,
        "projects_collapsed": False,
        "recent_collapsed": False,
    },
    "appearance": {
        "mode": "system",
        "separate_modes": False,
        "shared": {
            "theme_id": "rxy-dark",
            "accent": "",
            "background": "",
            "foreground": "",
            "ui_font_px": 14,
            "code_font_px": 13,
            "contrast": "normal",
        },
        "light": None,
        "dark": None,
        "reduced_motion": "system",
        "diff_markers": "color",
    },
}


def _profile(value: object, *, allow_null: bool) -> dict | None:
    if value is None:
        if allow_null:
            return None
        raise HTTPException(status_code=422, detail="INVALID_PREFERENCE")
    if not isinstance(value, dict) or not set(value) <= _PROFILE_KEYS:
        raise HTTPException(status_code=422, detail="INVALID_PREFERENCE")
    out = {}
    for key, item in value.items():
        if key in ("ui_font_px", "code_font_px"):
            if not isinstance(item, int) or not 10 <= item <= 24:
                raise HTTPException(status_code=422, detail="INVALID_PREFERENCE")
            out[key] = item
        elif key == "contrast":
            # APP-14：滑块数值 0–100（默认45）；旧客户端的 "normal"/"high"
            # 枚举仍接受并映射到数值，前端只发 int。
            if isinstance(item, str):
                if item not in _CONTRAST:
                    raise HTTPException(status_code=422, detail="INVALID_PREFERENCE")
                out[key] = {"normal": 45, "high": 80}[item]
            elif isinstance(item, int) and not isinstance(item, bool) and 0 <= item <= 100:
                out[key] = item
            else:
                raise HTTPException(status_code=422, detail="INVALID_PREFERENCE")
        else:
            text = str(item)
            if len(text) > 200:
                raise HTTPException(status_code=422, detail="INVALID_PREFERENCE")
            out[key] = text
    return out


def _sidebar(value: object) -> dict:
    allowed = {
        "grouping",
        "sort",
        "show_projects",
        "projects_collapsed",
        "recent_collapsed",
    }
    if not isinstance(value, dict) or not set(value) <= allowed:
        raise HTTPException(status_code=422, detail="INVALID_PREFERENCE")
    out = {}
    if "grouping" in value:
        if value["grouping"] not in _GROUPING:
            raise HTTPException(status_code=422, detail="INVALID_PREFERENCE")
        out["grouping"] = value["grouping"]
    if "sort" in value:
        if value["sort"] not in _SORT:
            raise HTTPException(status_code=422, detail="INVALID_PREFERENCE")
        out["sort"] = value["sort"]
    if "show_projects" in value:
        if not isinstance(value["show_projects"], bool):
            raise HTTPException(status_code=422, detail="INVALID_PREFERENCE")
        out["show_projects"] = value["show_projects"]
    for key in ("projects_collapsed", "recent_collapsed"):
        if key in value:
            if not isinstance(value[key], bool):
                raise HTTPException(status_code=422, detail="INVALID_PREFERENCE")
            out[key] = value[key]
    return out


def _appearance(value: object) -> dict:
    if not isinstance(value, dict) or not set(value) <= _APPEARANCE_KEYS:
        raise HTTPException(status_code=422, detail="INVALID_PREFERENCE")
    out = {}
    if "mode" in value:
        if value["mode"] not in _MODES:
            raise HTTPException(status_code=422, detail="INVALID_PREFERENCE")
        out["mode"] = value["mode"]
    if "separate_modes" in value:
        if not isinstance(value["separate_modes"], bool):
            raise HTTPException(status_code=422, detail="INVALID_PREFERENCE")
        out["separate_modes"] = value["separate_modes"]
    for name in ("shared", "light", "dark"):
        if name in value:
            out[name] = _profile(value[name], allow_null=name != "shared")
    if "reduced_motion" in value:
        if value["reduced_motion"] not in _REDUCED:
            raise HTTPException(status_code=422, detail="INVALID_PREFERENCE")
        out["reduced_motion"] = value["reduced_motion"]
    if "diff_markers" in value:
        if value["diff_markers"] not in _DIFF:
            raise HTTPException(status_code=422, detail="INVALID_PREFERENCE")
        out["diff_markers"] = value["diff_markers"]
    return out


def _merge(base: dict, patch: dict) -> dict:
    out = dict(base)
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _merge(out[key], value)
        else:
            out[key] = value
    return out


def _effective(row: UserPreference | None) -> dict:
    prefs = _merge(
        _DEFAULT,
        {
            "sidebar": row.sidebar if row else {},
            "appearance": row.appearance if row else {},
        },
    )
    if row is not None:
        prefs["locale"] = row.locale
    return prefs


def _row(db: Session, user_id: str, *, create: bool = False) -> UserPreference | None:
    row = db.get(UserPreference, user_id)
    if row is None and create:
        row = UserPreference(
            user_id=user_id,
            sidebar=dict(_DEFAULT["sidebar"]),
            appearance=dict(_DEFAULT["appearance"]),
        )
        db.add(row)
        db.flush()
    return row


@router.get("/api/v1/me/preferences")
def get_preferences(request: Request, db: Session = Depends(db_session)) -> dict[str, object]:
    record = current_record(request)
    row = _row(db, record.user_id)
    prefs = _effective(row)
    return {
        "revision": int(row.revision) if row else 0,
        "locale": prefs["locale"],
        "sidebar": prefs["sidebar"],
        "appearance": prefs["appearance"],
    }


class _PatchIn(BaseModel):
    # validated field-by-field below — the model only rejects wrong types
    expected_revision: int | None = None

    model_config = {"extra": "allow"}


@router.patch("/api/v1/me/preferences")
def patch_preferences(
    payload: _PatchIn,
    request: Request,
    db: Session = Depends(db_session),
) -> dict[str, object]:
    require_write(request)
    record = current_record(request)
    body = payload.model_dump()
    unknown = set(body) - _TOP_KEYS
    if unknown:
        raise HTTPException(status_code=422, detail="INVALID_PREFERENCE")
    row = db.execute(
        select(UserPreference).where(UserPreference.user_id == record.user_id).with_for_update()
    ).scalar_one_or_none()
    if row is None:
        row = _row(db, record.user_id, create=True)
    expected = body.get("expected_revision")
    if expected is not None and int(row.revision) != int(expected):
        raise HTTPException(status_code=409, detail="REVISION_CONFLICT")

    sidebar = dict(row.sidebar or _DEFAULT["sidebar"])
    appearance = _merge(dict(row.appearance or _DEFAULT["appearance"]), {})
    locale = row.locale
    if "locale" in body:
        if body["locale"] not in _LOCALES:
            raise HTTPException(status_code=422, detail="INVALID_PREFERENCE")
        locale = body["locale"]
    if "sidebar" in body:
        sidebar.update(_sidebar(body["sidebar"]))
    if "appearance" in body:
        appearance = _merge(appearance, _appearance(body["appearance"]))

    row.locale = locale
    row.sidebar = sidebar
    row.appearance = appearance
    row.revision = int(row.revision or 0) + 1
    db.flush()
    prefs = _effective(row)
    return {
        "revision": int(row.revision),
        "locale": prefs["locale"],
        "sidebar": prefs["sidebar"],
        "appearance": prefs["appearance"],
    }
