# Expert teams

RxyCode can run a coordinator-led expert team instead of a single AgentV2 loop. The code lives in `core/agents/` and `protocol/agents.py`.

**Default is off.** `settings.agents.enabled=false`. Leave it off for single-file fixes, small refactors, and read-only questions. Cost measurements on the built-in matrix put teams at about **3.0× tokens** and **2.5× wall time** without a completion-rate gain (`evals/baselines/f14-e0-matrix.md`).

## What it is

- **AgentSpec / TeamSpec** — static role, tools, budgets, SOP stages.
- **SopMachine** — deterministic stage transitions (`next_on_success` / `next_on_failure`). The only LLM routing decision is `choose_failure_target` when several failure targets exist.
- **Coordinator** — create the team, assign work, relay messages, close the run. Members do not talk to each other directly.
- **BudgetGuard** — token budget, wall clock, delegation count, consult count. Any gate stops the team and returns a partial result.
- **Mechanical verifier** — file/parse/lint/test checks before an LLM audit; result bound to a subject hash.
- **ModeRouter** — solo vs team. With the flag off, the router always stays solo.
- **JSON-RPC worker bridge** — optional external workers.

A builtin SOP is `core/agents/teams/software_dev/team.yaml`.

## When not to use it

- Everyday single-agent work (the default path)
- Tasks that must share one serial context
- Runs without an explicit token budget

Consider enabling only for structured split work (separate modules, an independent audit) where the mechanical gate can catch fake completion and you accept the extra cost.

## Design notes

Full constraints, SOP fields, and the cost matrix: [modules/agents.md](../modules/agents.md).
