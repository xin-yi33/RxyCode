#!/usr/bin/env node
/**
 * Deterministic fake appserver for the Desktop UI (no LLM, no Python).
 *
 * Speaks the same newline-delimited JSON-RPC protocol as
 * `python -m appserver` and replays the Phase4-D3 event sequences the
 * renderer must handle: message_delta streaming, tool_begin/tool_end
 * cards, event/final, event/done, event/error, and session/interrupt.
 *
 * Phase4-D4 adds approval scenarios driven by prompt text:
 *   "approval demo"   -> WRITE approval/request with a unique action, waits
 *                        for the client decision, then completes the run
 *   "approval reject" -> same flow with a fixed action for the reject demo
 *   "approval auto"   -> fixed action so a persisted always-allow rule can
 *                        auto-approve without the modal appearing
 *
 * Prompt text drives the scenario:
 *   "tool demo" -> streaming text + two tool cards + final + done
 *   "slow demo" -> streaming text + running tool card, waits for interrupt
 *   "fail demo" -> event/error + event/done failed + RPC error
 *   anything else -> streaming text + final + done
 */
/* eslint-disable @typescript-eslint/explicit-function-return-type -- plain JS protocol script */
import { createInterface } from 'node:readline'

const rl = createInterface({ input: process.stdin, crlfDelay: Infinity })
let sessionCounter = 0
const pendingPrompts = new Map()
const pendingServerRequests = new Map()
const childEventsByRoot = new Map()
const childSessionsByRoot = new Map()
const sessionRecords = new Map()
const sessionEvents = new Map()
let childEventSequence = 0
let sessionEventSequence = 0
let activeModel = 'opencode-go/deepseek-v4-flash'

const FAKE_MODELS = [
  {
    id: 'opencode-go/deepseek-v4-flash', name: 'deepseek-v4-flash', nickname: 'DeepSeek V4 Flash',
    provider_model_id: 'deepseek-v4-flash', base_url: 'https://opencode.ai/zen/go/v1',
    category: 'DeepSeek', provider_name: 'DeepSeek', provider_id: 'opencode-go',
    context_window: 128000, resolved_max_tokens: 16384, limit_source: 'model_metadata'
  },
  {
    id: 'zen/gpt-5.6-luna', name: 'gpt-5.6-luna', nickname: 'GPT-5.6 Luna',
    provider_model_id: 'gpt-5.6-luna', base_url: 'https://opencode.ai/zen/v1',
    category: 'Zen', provider_name: 'Zen', provider_id: 'zen',
    context_window: 200000, resolved_max_tokens: 32768, limit_source: 'model_metadata'
  },
  {
    id: 'glm/glm-4.5', name: 'glm-4.5', nickname: 'GLM 4.5',
    provider_model_id: 'glm-4.5', base_url: 'https://open.bigmodel.cn/api/paas/v4',
    category: 'GLM', provider_name: 'GLM', provider_id: 'glm',
    context_window: 128000, resolved_max_tokens: 16384, limit_source: 'model_metadata'
  }
]

function send(message) {
  process.stdout.write(`${JSON.stringify(message)}\n`)
}

function notify(method, params) {
  const sessionId = typeof params?.session_id === 'string' ? params.session_id : null
  if (sessionId !== null && method.startsWith('event/')) {
    const events = sessionEvents.get(sessionId) ?? []
    events.push({ event_id: `session-event-${++sessionEventSequence}`, seq: sessionEventSequence, method, params })
    sessionEvents.set(sessionId, events)
    if (method === 'event/done' && typeof params.status === 'string') ensureTask(sessionId, { status: params.status })
    if (method === 'event/token_usage') {
      ensureTask(sessionId, { usage: {
        input_tokens: params.input_tokens ?? null,
        output_tokens: params.output_tokens ?? null,
        cache_hit_tokens: params.cache_hit_tokens ?? null,
        cache_write_tokens: params.cache_write_tokens ?? null,
        cache_hit_rate: params.cache_hit_rate ?? null,
        reporting_status: params.reporting_status ?? 'not_reported'
      } })
    }
  }
  send({ jsonrpc: '2.0', method, params })
}

function ensureTask(sessionId, overrides = {}) {
  const current = sessionRecords.get(sessionId) ?? {
    session_id: sessionId,
    title: 'New task',
    workspace_root: process.cwd(),
    model_id: activeModel,
    provider_id: activeModel.split('/')[0] ?? '',
    status: 'queued',
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
    trashed_at: null,
    child_count: 0,
    usage: {
      input_tokens: null, output_tokens: null, cache_hit_tokens: null,
      cache_write_tokens: null, cache_hit_rate: null, reporting_status: 'not_reported'
    }
  }
  const next = { ...current, ...overrides, updated_at: new Date().toISOString() }
  sessionRecords.set(sessionId, next)
  return next
}

