"""Interactive question tool with native async API and CLI transports."""
from __future__ import annotations

import asyncio
from typing import Literal

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field


class Option(BaseModel):
    label: str = Field(description="Option display label")
    value: str = Field(description="Option value")


class Question(BaseModel):
    question: str = Field(description="Question text")
    header: str = Field(default="", description="Header/title for the question")
    options: list[Option] = Field(
        default_factory=list, description="Multiple choice options"
    )
    multiple: Literal[False] = Field(
        default=False,
        description="Only single selection is supported; multiple=true is invalid",
    )


class QuestionInput(BaseModel):
    questions: list[Question] = Field(description="Questions to ask the user")


def _as_mapping(value) -> dict:
    if isinstance(value, dict):
        return value
    model_dump = getattr(value, "model_dump", None)
    return model_dump() if callable(model_dump) else {}


async def _ask_via_question_broker(questions: list[dict]) -> str | None:
    """Delegate API questions without reusing the safety-approval protocol."""
    try:
        from ..core.question import (
            QuestionOption,
            QuestionRequest,
            get_question_broker,
        )
    except Exception:
        return None

    broker = get_question_broker()
    if broker is None:
        return None

    answers = []
    for raw_question in questions:
        question = _as_mapping(raw_question)
        text = question.get("question", "")
        options = [_as_mapping(option) for option in question.get("options", [])]
        request = QuestionRequest(
            question=text,
            header=str(question.get("header", "")),
            options=[
                QuestionOption(
                    label=str(option.get("label", option.get("value", ""))),
                    value=str(option.get("value", option.get("label", ""))),
                )
                for option in options
            ],
        )
        response = await broker.ask(request)
        if response.unavailable:
            answers.append("[no input: question channel unavailable]")
            break
        if response.timed_out:
            answers.append("[no input: question timed out]")
            break
        if response.cancelled:
            answers.append("[cancelled: question]")
            break
        answers.append(response.answer or "")
    return "\n".join(
        f"A{index + 1}: {answer}" for index, answer in enumerate(answers)
    )


def _ask_questions_from_stdin(questions: list[dict]) -> str:
    try:
        from ..utils.tui import get_tui
        tui = get_tui()
    except Exception:
        tui = None

    answers = []
    for raw_question in questions:
        question = _as_mapping(raw_question)
        header = question.get("header", "")
        text = question.get("question", "")
        options = [_as_mapping(option) for option in question.get("options", [])]

        display = f"\n[{header}] {text}" if header else f"\n{text}"
        if tui:
            tui.write(display, "class:output.question")

        if options:
            for index, option in enumerate(options, 1):
                label = option.get("label", option.get("value", ""))
                if tui:
                    tui.write(f"  {index}. {label}", "class:output.question")
            try:
                choice = input("Enter choice number: ").strip()
                option_index = int(choice) - 1
                if 0 <= option_index < len(options):
                    selected = options[option_index]
                    answers.append(selected.get("value", selected.get("label", "")))
                else:
                    answers.append(choice)
            except (ValueError, EOFError):
                answers.append("[no input]")
        else:
            try:
                answers.append(input("Your answer: ").strip())
            except EOFError:
                answers.append("[no input]")

    return "\n".join(
        f"A{index + 1}: {answer}" for index, answer in enumerate(answers)
    )


def ask_questions(questions: list[dict]) -> str:
    """Synchronous compatibility entry point for direct/legacy callers."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        via_broker = asyncio.run(_ask_via_question_broker(questions))
        if via_broker is not None:
            return via_broker
        return _ask_questions_from_stdin(questions)
    raise RuntimeError(
        "ask_questions() cannot block an active event loop; "
        "use ask_questions_async()"
    )


async def ask_questions_async(questions: list[dict]) -> str:
    """Ask questions without blocking or switching event loops."""
    via_broker = await _ask_via_question_broker(questions)
    if via_broker is not None:
        return via_broker
    return await asyncio.to_thread(_ask_questions_from_stdin, questions)


question_tool = StructuredTool(
    name="question",
    description=(
        "Ask the user questions and wait for responses. "
        "Supports multiple choice and free text."
    ),
    func=ask_questions,
    coroutine=ask_questions_async,
    args_schema=QuestionInput,
)
