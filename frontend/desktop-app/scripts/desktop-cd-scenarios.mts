export type ScenarioKind =
  | 'standard'
  | 'approval'
  | 'cancel'
  | 'failure'
  | 'parallel-primary'
  | 'busy'
  | 'child-tree'
  | 'child-approval'
  | 'child-cancel'
  | 'lease-conflict'
  | 'budget'
  | 'mcp-skill-partial'
  | 'recovery'
  | 'stream-switch'

export interface DesktopCdScenario {
  id: `DTS-${string}`
  title: string
  kind: ScenarioKind
  prompt: string
  model: 'opencode-go/mimo-v2.5' | 'zen/gpt-5.6-luna'
  screenshotCheckpoints: string[]
}

const rows: Array<Omit<DesktopCdScenario, 'id' | 'model'>> = [
  { title: 'Python service startup audit', kind: 'standard', screenshotCheckpoints: ['terminal'], prompt: 'Act as a release engineer. Inspect the Python service startup chain from CLI entrypoint through configuration loading and appserver bootstrap. Use file discovery, symbol search, targeted reads, and a harmless verification command. Return a risk-ranked report with exact paths, assumptions, and reproducible commands; do not modify files.' },
  { title: 'Order cache TTL repair', kind: 'standard', screenshotCheckpoints: ['terminal'], prompt: 'Investigate the order-cache TTL behavior as if a customer reported stale checkout totals. Read implementation and tests, trace invalidation across at least three modules, propose the smallest safe repair, and run focused plus neighboring regression tests. Include rollback advice and evidence for every conclusion.' },
  { title: 'Production incident investigation', kind: 'standard', screenshotCheckpoints: ['terminal'], prompt: 'Investigate a production timeout incident. Correlate appserver watchdog behavior, session lifecycle, transport events, and user-visible failure handling. Use repository search, code reads, and test evidence. Produce root cause, blast radius, immediate mitigation, durable fix, and a validation matrix.' },
  { title: 'Skill-driven API migration', kind: 'standard', screenshotCheckpoints: ['terminal'], prompt: 'Load the repository coding workflow Skill and plan a backward-compatible API migration. Read the relevant contracts, identify all producers and consumers, include a staged rollout with feature flags, tests, observability, and rollback. Clearly distinguish facts from inferred risks.' },
  { title: 'Workspace MCP contract audit', kind: 'standard', screenshotCheckpoints: ['terminal'], prompt: 'Use the configured workspace MCP to locate three business-contract documents, compare field naming and nullability with the local protocol types, then produce a compatibility memo. Include MCP evidence, local code references, ambiguous fields, and a no-downtime migration sequence.' },
  { title: 'Competitor research ADR', kind: 'standard', screenshotCheckpoints: ['terminal'], prompt: 'Research current agent desktop interaction patterns using approved external search plus local product requirements. Compare task navigation, activity evidence, approval UX, and recovery. Write a source-backed ADR with adopted and rejected ideas; do not copy brands or proprietary assets.' },
  { title: 'Git and CI failure triage', kind: 'standard', screenshotCheckpoints: ['terminal'], prompt: 'Audit the current Git worktree and CI configuration. Find likely failing checks, inspect workflow dependencies, identify platform-specific risks, and provide a minimal patch plan with exact local verification commands. Preserve unrelated user changes.' },
  { title: 'Payment security review', kind: 'standard', screenshotCheckpoints: ['terminal'], prompt: 'Perform a read-only security review of the payment module. Trace credential access, redaction, logging, subprocess boundaries, and approval gates. Run safe static checks and return a severity table with evidence, exploit preconditions, and remediation tests.' },
  { title: 'Database migration approval', kind: 'approval', screenshotCheckpoints: ['approval', 'terminal'], prompt: 'Prepare a database migration preflight that reads schema and migration history, generates a reversible SQL artifact in the test workspace, runs validation, and pauses for explicit approval before any write. Explain the exact scope and risk in the approval request. approval demo' },
  { title: 'Temporary file cleanup approval', kind: 'approval', screenshotCheckpoints: ['approval', 'terminal'], prompt: 'Audit temporary release files, produce a deletion manifest and hashes, then request approval before writing the manifest. Continue only after approval, verify the artifact, and summarize what was intentionally not deleted. approval demo' },
  { title: 'Long multi-tool session isolation', kind: 'standard', screenshotCheckpoints: ['terminal'], prompt: 'Analyze a multi-file refactor using repository search, reads, a Skill, an MCP lookup, and non-mutating tests. Keep evidence grouped by subsystem and produce a final implementation map. This task will run beside other sessions, so never rely on active-session global state.' },
  { title: 'User cancellation during tool', kind: 'cancel', screenshotCheckpoints: ['running', 'cancelled'], prompt: 'Start a deliberately slow dependency diagnosis, stream intermediate evidence, and begin a harmless long-running verification tool so the user can cancel. After cancellation, no tool or final-success state may remain active. slow demo' },
  { title: 'MCP failure recovery', kind: 'failure', screenshotCheckpoints: ['failed'], prompt: 'Call a deliberately unavailable external MCP, preserve the protocol error, stop cleanly, and explain recovery options without hiding the failure. The GUI must remain usable for a new task. fail demo' },
  { title: 'Cross-module implementation brief', kind: 'standard', screenshotCheckpoints: ['terminal'], prompt: 'Analyze a cross-module refactor involving a Skill, MCP search, repository reads, proposed writes, and tests. Return a dependency graph, ownership boundaries, compatibility rules, acceptance commands, and a conflict-avoidance sequence.' },
  { title: 'Zen Luna release audit', kind: 'standard', screenshotCheckpoints: ['terminal'], prompt: 'Perform a high-confidence release audit with zen/gpt-5.6-luna. Inspect changed files, protocol compatibility, desktop build and regression evidence. Return blockers, non-blockers, exact commands, and a concise go/no-go decision. Never route this model through the Go gateway.' },
  { title: 'Approval rejection and recovery', kind: 'approval', screenshotCheckpoints: ['approval', 'terminal'], prompt: 'Prepare a risky workspace write, show a precise approval request, tolerate rejection without converting it to success, then provide a safe read-only alternative and recovery steps. approval demo' },
  { title: 'Theme and diagnostics workflow', kind: 'standard', screenshotCheckpoints: ['terminal'], prompt: 'Audit desktop theme tokens, diagnostics placement, connection status, and keyboard navigation across light and dark themes. Use code evidence and return a prioritized UI defect list with WCAG-oriented acceptance checks.' },
  { title: 'Workspace switching isolation', kind: 'standard', screenshotCheckpoints: ['terminal'], prompt: 'Simulate a consultant switching between two repositories. Verify task history, workspace roots, tools, model selection, and approvals cannot leak across sessions. Return a concrete isolation checklist and tests.' },
  { title: 'Four release audits in parallel', kind: 'parallel-primary', screenshotCheckpoints: ['parallel', 'terminal'], prompt: 'Run four independent release-audit sessions concurrently: protocol compatibility, desktop accessibility, packaging/runtime, and test reliability. Each must use multiple evidence sources and preserve its own stream, tools, errors, usage, and final answer. Summarize overlap and prove execution intervals overlapped.' },
  { title: 'Same-session busy guard', kind: 'busy', screenshotCheckpoints: ['busy', 'terminal'], prompt: 'Submit this long repository audit twice to the same Primary session. The first run should continue; the duplicate must receive a stable busy state without corrupting the first stream, tool cards, usage, or final answer.' },
  { title: 'Explore and scout incident children', kind: 'child-tree', screenshotCheckpoints: ['agents', 'terminal'], prompt: '@explore @scout Investigate a production incident concurrently. Explore local code and tests; scout external operational guidance. Use a relevant Skill, merge evidence in the Primary, show the full child tree, and label partial or conflicting findings.' },
  { title: 'Two isolated Primary trees', kind: 'child-tree', screenshotCheckpoints: ['agents', 'terminal'], prompt: 'Run two Primary sessions concurrently. Each Primary must dispatch its own explore and reviewer children. Prove child trees, event cursors, tools, usage, approvals, and final summaries remain isolated even when child ids and tool names are similar.' },
  { title: 'Explicit payment reviewer', kind: 'child-tree', screenshotCheckpoints: ['agents', 'terminal'], prompt: '@reviewer Review the payment module through an explicit invocation. Navigate between Parent and Child evidence, keep the reviewer read-only, and return findings with exact files, severity, and rejected false positives.' },
  { title: 'Child-owned migration approval', kind: 'child-approval', screenshotCheckpoints: ['approval', 'agents', 'terminal'], prompt: 'Dispatch a leased-write migration child that must wait for approval while a read-only sibling continues schema analysis. The approval UI must identify child, agent, rule, and path. Merge both outcomes without blocking the sibling.' },
  { title: 'Recursive Parent cancellation', kind: 'child-cancel', screenshotCheckpoints: ['agents', 'cancelled'], prompt: 'Start a Primary investigation with multiple active children, then cancel the Parent after discovering the wrong workspace. All descendants, tools, leases, and pending RPCs must terminate while a separate Primary session continues normally.' },
  { title: 'Leased write conflict and retry', kind: 'lease-conflict', screenshotCheckpoints: ['agents', 'conflict', 'terminal'], prompt: 'Dispatch two leased-write children targeting the same migration file. Exactly one lease may write; the sibling must enter an explainable conflict state. After release, retry the blocked child and verify the artifact hash and event history.' },
  { title: 'Budget terminal-state matrix', kind: 'budget', screenshotCheckpoints: ['agents', 'terminal'], prompt: 'Run a cost-limited audit that exercises concurrency, step, token, wall-time, and depth limits. Each child must end in an explainable terminal state with the governing limit, actual usage when reported, and no orphan work.' },
  { title: 'MCP failure plus Skill success', kind: 'mcp-skill-partial', screenshotCheckpoints: ['agents', 'terminal'], prompt: 'Reconcile invoices with two children: one calls the real local invoice MCP and intentionally encounters a controlled failure; the other loads the real reconciliation Skill and succeeds. The Primary must return an honest partial-success summary with evidence and no fabricated token values.' },
  { title: 'Worker reconnect and cursor replay', kind: 'recovery', screenshotCheckpoints: ['reconnecting', 'agents', 'terminal'], prompt: 'Interrupt appserver/worker transport after child events have started, reconnect, replay from the persisted cursor, and rebuild the child tree. Assert no duplicate terminal events, no status regression, no cursor gap, and no rerun of completed work.' },
  { title: 'Zen Luna long-stream switching', kind: 'stream-switch', screenshotCheckpoints: ['streaming', 'agents', 'terminal'], prompt: 'Using zen/gpt-5.6-luna, conduct a long streaming release audit with Parent and isolated children. Rapidly switch among Parent, Child evidence, and another Primary session. Verify frame-coalesced text never crosses sessions, user scroll position is respected, and usage is reported or explicitly not_reported. Never use the Go gateway for Luna.' }
]

export const desktopCdScenarios: DesktopCdScenario[] = rows.map((row, index) => {
  const id = `DTS-${String(index + 1).padStart(2, '0')}` as const
  return {
    ...row,
    id,
    model: index === 14 || index === 29
      ? 'zen/gpt-5.6-luna'
      : 'opencode-go/mimo-v2.5'
  }
})

if (desktopCdScenarios.length !== 30 || new Set(desktopCdScenarios.map((item) => item.id)).size !== 30) {
  throw new Error('desktop CD suite must define exactly 30 unique scenarios')
}
