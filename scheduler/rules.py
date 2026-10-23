"""Application-layer schedule rules. No cron, launchd, or Task Scheduler.

Kinds: ``interval`` (minutes/hours/days), ``at`` (one instant or a daily
HH:mm) and ``weekly`` (weekdays 1..7 + HH:mm). Daily/weekly times are
interpreted in the schedule's IANA timezone so DST stays honest.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


class ScheduleRuleError(ValueError):
    pass


def parse_timezone(name: Any) -> ZoneInfo:
    text = str(name or "UTC")
    try:
        return ZoneInfo(text)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ScheduleRuleError(f"invalid timezone: {text}") from exc


def parse_rule(rule: dict[str, Any]) -> dict[str, Any]:
    kind = str((rule or {}).get("kind") or "")
    if kind == "interval":
        every = int(rule.get("every") or 0)
        unit = str(rule.get("unit") or "minutes")
        if every <= 0 or unit not in {"minutes", "hours", "days"}:
            raise ScheduleRuleError("invalid interval rule")
        return {"kind": "interval", "every": every, "unit": unit}
    if kind == "at":
        stamp = str(rule.get("time") or "")
        if "T" in stamp:
            datetime.fromisoformat(stamp)
            return {"kind": "at", "time": stamp, "once": True}
        return {"kind": "at", "time": _hhmm(stamp), "once": False}
    if kind == "weekly":
        raw = rule.get("weekdays") or []
        days = sorted({int(day) for day in raw})
        if not days or any(day < 1 or day > 7 for day in days):
            raise ScheduleRuleError("invalid weekly weekdays")
        return {
            "kind": "weekly",
            "weekdays": days,
            "time": _hhmm(str(rule.get("time") or "")),
        }
    raise ScheduleRuleError("rule kind must be interval, at or weekly")


def _hhmm(stamp: str) -> str:
    parts = stamp.split(":")
    if len(parts) != 2:
        raise ScheduleRuleError("invalid at-time rule")
    try:
        hour, minute = int(parts[0]), int(parts[1])
    except ValueError as exc:
        raise ScheduleRuleError("invalid at-time rule") from exc
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ScheduleRuleError("invalid at-time rule")
    return f"{hour:02d}:{minute:02d}"


def next_fire(rule: dict[str, Any], after: datetime, timezone_name: str = "UTC") -> datetime:
    """Naive-UTC instant of the next firing, computed in the schedule's zone."""
    parsed = parse_rule(rule)
    zone = parse_timezone(timezone_name)
    local = after.replace(tzinfo=ZoneInfo("UTC")).astimezone(zone)
    if parsed["kind"] == "interval":
        delta = {
            "minutes": timedelta(minutes=parsed["every"]),
            "hours": timedelta(hours=parsed["every"]),
            "days": timedelta(days=parsed["every"]),
        }[parsed["unit"]]
        return _to_naive_utc(local + delta)
    if parsed.get("once"):
        stamp = datetime.fromisoformat(parsed["time"])
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=zone)
        return _to_naive_utc(stamp)
    hour, minute = (int(part) for part in parsed["time"].split(":"))
    if parsed["kind"] == "weekly":
        days = set(parsed["weekdays"])
        for offset in range(0, 8):
            candidate_day = (local + timedelta(days=offset)).date()
            candidate = datetime(
                candidate_day.year,
                candidate_day.month,
                candidate_day.day,
                hour,
                minute,
                tzinfo=zone,
            )
            if candidate > local and candidate.isoweekday() in days:
                return _to_naive_utc(candidate)
        raise ScheduleRuleError("weekly rule has no future fire")
    candidate = local.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if candidate <= local:
        candidate = candidate + timedelta(days=1)
    return _to_naive_utc(candidate)


def preview(
    rule: dict[str, Any], after: datetime, timezone_name: str = "UTC", count: int = 3
) -> list[datetime]:
    """The next ``count`` fire instants — the schedule's honest preview."""
    out: list[datetime] = []
    cursor = after
    for _ in range(max(1, count)):
        nxt = next_fire(rule, cursor, timezone_name)
        out.append(nxt)
        cursor = nxt + timedelta(seconds=1)
    return out


def _to_naive_utc(value: datetime) -> datetime:
    return value.astimezone(ZoneInfo("UTC")).replace(tzinfo=None)
