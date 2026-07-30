# validation/ - Result Validation

## What Is This Module?
Validates execution results against user requirements. Triggers re-planning when results are insufficient.

## Key Files
| File | Purpose |
|------|---------|
| validator.py | Validator - deterministic evidence checks plus structured scoring |
| side_effects.py | Detects tasks/claims that require WRITE/DANGER evidence |
| final_output.py | Verifies claim-to-evidence grounding and live artifacts |
| re_planner.py | RePlanner - generates new plans when validation fails |

## Core Code: validator.py

**Classes:**
- ValidationResult(BaseModel): Contains passed, three scores, issues, and suggestion
- Validator: deterministic evidence validation followed by LLM scoring

**Validation Flow:**
1. Reject failed/malformed tool evidence and abnormal executor sentinels
2. Require an executed, successful WRITE/DANGER `ToolEvidence` whenever
   `TaskEffect` is `write`/`danger`, or when `auto` plus hints/intent/claims
   indicate a side effect
3. Only then ask the LLM for completeness, relevance, and format scores
4. All three scores must meet `pass_threshold` (default 0.7)
5. After synthesis, require every final claim to be a verbatim excerpt from a
   passed leaf result or successful tool evidence; required side-effect
   evidence must be cited, and artifact existence/size/SHA-256 is rechecked

**Key Methods:**
- validate(title, description, requirement, result, evidence, tools_hint, effect) -> ValidationResult

## Core Code: re_planner.py

**Purpose:** Generates revised plans when validation fails.

**Key Methods:**
- replan(original_task, failed_result, feedback) -> list[SubTask]
- Takes validation feedback and creates targeted retry subtasks
- Limits replanning attempts to prevent infinite loops