function taskList(includeTrashed = false) {
  return [...sessionRecords.values()].filter((task) => includeTrashed || task.trashed_at === null)
}

function notifyChild(method, rootSessionId, parentSessionId, sessionId, payload = {}) {
  const event = {
    event_id: `child-event-${++childEventSequence}`,
    event_name: method,
    seq: childEventSequence,
    timestamp: Date.now() / 1000,
    root_session_id: rootSessionId,
    parent_session_id: parentSessionId,
    session_id: sessionId,
    request_id: `request-${sessionId}`,
    definition_version: 'fake-v1',
    redaction_metadata: '',
    payload
  }
  const events = childEventsByRoot.get(rootSessionId) ?? []
  events.push(event)
  childEventsByRoot.set(rootSessionId, events)
  const sessions = childSessionsByRoot.get(rootSessionId) ?? new Map()
  const previous = sessions.get(sessionId) ?? {}
  const status = String(payload.status ?? method.slice('child_session/'.length))
  sessions.set(sessionId, {
    ...previous,
    session_id: sessionId,
    parent_session_id: parentSessionId,
    root_session_id: rootSessionId,
    agent_id: payload.agent_id ?? previous.agent_id ?? 'child',
    status,
    created_at: previous.created_at ?? new Date().toISOString(),
    started_at: method === 'child_session/started' ? new Date().toISOString() : previous.started_at ?? null,
    terminal_at: ['completed', 'failed', 'cancelled', 'timed_out', 'denied'].includes(status) ? new Date().toISOString() : null,
    trigger: 'automatic',
    definition_version: 'fake-v1',
    event_cursor: event.seq
  })
  childSessionsByRoot.set(rootSessionId, sessions)
  notify(method, event)
  return event
}

function respond(id, result) {
  send({ jsonrpc: '2.0', id, result })
}

function respondError(id, code, message) {
  send({ jsonrpc: '2.0', id, error: { code, message } })
}

function sendServerRequest(method, params) {
  return new Promise((resolve, reject) => {
    const id = `srv-${++sessionCounter}-${Date.now().toString(36)}`
    pendingServerRequests.set(id, { resolve, reject })
    send({ jsonrpc: '2.0', id, method, params })
  })
}

const sleep = (ms) => new Promise((resolveWait) => setTimeout(resolveWait, ms))

const STRESS_TOOL_CATALOG = [
  ['glob', 'matched 8 project files'],
  ['grep', 'found 3 relevant call sites'],
  ['read', 'read 2,184 bytes'],
  ['skill', 'loaded coding-workflow instructions'],
  ['mcp__workspace__search', 'MCP workspace search returned 4 records'],
  ['websearch', 'collected 3 source summaries'],
  ['bash', 'verification command exited 0'],
  ['write', 'wrote validated workspace artifact'],
  ['git', 'working tree inspected']
]

