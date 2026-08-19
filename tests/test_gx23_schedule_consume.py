"""GX23-B path A: consume B16 schedule/*. Do not invent a second scheduler."""

from __future__ import annotations

from pathlib import Path

from appserver.server import AppServer
from protocol.requests import (
    ScheduleCreateRequest,
    ScheduleDeleteRequest,
    ScheduleListRequest,
    ScheduleToggleRequest,
    ScheduleUpdateRequest,
)


def test_schedule_methods_exist() -> None:
    assert ScheduleListRequest.model_fields["method"].default == "schedule/list"
    assert ScheduleCreateRequest.model_fields["method"].default == "schedule/create"
    assert ScheduleUpdateRequest.model_fields["method"].default == "schedule/update"
    assert ScheduleDeleteRequest.model_fields["method"].default == "schedule/delete"
    assert ScheduleToggleRequest.model_fields["method"].default == "schedule/toggle"


def test_appserver_has_schedule_service() -> None:
    server = AppServer(stub=True)
    assert server._schedule is not None


def test_no_handlers_package() -> None:
    assert not (Path(__file__).resolve().parents[1] / "appserver" / "handlers").exists()
