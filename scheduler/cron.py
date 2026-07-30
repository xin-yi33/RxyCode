"""Cron expression parser supporting standard 5-field format.

Fields: minute hour day-of-month month day-of-week
Special values: * (any), */N (every N), N-M (range), N,M,O (list)

Examples:
    * * * * *       -> every minute
    */5 * * * *     -> every 5 minutes
    0 * * * *       -> every hour at :00
    0 9 * * 1-5     -> weekdays at 09:00
    30 8 1,15 * *   -> 8:30 on 1st and 15th
"""

import re
from dataclasses import dataclass
from datetime import datetime


@dataclass
class CronExpression:
    """Parsed cron expression."""
    minutes: set[int]
    hours: set[int]
    days: set[int]
    months: set[int]
    weekdays: set[int]
    raw: str

    def matches(self, dt: datetime) -> bool:
        """Check if a datetime matches this cron expression."""
        # cron weekday: 0=Sun,1=Mon,...,6=Sat  |  python weekday(): 0=Mon,...,6=Sun
        cron_wday = (dt.weekday() + 1) % 7
        return (
            dt.minute in self.minutes
            and dt.hour in self.hours
            and dt.day in self.days
            and dt.month in self.months
            and cron_wday in self.weekdays
        )

    def next_run(self, after: datetime) -> datetime:
        """Find the next matching time after the given datetime."""
        from datetime import timedelta
        candidate = after.replace(second=0, microsecond=0) + timedelta(minutes=1)

        for _ in range(60 * 24 * 366):  # limit to ~1 year
            if self.matches(candidate):
                return candidate
            candidate += timedelta(minutes=1)

        raise ValueError("Could not find next run time within 1 year")


def parse_cron(expr: str) -> CronExpression:
    """Parse a cron expression string into a CronExpression.

    Supports:
        Standard 5-field: "minute hour day month weekday"
        Shorthand: "@every 5m", "@hourly", "@daily", "@weekly", "@monthly"
    """
    expr = expr.strip()

    expr = _expand_shorthand(expr)

    parts = expr.split()
    if len(parts) != 5:
        raise ValueError(
            f"Invalid cron expression: expected 5 fields (minute hour day month weekday), got {len(parts)}"
        )

    field_defs = [
        ("minute", 0, 59),
        ("hour", 0, 23),
        ("day", 1, 31),
        ("month", 1, 12),
        ("weekday", 0, 6),
    ]

    values = []
    for (field_name, low, high), part in zip(field_defs, parts):
        values.append(_parse_field(part, low, high, field_name))

    return CronExpression(
        minutes=values[0],
        hours=values[1],
        days=values[2],
        months=values[3],
        weekdays=values[4],
        raw=expr,
    )


def _expand_shorthand(expr: str) -> str:
    """Expand @keyword shorthand to standard 5-field format."""
    shorthands = {
        "@yearly":   "0 0 1 1 *",
        "@annually": "0 0 1 1 *",
        "@monthly":  "0 0 1 * *",
        "@weekly":   "0 0 * * 0",
        "@daily":    "0 0 * * *",
        "@hourly":   "0 * * * *",
    }
    lower = expr.lower()
    if lower in shorthands:
        return shorthands[lower]

    if lower.startswith("@every "):
        dur = lower.replace("@every ", "").strip()
        minutes = _parse_duration(dur)
        if minutes < 1:
            raise ValueError(f"Invalid duration: {dur}")
        if minutes >= 60 and minutes % 60 == 0:
            hours = minutes // 60
            if hours >= 24 and hours % 24 == 0:
                return "0 0 * * *"
            return f"0 */{hours} * * *"
        return f"*/{minutes} * * * *"

    return expr


def _parse_duration(dur: str) -> int:
    """Parse a duration string like '5m', '1h', '2h30m' into minutes."""
    total = 0
    current = ""
    for ch in dur:
        if ch.isdigit():
            current += ch
        elif ch == "h":
            total += int(current or "0") * 60
            current = ""
        elif ch == "m":
            total += int(current or "0")
            current = ""
        elif ch == "d":
            total += int(current or "0") * 1440
            current = ""
        else:
            raise ValueError(f"Invalid duration character: {ch}")
    if current:
        total += int(current)
    return total


def _parse_field(field: str, low: int, high: int, name: str) -> set[int]:
    """Parse a single cron field into a set of valid values."""
    values = set()

    for part in field.split(","):
        part = part.strip()

        if part == "*":
            values.update(range(low, high + 1))
            continue

        step_match = re.match(r"^\*/(\d+)$", part)
        if step_match:
            step = int(step_match.group(1))
            if step < 1:
                raise ValueError(f"Invalid step in {name}: {part}")
            values.update(range(low, high + 1, step))
            continue

        range_match = re.match(r"^(\d+)-(\d+)(?:/(\d+))?$", part)
        if range_match:
            start = int(range_match.group(1))
            end = int(range_match.group(2))
            step = int(range_match.group(3)) if range_match.group(3) else 1
            if start < low or end > high or start > end:
                raise ValueError(f"Invalid range in {name}: {part}")
            values.update(range(start, end + 1, step))
            continue

        if part.isdigit():
            val = int(part)
            if val < low or val > high:
                raise ValueError(f"Value {val} out of range [{low}-{high}] for {name}")
            values.add(val)
            continue

        raise ValueError(f"Invalid {name} field: {part}")

    return values