async function runStressPrompt(requestId, sessionId, text) {
  const runId = `stress-${++sessionCounter}`
  const match = text.match(/\[DTS-(\d{2})\]/)
  const index = Number(match?.[1] ?? 0)
  const tools = [0, 1, 2].map((offset) => STRESS_TOOL_CATALOG[(index + offset) % STRESS_TOOL_CATALOG.length])
  notify('event/plan', { session_id: sessionId, steps: ['Inspect evidence', 'Run checks', 'Summarize'] })
  notify('event/step', { session_id: sessionId, index: 1, total: 3, text: 'Inspect evidence' })
  notify('event/progress', { session_id: sessionId, text: `DTS-${String(index).padStart(2, '0')} is collecting evidence` })
  if (index >= 21) {
    const first = `${sessionId}-explore-${index}`
    const second = `${sessionId}-review-${index}`
    notifyChild('child_session/created', sessionId, sessionId, first, { agent_id: 'explore', status: 'created' })
    notifyChild('child_session/queued', sessionId, sessionId, first, { agent_id: 'explore', status: 'queued' })
    notifyChild('child_session/started', sessionId, sessionId, first, { agent_id: 'explore', status: 'running' })
    notifyChild('child_session/created', sessionId, sessionId, second, { agent_id: index === 28 ? 'invoice-mcp' : 'reviewer', status: 'created' })
    notifyChild('child_session/started', sessionId, sessionId, second, { agent_id: index === 28 ? 'invoice-mcp' : 'reviewer', status: 'running' })
    notifyChild('child_session/progress', sessionId, sessionId, first, {
      agent_id: 'explore', status: 'running', text: `Child explore is inspecting DTS-${String(index).padStart(2, '0')}`, tool_name: 'grep'
    })
    notifyChild('child_session/tool_call', sessionId, sessionId, second, {
      agent_id: index === 28 ? 'invoice-mcp' : 'reviewer', status: 'running', text: 'Child is collecting isolated evidence', tool_name: index === 28 ? 'mcp__invoice__lookup' : 'read'
    })
    await sleep(80)
    if (index === 27) {
      notifyChild('child_session/timed_out', sessionId, sessionId, first, { agent_id: 'explore', status: 'timed_out', limit: 'wall_time' })
      notifyChild('child_session/denied', sessionId, sessionId, second, { agent_id: 'reviewer', status: 'denied', limit: 'depth' })
    } else if (index === 28) {
      notifyChild('child_session/failed', sessionId, sessionId, second, { agent_id: 'invoice-mcp', status: 'failed', error: 'controlled MCP failure' })
      notifyChild('child_session/completed', sessionId, sessionId, first, { agent_id: 'reconciliation-skill', status: 'completed' })
    } else if (index !== 25) {
      notifyChild('child_session/completed', sessionId, sessionId, first, { agent_id: 'explore', status: 'completed' })
      notifyChild('child_session/completed', sessionId, sessionId, second, { agent_id: 'reviewer', status: 'completed' })
    }
  }
  notify('event/message_delta', {
    session_id: sessionId,
    text: `正在执行真实业务场景 DTS-${String(index).padStart(2, '0')}：分析、调用工具并验证结果。`
  })
  if (index === 25) {
    pendingPrompts.set(requestId, { sessionId, runId })
    notify('event/tool_begin', {
      session_id: sessionId,
      call_id: `stress-${runId}-leased-write`,
      tool_name: 'write',
      arguments: { path: 'migrations/wrong-workspace.sql' }
    })
    return
  }
  if (index === 29) {
    const recoveryId = `recovery-${runId}`
    const failedCallId = `stress-${runId}-recovery-failed`
    const replacementCallId = `stress-${runId}-recovery-replacement`
    notify('event/tool_begin', {
      session_id: sessionId, call_id: failedCallId, tool_name: 'read',
      arguments: { path: 'release/checklist.md' }
    })
    await sleep(40)
    notify('event/tool_end', {
      session_id: sessionId, call_id: failedCallId, ok: false,
      summary: 'temporary provider read failure', status: 'error'
    })
    notify('event/recovery_started', {
      session_id: sessionId, run_id: runId, recovery_id: recoveryId,
      source_call_id: failedCallId, recovery_kind: 'model_recovery',
      error_kind: 'tool_error', max_attempts: 3,
      event_id: `${recoveryId}-started`, seq: ++sessionEventSequence, timestamp: new Date().toISOString()
    })
    notify('event/recovery_analyzing', {
      session_id: sessionId, run_id: runId, recovery_id: recoveryId,
      event_id: `${recoveryId}-analyzing`, seq: ++sessionEventSequence, timestamp: new Date().toISOString()
    })
    notify('event/recovery_attempt', {
      session_id: sessionId, run_id: runId, recovery_id: recoveryId,
      attempt: 1, strategy: 'alternative_tool', replacement_call_id: replacementCallId,
      display_summary: 'Switched to a bounded read retry',
      event_id: `${recoveryId}-attempt-1`, seq: ++sessionEventSequence, timestamp: new Date().toISOString()
    })
    notify('event/tool_begin', {
      session_id: sessionId, call_id: replacementCallId, tool_name: 'read',
      arguments: { path: 'release/checklist.md', retry: true }
    })
    await sleep(40)
    notify('event/tool_end', {
      session_id: sessionId, call_id: replacementCallId, ok: true,
      summary: 'read recovered from alternate bounded path', status: 'succeeded'
    })
    notify('event/recovery_resolved', {
      session_id: sessionId, run_id: runId, recovery_id: recoveryId,
      attempts: 1, display_summary: 'Recovered automatically after one attempt',
      event_id: `${recoveryId}-resolved`, seq: ++sessionEventSequence, timestamp: new Date().toISOString()
    })
  }
  for (const [toolName, summary] of tools) {
    const callId = `stress-${runId}-${toolName}`
    notify('event/tool_begin', {
      session_id: sessionId,
      call_id: callId,
      tool_name: toolName,
      arguments: { scenario: index, source: 'desktop-stress' }
    })
    await sleep(160)
    notify('event/tool_end', {
      session_id: sessionId,
      call_id: callId,
      ok: true,
      summary,
      status: 'succeeded'
    })
  }
  const answer = `DTS-${String(index).padStart(2, '0')} 已完成：已分析上下文、执行 ${tools.length} 项工具操作并验证结果。`
  notify('event/token_usage', {
    session_id: sessionId,
    input_tokens: index % 4 === 0 ? null : 1000 + index,
    output_tokens: index % 4 === 0 ? null : 200 + index,
    cache_hit_tokens: index % 4 === 0 ? null : 400 + index,
    cache_write_tokens: null,
    reporting_status: index % 4 === 0 ? 'not_reported' : 'partial'
  })
  ensureTask(sessionId, {
    status: 'succeeded',
    usage: {
      input_tokens: index % 4 === 0 ? null : 1000 + index,
      output_tokens: index % 4 === 0 ? null : 200 + index,
      cache_hit_tokens: index % 4 === 0 ? null : 400 + index,
      cache_write_tokens: null,
      cache_hit_rate: index % 4 === 0 ? null : (400 + index) / (1000 + index),
      reporting_status: index % 4 === 0 ? 'not_reported' : 'partial'
    }
  })
  notify('event/final', { session_id: sessionId, run_id: runId, text: answer })
  notify('event/done', { session_id: sessionId, run_id: runId, status: 'succeeded' })
  respond(requestId, { run_id: runId, status: 'succeeded', text: answer })
}

