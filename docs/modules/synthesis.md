# synthesis/ - Result Synthesis

## What Is This Module?
Combines execution results from all subtasks into a coherent final response for the user. Runs as the last node in the LangGraph pipeline.

## Key Files
| File | Purpose |
|------|---------|
| synthesizer.py | OutputSynthesizer - merges subtask results into final answer |

## Core Code: synthesizer.py (OutputSynthesizer)

**How It Works:**
1. Collects completed and cancelled leaf tasks from the TaskTree
2. Formats completed results plus cancellation reasons and status
3. Asks LLM to synthesize a coherent response
4. Appends a deterministic incomplete-task disclosure when results are mixed
5. Returns a `[Build incomplete: ...]` failure when no task completed

**Key Methods:**
- synthesize(tree, user_input) -> str: Main synthesis entry point
- collect_results(tree) -> list[dict]: Extract all results from tree nodes

**Output Format:**
- Preserves task structure in the response
- Never silently omits cancelled subtasks
- Maintains original user intent focus
