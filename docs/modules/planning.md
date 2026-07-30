# planning/ - Task Planning

## What Is This Module?
Decomposes complex user requests into structured task trees. Uses LLM-based hierarchical decomposition to break tasks into executable subtasks.

## Key Files
| File | Purpose |
|------|---------|
| decomposer.py | HierarchicalDecomposer - breaks tasks into subtask trees |
| goal_planner.py | GoalPlanner - high-level goal analysis and planning |

## Core Code: decomposer.py

**Classes:**
- SubTask(BaseModel): Individual subtask with description, tools_hint,
  dependencies, and a `TaskEffect`
- SubTaskList(BaseModel): List of subtasks returned by LLM
- HierarchicalDecomposer: Recursive task decomposition

`TaskEffect` is persisted on every `TaskNode`: `read` restricts executor tool
selection to READ risk, while `write` and `danger` require verified mutating
tool evidence before validation can pass. `auto` is the backward-compatible
default for older plans; validation then infers side-effect requirements from
tool hints, task intent, and completion claims, so `auto` is not an evidence
bypass.

**Decomposition Flow:**
1. Take a task node from the TaskTree
2. Ask LLM to decompose it into subtasks (using structured output)
3. For each subtask, recursively decompose if it is still complex (max_depth=4)
4. Leaf nodes are executable tasks

**Key Methods:**
- decompose(tree, memory_context) -> TaskTree: Main decomposition entry point
- _decompose_recursive(tree, node, memory_context): Recursive decomposition

**Complexity Heuristic:**
- Simple tasks (single tool, clear description) become leaf nodes
- Complex tasks (multiple steps, dependencies) are decomposed further
- Max depth: 4 levels to prevent infinite recursion

## Core Code: goal_planner.py

**Purpose:** High-level goal analysis before decomposition.

**Key Methods:**
- plan(user_input, memory_context) -> dict: Analyze user intent and suggest approach
- Returns: {goal, approach, estimated_complexity, suggested_mode}