async function runMentionChild(rootSessionId, agentId, prompt, requestId) {
  const childSessionId = `${rootSessionId}-${agentId}-${++sessionCounter}`
  notifyChild('child_session/created', rootSessionId, rootSessionId, childSessionId, {
    agent_id: agentId, status: 'created', request_id: requestId
  })
  notifyChild('child_session/queued', rootSessionId, rootSessionId, childSessionId, {
    agent_id: agentId, status: 'queued'
  })
  notifyChild('child_session/started', rootSessionId, rootSessionId, childSessionId, {
    agent_id: agentId, status: 'running'
  })
  notifyChild('child_session/progress', rootSessionId, rootSessionId, childSessionId, {
    agent_id: agentId, status: 'running', text: `@${agentId} is working on the delegated task`, tool_name: 'read'
  })
  await sleep(agentId === 'scout' ? 420 : 300)
  notifyChild('child_session/completed', rootSessionId, rootSessionId, childSessionId, {
    agent_id: agentId,
    status: 'completed',
    summary: `@${agentId} completed: ${prompt.slice(0, 120)}`,
    usage: {
      steps: 2,
      input_tokens: agentId === 'scout' ? 640 : 520,
      output_tokens: agentId === 'scout' ? 180 : 140,
      cache_hit_tokens: agentId === 'scout' ? 300 : 240,
      wall_time_ms: agentId === 'scout' ? 420 : 300,
      retry_count: 0
    }
  })
}

async function runApprovalPrompt(requestId, sessionId, text) {
  const runId = `demo-${++sessionCounter}`
  const isReject = text.includes('reject')
  const isAuto = text.includes('auto')
  const action = isAuto
    ? 'bash: write approval-auto.txt'
    : isReject
      ? 'bash: write approval-reject-demo.txt'
      : `bash: write approval-demo-${sessionCounter}.txt`
  const approvalId = `apr-${runId}`
  const dtsIndex = Number(text.match(/\[DTS-(\d{2})\]/)?.[1] ?? 0)
  const approvalChild = dtsIndex === 24 ? `${sessionId}-migration-24` : null
  if (approvalChild !== null) {
    notifyChild('child_session/created', sessionId, sessionId, approvalChild, { agent_id: 'migration-writer', status: 'created' })
    notifyChild('child_session/started', sessionId, sessionId, approvalChild, { agent_id: 'migration-writer', status: 'running' })
    notifyChild('child_session/progress', sessionId, sessionId, approvalChild, {
      agent_id: 'migration-writer', status: 'running', text: 'Child is preparing the migration write and waiting for approval', tool_name: 'read'
    })
    notifyChild('child_session/approval_required', sessionId, sessionId, approvalChild, { agent_id: 'migration-writer', status: 'approval', rule: 'leased_write', path: 'migrations/next.sql' })
  }

  notify('event/message_delta', {
    method: 'event/message_delta',
    session_id: sessionId,
    text: '请求执行写入操作…'
  })
  await sleep(400)
  notify('event/tool_begin', {
    method: 'event/tool_begin',
    session_id: sessionId,
    call_id: approvalId,
    tool_name: 'bash',
    arguments: { command: action.replace('bash: write ', '') }
  })

  let approved = false
  let approvalError = null
  try {
    const decision = await sendServerRequest('approval/request', {
      method: 'approval/request',
      session_id: sessionId,
      request_id: approvalId,
      risk_level: 'WRITE',
      action,
      details: {
        tool_name: 'bash',
        command: action.replace('bash: write ', ''),
        workspace_root: process.cwd()
      }
    })
    approved = decision?.decision === 'approved'
  } catch {
    approved = false
    approvalError = 'approval request failed'
  }

  if (approved) {
    await sleep(1200) // keep the "submitting" state visible for screenshots
    notify('event/tool_end', {
      method: 'event/tool_end',
      session_id: sessionId,
      call_id: approvalId,
      ok: true,
      summary: '写入完成',
      status: 'succeeded'
    })
    notify('event/message_delta', {
      method: 'event/message_delta',
      session_id: sessionId,
      text: '写入完成。'
    })
  } else {
    notify('event/tool_end', {
      method: 'event/tool_end',
      session_id: sessionId,
      call_id: approvalId,
      ok: false,
      summary: approvalError === null ? '用户已拒绝' : '审批异常',
      status: 'rejected'
    })
    notify('event/message_delta', {
      method: 'event/message_delta',
      session_id: sessionId,
      text: '操作已被拒绝。'
    })
  }

  if (approvalChild !== null) {
    notifyChild(
      approved ? 'child_session/completed' : 'child_session/denied',
      sessionId,
      sessionId,
      approvalChild,
      { agent_id: 'migration-writer', status: approved ? 'completed' : 'denied' }
    )
  }
  await sleep(300)
  notify('event/final', {
    method: 'event/final',
    session_id: sessionId,
    run_id: runId,
    text: approved ? '写入完成。' : '操作已被拒绝。'
  })
  notify('event/done', {
    method: 'event/done',
    session_id: sessionId,
    run_id: runId,
    status: approved ? 'succeeded' : 'failed'
  })
  respond(requestId, {
    run_id: runId,
    status: approved ? 'succeeded' : 'failed',
    text: approved ? '写入完成。' : '操作已被拒绝。'
  })
}

