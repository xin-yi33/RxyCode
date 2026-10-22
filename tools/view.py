"""view tool - View file contents with line numbers."""

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from .read import read_file


class ViewInput(BaseModel):
    filePath: str = Field(description="Path to the file to view")
    offset: int = Field(default=1, description="Line number to start from (1-indexed)")
    limit: int = Field(default=2000, description="Maximum number of lines to show")


def run_view(filePath: str, offset: int = 1, limit: int = 2000) -> str:
    # 废弃入口（2026-10-13）：view 不再单独注册到模型。旧 Python 调用保留
    # 2000 行默认值，读取实现统一委托 read，避免两套文件读取行为继续漂移。
    return read_file(filePath, offset, limit)


view_tool = StructuredTool(
    name="view",
    description="View file contents with line numbers. Supports offset and limit for large files.",
    func=run_view,
    args_schema=ViewInput,
)
