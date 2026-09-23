"""ReAct finish action: calling this tool is exit condition 2."""

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field


class FinalAnswerInput(BaseModel):
    result: str = Field(description="The complete user-visible Final Answer")


def submit_final_answer(result: str) -> str:
    """Return the Final Answer. The harness stops the loop after this call."""
    return str(result or "")


final_answer_tool = StructuredTool.from_function(
    func=submit_final_answer,
    name="final_answer",
    description=(
        "Call this when the task is complete or you are giving the "
        "user-visible Final Answer. This is an exit: do not call any other "
        "tool after it. Put the full answer in `result`."
    ),
    args_schema=FinalAnswerInput,
)