function isPlanPrompt(text, mode) {
  if (isImplementPrompt(text)) return false
  return mode === 'plan' || /请只输出计划文档|改写上一份计划文档/.test(text)
}

function isImplementPrompt(text) {
  return /严格按照以下计划实施/.test(text)
}

function planMarkdown(text) {
  const revised = /改写上一份计划|需要改进/.test(text)
  const wantsSum = /1\s*\+\s*1|计算/.test(text)
  const title = wantsSum || /1\+1 计算演示/.test(text) ? '1+1 计算演示' : '任务计划'
  const summary = revised
    ? (wantsSum
      ? '计算两个整数 1 和 1 的和，并按补充说明增加验证。'
      : '根据补充说明修订后的实施计划。')
    : (wantsSum ? '计算两个整数 1 和 1 的和。' : '为当前任务给出可执行的分步计划。')
  const steps = [
    '1. 确认输入为整数 1 和 1',
    '2. 相加得到 2',
    '3. 向用户报告结果'
  ]
  if (revised) steps.push('4. 按补充说明增加验证或测试')
  return [`# ${title}`, '', '## Summary', summary, '', '## Steps', ...steps].join('\n')
}

async function finishPrompt(requestId, sessionId, runId, text) {
  notify('event/final', {
    method: 'event/final',
    session_id: sessionId,
    run_id: runId,
    text
  })
  notify('event/done', {
    method: 'event/done',
    session_id: sessionId,
    run_id: runId,
    status: 'succeeded'
  })
  ensureTask(sessionId, { status: 'succeeded' })
  respond(requestId, { run_id: runId, status: 'succeeded', text })
}

async function runPlanPrompt(requestId, sessionId, text) {
  const runId = `plan-${++sessionCounter}`
  ensureTask(sessionId, { title: text.slice(0, 80) || 'Plan', status: 'running' })
  const document = planMarkdown(text)
  notify('event/message_delta', {
    method: 'event/message_delta',
    session_id: sessionId,
    text: document
  })
  await sleep(180)
  await finishPrompt(requestId, sessionId, runId, document)
}

async function runImplementPrompt(requestId, sessionId, text) {
  const runId = `build-${++sessionCounter}`
  ensureTask(sessionId, { title: text.slice(0, 80) || 'Build', status: 'running' })
  notify('event/message_delta', {
    method: 'event/message_delta',
    session_id: sessionId,
    text: '开始按计划实施…'
  })
  await sleep(160)
  notify('event/tool_begin', {
    method: 'event/tool_begin',
    session_id: sessionId,
    call_id: 'build-1',
    tool_name: 'bash',
    arguments: { command: 'python -c "print(1+1)"' }
  })
  await sleep(220)
  notify('event/tool_end', {
    method: 'event/tool_end',
    session_id: sessionId,
    call_id: 'build-1',
    ok: true,
    summary: '2',
    status: 'succeeded'
  })
  const answer = '已按计划完成：1 + 1 = 2。'
  notify('event/message_delta', {
    method: 'event/message_delta',
    session_id: sessionId,
    text: answer
  })
  await sleep(120)
  await finishPrompt(requestId, sessionId, runId, answer)
}

