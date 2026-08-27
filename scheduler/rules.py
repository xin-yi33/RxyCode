"""Application-layer schedule rules. No cron, launchd, or Task Scheduler."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any


class ScheduleRuleError(ValueError):
    pass


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
        parts = stamp.split(":")
        if len(parts) != 2:
            raise ScheduleRuleError("invalid at-time rule")
        hour, minute = int(parts[0]), int(parts[1])
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            raise ScheduleRuleError("invalid at-time rule")
        return {"kind": "at", "time": f"{hour:02d}:{minute:02d}", "once": False}
    raise ScheduleRuleError("rule kind must be interval or at")


def next_fire(rule: dict[str, Any], after: datetime) -> datetime:
    parsed = parse_rule(rule)
    if parsed["kind"] == "interval":
        delta = {
            "minutes": timedelta(minutes=parsed["every"]),
            "hours": timedelta(hours=parsed["every"]),
            "days": timedelta(days=parsed["every"]),
        }[parsed["unit"]]
        return after + delta
    if parsed.get("once"):
        stamp = datetime.fromisoformat(parsed["time"])
        if stamp.tzinfo is not None:
            stamp = stamp.replace(tzinfo=None)
        return stamp
    hour, minute = (int(part) for part in parsed["time"].split(":"))
    candidate = after.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if candidate <= after:
        candidate = candidate + timedelta(days=1)
    return candidate
