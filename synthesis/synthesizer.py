"""OutputSynthesizer: aggregate all leaf task results into a final answer."""

from __future__ import annotations

import json

from RxyCode.RxyCode1_1_0.core.state import TaskStatus, TaskTree
from RxyCode.RxyCode1_1_0.core.prompts import (
    build_user_message,
    get_role_prompt,
    get_system_prompt,
)
from RxyCode.RxyCode1_1_0.planning.structured_output import invoke_structured_output
from RxyCode.RxyCode1_1_0.validation.final_output import (
    GroundedSynthesis,
    build_grounding_sources,
)


class OutputSynthesizer:
    def __init__(self, llm):
        self._llm = llm

    async def synthesize_grounded(
        self,
        tree: TaskTree,
        user_input: str,
    ) -> GroundedSynthesis:
        sources = build_grounding_sources(tree)
        cancelled_tasks = []
        for node in tree.get_leaf_nodes():
            if node.status == TaskStatus.CANCELLED:
                reason = (
                    node.result
                    or (node.error_history[-1] if node.error_history else "")
                    or "cancelled before completion"
                )
                cancelled_tasks.append(
                    {
                        "title": node.title,
                        "depth": node.depth,
                        "status": node.status.value,
                        "reason": reason[:500],
                        "parent_id": node.parent_id,
                    }
                )
        if not sources:
            cancelled_titles = ", ".join(
                task["title"] for task in cancelled_tasks
            )
            suffix = (
                f" Cancelled tasks: {cancelled_titles}."
                if cancelled_titles
                else ""
            )
            return GroundedSynthesis(
                answer=(
                    "[Build incomplete: No completed tasks to synthesize."
                    f"{suffix}]"
                )
            )
        task_content = (
            f"User request: {user_input}\n"
            f"Constraints: {', '.join(tree.constraints) if tree.constraints else '(none)'}\n"
            f"Output format: {tree.output_format}\n\n"
            "Verified grounding sources:\n"
            f"{json.dumps([source.model_dump() for source in sources], ensure_ascii=False, indent=2)}\n\n"
            "Return a JSON object with answer and claims. Each claim must contain "
            "task_id, source_id, and text. Claim text MUST be an exact non-empty "
            "substring of that source's text; do not paraphrase or add facts. "
            "The answer MUST equal all claim texts joined in claim order by two "
            "newlines, with no headings, commentary, or other text. Cite every "
            "passed task and every source where required=true."
        )
        if cancelled_tasks:
            task_content += (
                "\n\nCancelled/incomplete sub-tasks:\n"
                f"{json.dumps(cancelled_tasks, ensure_ascii=False, indent=2)}\n\n"
                "The final answer must explicitly state that these tasks were "
                "not completed and must not claim the full request succeeded."
            )
        user_msg = build_user_message(get_role_prompt("synthesizer"), task_content)
        from langchain_core.messages import HumanMessage, SystemMessage
        messages = [
            SystemMessage(content=get_system_prompt()),
            HumanMessage(content=user_msg),
        ]
        return await invoke_structured_output(
            self._llm,
            messages,
            GroundedSynthesis,
        )

    async def synthesize(self, tree: TaskTree, user_input: str) -> str:
        """Backward-compatible string facade over the grounded contract."""
        result = await self.synthesize_grounded(tree, user_input)
        return result.answer

    def collect_results(self, tree: TaskTree) -> list[dict]:
        results = []
        for node in tree.get_leaf_nodes():
            if node.status == TaskStatus.PASSED and node.result:
                results.append({
                    "id": node.id,
                    "title": node.title,
                    "depth": node.depth,
                    "result": node.result,
                    "parent_id": node.parent_id,
                })
        return results