async function runPrompt(requestId, sessionId, text, mode = 'build') {
  const runId = `demo-${++sessionCounter}`
  ensureTask(sessionId, { title: text.slice(0, 80) || 'New task', status: 'running' })
  if (text.includes('startup demo')) {
    notify('event/progress', { session_id: sessionId, text: 'Starting Agent…' })
    await sleep(260)
  }
  notify('event/job_status', {
    session_id: sessionId,
    job_id: `job-${runId}`,
    state: 'submitted'
  })
  notify('event/job_status', {
    session_id: sessionId,
    job_id: `job-${runId}`,
    state: 'running'
  })

  if (text.includes('timeout demo')) {
    // Simulate the production watchdog response. There is deliberately no
    // final event: the renderer must reconnect and represent this as an
    // intermediate recovery, not a terminal task error.
    await sleep(80)
    respondError(requestId, -32004, 'appserver degraded: job stalled >120.0s (session ' + sessionId + ')')
    return
  }

  if (isImplementPrompt(text)) {
    await runImplementPrompt(requestId, sessionId, text)
    return
  }

  if (isPlanPrompt(text, mode)) {
    await runPlanPrompt(requestId, sessionId, text)
    return
  }

  if (text.includes('fail demo')) {
    await sleep(300)
    notify('event/message_delta', {
      method: 'event/message_delta',
      session_id: sessionId,
      text: '执行中…'
    })
    await sleep(400)
    notify('event/error', {
      method: 'event/error',
      session_id: sessionId,
      message: 'demo failure',
      run_id: runId,
      status: 'failed'
    })
    notify('event/done', {
      method: 'event/done',
      session_id: sessionId,
      run_id: runId,
      status: 'failed'
    })
    ensureTask(sessionId, { status: 'failed' })
    respondError(requestId, -32000, 'demo failure')
    return
  }

  if (text.includes('approval demo') || text.includes('approval reject') || text.includes('approval auto')) {
    await runApprovalPrompt(requestId, sessionId, text)
    return
  }

  if (text.includes('slow demo')) {
    // Register before the first streamed event: the UI may let a user press
    // Stop as soon as the running tool card appears.
    pendingPrompts.set(requestId, { sessionId, runId })
    notify('event/message_delta', {
      method: 'event/message_delta',
      session_id: sessionId,
      text: '正在分析需求…'
    })
    await sleep(500)
    notify('event/tool_begin', {
      method: 'event/tool_begin',
      session_id: sessionId,
      call_id: 'slow-1',
      tool_name: 'bash',
      arguments: { command: 'analyze --slow' }
    })
    await sleep(500)
    notify('event/message_delta', {
      method: 'event/message_delta',
      session_id: sessionId,
      text: '正在深入分析…'
    })
    return
  }

  if (text.includes('[DTS-')) {
    await runStressPrompt(requestId, sessionId, text)
    return
  }

  notify('event/message_delta', {
    method: 'event/message_delta',
    session_id: sessionId,
    text: '开始处理…'
  })
  await sleep(400)
  notify('event/tool_begin', {
    method: 'event/tool_begin',
    session_id: sessionId,
    call_id: 'demo-bash',
    tool_name: 'bash',
    arguments: { command: 'ls' }
  })
  await sleep(500)
  notify('event/tool_end', {
    method: 'event/tool_end',
    session_id: sessionId,
    call_id: 'demo-bash',
    ok: true,
    summary: '3 files listed',
    status: 'succeeded'
  })
  notify('event/tool_begin', {
    method: 'event/tool_begin',
    session_id: sessionId,
    call_id: 'demo-read',
    tool_name: 'read_file',
    arguments: { path: 'README.md' }
  })
  await sleep(400)
  notify('event/tool_end', {
    method: 'event/tool_end',
    session_id: sessionId,
    call_id: 'demo-read',
    ok: true,
    summary: '886 bytes',
    status: 'succeeded'
  })
  notify('event/message_delta', {
    method: 'event/message_delta',
    session_id: sessionId,
    text: '已完成：demo 输出。'
  })
  await sleep(300)
  notify('event/final', {
    method: 'event/final',
    session_id: sessionId,
    run_id: runId,
    text: 'demo 输出完成。'
  })
  notify('event/done', {
    method: 'event/done',
    session_id: sessionId,
    run_id: runId,
    status: 'succeeded'
  })
  respond(requestId, { run_id: runId, status: 'succeeded', text: 'demo 输出完成。' })
}

