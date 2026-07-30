"""System datetime tool."""

from datetime import datetime
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field


class DatetimeInput(BaseModel):
    format: str = Field(default="%Y-%m-%d %H:%M:%S", description="Output format (strftime format)")


def get_datetime(format: str = "%Y-%m-%d %H:%M:%S") -> str:
    """Get current system date and time."""
    now = datetime.now()
    try:
        return now.strftime(format)
    except ValueError:
        return now.strftime("%Y-%m-%d %H:%M:%S")


datetime_tool = StructuredTool.from_function(
    func=get_datetime,
    name="datetime",
    description="Get current system date and time. Use this when user asks about today's date, current time, or datetime.",
    args_schema=DatetimeInput,
)