function handleInterrupt(requestId, sessionId) {
  for (const [promptId, entry] of pendingPrompts) {
    if (entry.sessionId === sessionId) {
      pendingPrompts.delete(promptId)
      for (const child of childSessionsByRoot.get(sessionId)?.values() ?? []) {
        if (!['completed', 'failed', 'cancelled', 'timed_out', 'denied'].includes(child.status)) {
          notifyChild('child_session/cancelled', sessionId, child.parent_session_id, child.session_id, {
            agent_id: child.agent_id,
            status: 'cancelled'
          })
        }
      }
      respond(requestId, { cancelled: true, session_id: sessionId })
      notify('event/done', {
        method: 'event/done',
        session_id: sessionId,
        run_id: entry.runId,
        status: 'cancelled'
      })
      respond(promptId, { run_id: entry.runId, status: 'cancelled', text: 'partial' })
      return
    }
  }
  respond(requestId, { cancelled: false, session_id: sessionId })
}

rl.on('line', (line) => {
  let message
  try {
    message = JSON.parse(line)
  } catch {
    return
  }
  const id = message.id
  const method = String(message.method ?? '')
  const params = message.params ?? {}

  const isServerResponse =
    id !== undefined &&
    (Object.prototype.hasOwnProperty.call(message, 'result') ||
      Object.prototype.hasOwnProperty.call(message, 'error'))
  if (isServerResponse) {
    const entry = pendingServerRequests.get(id)
    if (entry !== undefined) {
      pendingServerRequests.delete(id)
      if (Object.prototype.hasOwnProperty.call(message, 'error')) {
        entry.reject(new Error(String(message.error?.message ?? 'server request error')))
      } else {
        entry.resolve(message.result)
      }
    }
    return
  }

  if (method === 'initialize') {
    respond(id, {
      protocol_version: '1.1.0',
      server_name: 'rxycode-appserver',
      capabilities: { sessions: true, approval: true, subagents: true }
    })
    return
  }
  if (method === 'initialized' || (method !== '' && id === undefined)) {
    return
  }
  if (method === 'approval/mode_set') {
    respond(id, { ok: true, preset: String(params.preset ?? 'ask') })
    return
  }
  if (method === 'thread/list_deleted') {
    const items = [...sessionRecords.values()].filter((task) => task.trashed_at)
    respond(id, { threads: items })
    return
  }
  if (method === 'thread/restore') {
    const task = ensureTask(String(params.thread_id ?? params.session_id ?? ''), { trashed_at: null })
    respond(id, task)
    return
  }
  if (method === 'thread/purge') {
    if (params.confirm_purge !== true) {
      respondError(id, -32602, 'confirm_purge required')
      return
    }
    const sessionId = String(params.thread_id ?? params.session_id ?? '')
    sessionRecords.delete(sessionId)
    sessionEvents.delete(sessionId)
    respond(id, { thread_id: sessionId, purged: true })
    return
  }
  if (method === 'session/new') {
    sessionCounter += 1
    const sessionId = `demo-${sessionCounter}`
    const requestedModel = typeof (params.model ?? params.model_id) === 'string' && (params.model ?? params.model_id) !== ''
      ? (params.model ?? params.model_id)
      : activeModel
    const task = ensureTask(sessionId, {
      workspace_root: String(params.workspace_root ?? process.cwd()),
      model_id: requestedModel,
      provider_id: String(params.provider_id ?? requestedModel.split('/')[0] ?? '')
    })
    respond(id, { session_id: sessionId, workspace_root: task.workspace_root, model_id: task.model_id, provider_id: task.provider_id })
    notify('event/progress', { session_id: sessionId, text: 'Preparing Agent worker…' })
    return
  }
  if (method === 'sessions/list') {
    respond(id, { sessions: taskList(params.include_trashed !== false) })
    return
  }
  if (method === 'session/events') {
    const sessionId = String(params.session_id ?? '')
    const cursor = Number(params.cursor ?? 0)
    const events = (sessionEvents.get(sessionId) ?? []).filter((event) => event.seq > cursor)
    respond(id, { events, next_cursor: sessionEventSequence, gap_detected: false })
    return
  }
  if (method === 'session/rename') {
    const task = ensureTask(String(params.session_id ?? ''), { title: String(params.title ?? '').trim() || 'New task' })
    respond(id, task)
    return
  }
  if (method === 'session/trash') {
    const task = ensureTask(String(params.session_id ?? ''), { trashed_at: new Date().toISOString() })
    respond(id, task)
    return
  }
  if (method === 'session/restore') {
    const task = ensureTask(String(params.session_id ?? ''), { trashed_at: null })
    respond(id, task)
    return
  }
  if (method === 'session/purge') {
    const sessionId = String(params.session_id ?? '')
    const task = sessionRecords.get(sessionId)
    if (task === undefined || task.trashed_at === null) respondError(id, -32040, 'task must be trashed before purge')
    else {
      sessionRecords.delete(sessionId)
      sessionEvents.delete(sessionId)
      respond(id, { session_id: sessionId, purged: true })
    }
    return
  }
  if (method === 'session/set_model') {
    const sessionId = String(params.session_id ?? '')
    const modelId = String(params.model_id ?? '')
    const model = FAKE_MODELS.find((entry) => entry.id === modelId)
    if (model === undefined) respondError(id, -32602, `unknown model: ${modelId}`)
    else {
      const task = ensureTask(sessionId, { model_id: model.id, provider_id: model.provider_id })
      respond(id, { ok: true, session_id: sessionId, model_id: task.model_id, provider_id: task.provider_id })
    }
    return
  }
  if (method === 'models/list') {
    respond(id, { models: FAKE_MODELS.map((model) => ({ ...model, active: model.id === activeModel })), active: activeModel, recent: [activeModel] })
    return
  }
  if (method === 'models/set_active') {
    const modelId = String(params.id ?? '')
    if (!FAKE_MODELS.some((model) => model.id === modelId)) respondError(id, -32602, `unknown model: ${modelId}`)
    else {
      activeModel = modelId
      respond(id, { ok: true, id: activeModel })
    }
    return
  }
  if (method === 'models/presets') {
    respond(id, { presets: [
      { id: 'deepseek', name: 'DeepSeek', base_url: 'https://api.deepseek.com', category: 'DeepSeek' },
      { id: 'glm', name: 'GLM', base_url: 'https://open.bigmodel.cn/api/paas/v4', category: 'GLM' },
      { id: 'custom', name: 'Custom provider', base_url: '', category: 'Others' }
    ] })
    return
  }
  if (method === 'models/discover') {
    respond(id, { ok: true, models: [{ id: 'discovered-model-a' }, { id: 'discovered-model-b' }], base_url: String(params.base_url ?? '') })
    return
  }
  if (method === 'session/prompt') {
    const sessionId = String(params.session_id ?? '')
    const text = String(params.text ?? '')
    const mode = String(params.mode ?? 'build')
    void runPrompt(id, sessionId, text, mode).catch((error) => {
      respondError(id, -32000, String(error))
      notify('event/done', {
        method: 'event/done',
        session_id: sessionId,
        run_id: 'demo-error',
        status: 'failed'
      })
    })
    return
  }
  if (method === 'session/interrupt') {
    handleInterrupt(id, String(params.session_id ?? ''))
    return
  }
  if (method === 'agent/invoke' || method === 'task/start') {
    const rootSessionId = String(params.parent_session_id ?? params.root_session_id ?? '')
    const agentId = String(params.agent_id ?? '')
    const prompt = String(params.prompt ?? '')
    const requestId = String(params.request_id ?? `request-${Date.now()}`)
    respond(id, { accepted: true, request_id: requestId })
    void runMentionChild(rootSessionId, agentId, prompt, requestId)
    return
  }
  if (method === 'subagents/capability') {
    respond(id, { protocol_version: 1, subagents_enabled: true, task: true, mention: true, child_tasks: true, active_lease_count: 0 })
    return
  }
  if (method === 'subagents/list') {
    respond(id, { agents: [
      { id: 'explore', description: 'Read-only repository explorer', mode: 'subagent', model: null },
      { id: 'reviewer', description: 'Read-only code reviewer', mode: 'subagent', model: null }
    ] })
    return
  }
  if (method === 'child_sessions/events') {
    const root = String(params.root_session_id ?? '')
    const cursor = Number(params.cursor ?? 0)
    const events = (childEventsByRoot.get(root) ?? []).filter((event) => event.seq > cursor)
    respond(id, { events, next_cursor: childEventSequence, gap_detected: false })
    return
  }
  if (method === 'child_sessions/list') {
    const root = String(params.root_session_id ?? '')
    respond(id, { root_session_id: root, sessions: [...(childSessionsByRoot.get(root)?.values() ?? [])] })
    return
  }
  if (method === 'child_sessions/cancel') {
    const root = String(params.root_session_id ?? '')
    for (const session of childSessionsByRoot.get(root)?.values() ?? []) {
      if (!['completed', 'failed', 'cancelled', 'timed_out', 'denied'].includes(session.status)) {
        notifyChild('child_session/cancelled', root, session.parent_session_id, session.session_id, { agent_id: session.agent_id, status: 'cancelled' })
      }
    }
    respond(id, { cancelled: true, root_session_id: root })
    return
  }
  if (method === 'child_sessions/retry') {
    respond(id, { accepted: true, request_id: String(params.request_id ?? `retry-${Date.now()}`) })
    return
  }
  if (method === 'shutdown') {
    respond(id, { ok: true })
    process.exit(0)
    return
  }
  respondError(id, -32601, `method not found: ${method}`)
})
