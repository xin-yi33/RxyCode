import { test } from 'node:test'
import assert from 'node:assert/strict'
import {
  addSession,
  addApprovalRequest,
  addUserMessage,
  isPlaceholderTitle,
  titleFromFirstPrompt,
  applyError,
  applyTransportRecovery,
  applyFinalAnswer,
  applyMessageDelta,
  applyProtocolNotification,
  applyPromptResult,
  applyRunComplete,
  applyToolBegin,
  applyToolEnd,
  beginAssistantMessage,
  beginMentionDispatch,
  createInitialState,
  hydrateChildSessions,
  hydrateSessions,
  releaseStaleRun,
  removeApprovalRequest,
  removeApprovalRequestsForSession,
  selectSession,
  clearActiveSession,
  setRunning,
  timelineFor,
  parseLeadingAgentMentions,
  replaySessionEvents,
  purgeSession,
  renameSession,
  restoreSession,
  updateApprovalRequestStatus,
  setSessionModel,
  trashSession,
  pinSession,
  type ConversationState
} from './conversationStore.mts'
import type { ApprovalRequest, RunComplete, ToolBegin, ToolEnd } from '@rxycode/protocol-client'

const WORKSPACE = 'D:\\workspace'

test('parseLeadingAgentMentions extracts one or more leading mentions', () => {
  assert.deepEqual(parseLeadingAgentMentions('@explore inspect auth'), {
    agentIds: ['explore'],
    prompt: 'inspect auth'
  })
  assert.deepEqual(parseLeadingAgentMentions('@explore @scout investigate incident'), {
    agentIds: ['explore', 'scout'],
    prompt: 'investigate incident'
  })
  assert.equal(parseLeadingAgentMentions('please ask @explore') , null)
  assert.equal(parseLeadingAgentMentions('@Explore inspect auth'), null)
})

function baseState(): ConversationState {
  return addSession(createInitialState(), {
    sessionId: 's1',
    workspaceRoot: WORKSPACE
  })
}

test('addSession adds a session and activates the first one', () => {
  const state = addSession(createInitialState(), {
    sessionId: 's1',
    workspaceRoot: WORKSPACE
  })
  assert.equal(state.sessions.length, 1)
  assert.equal(state.sessions[0]?.sessionId, 's1')
  assert.equal(state.activeSessionId, 's1')
  assert.equal(state.messagesBySession['s1']?.length, 0)
})

test('clearActiveSession leaves a draft with no open chat', () => {
  const state = addSession(createInitialState(), {
    sessionId: 's1',
    workspaceRoot: WORKSPACE
  })
  assert.equal(clearActiveSession(state).activeSessionId, null)
})

test('addSession activates a newly created session', () => {
  const first = addSession(createInitialState(), {
    sessionId: 's1',
    workspaceRoot: WORKSPACE
  })
  const state = addSession(first, {
    sessionId: 's2',
    workspaceRoot: WORKSPACE
  })
  assert.equal(state.activeSessionId, 's2')
})

test('addSession uses a Chinese default title prefixed with 会话', () => {
  const state = addSession(createInitialState(), {
    sessionId: 'abc12345',
    workspaceRoot: WORKSPACE
  })
  assert.equal(state.sessions[0]?.title, '会话 abc12345')
})

test('addSession ignores duplicate session ids', () => {
  const once = addSession(createInitialState(), {
    sessionId: 's1',
    workspaceRoot: WORKSPACE
  })
  const twice = addSession(once, {
    sessionId: 's1',
    workspaceRoot: WORKSPACE
  })
  assert.equal(twice.sessions.length, 1)
})

test('selectSession switches the active session', () => {
  const withTwo = addSession(baseState(), {
    sessionId: 's2',
    workspaceRoot: WORKSPACE
  })
  const selected = selectSession(withTwo, 's2')
  assert.equal(selected.activeSessionId, 's2')
})

test('selectSession ignores unknown ids', () => {
  const state = baseState()
  assert.equal(selectSession(state, 'nope'), state)
})

test('addUserMessage appends a user message and titles the session from the first prompt', () => {
  const state = addUserMessage(baseState(), 's1', '帮我写一个 hello world')
  assert.equal(state.messagesBySession['s1']?.length, 1)
  assert.equal(state.messagesBySession['s1']?.[0]?.role, 'user')
  assert.equal(state.messagesBySession['s1']?.[0]?.text, '帮我写一个 hello world')
  assert.equal(state.sessions[0]?.title, '帮我写一个 hello world')
})

test('addUserMessage titles a 新任务 session from the first sentence', () => {
  const created = addSession(createInitialState(), {
    sessionId: 's1',
    workspaceRoot: WORKSPACE,
    title: '新任务'
  })
  const state = addUserMessage(created, 's1', '没什么，只是打个招呼。后面还有一句')
  assert.equal(state.sessions[0]?.title, '没什么，只是打个招呼')
  assert.equal(isPlaceholderTitle('新任务'), true)
  assert.equal(titleFromFirstPrompt('hello world! more'), 'hello world')
})

test('addUserMessage keeps a custom session title unchanged', () => {
  const custom = addSession(createInitialState(), {
    sessionId: 's1',
    workspaceRoot: WORKSPACE,
    title: '我的任务'
  })
  const state = addUserMessage(custom, 's1', '第一条消息')
  assert.equal(state.sessions[0]?.title, '我的任务')
})

test('addUserMessage clears a previous session error', () => {
  const errored = applyError(baseState(), 's1', 'boom')
  assert.equal(errored.errorBySession['s1'], 'boom')
  const state = addUserMessage(errored, 's1', '再试一次')
  assert.equal(state.errorBySession['s1'], null)
})

test('beginAssistantMessage marks the session running and opens a streaming placeholder', () => {
  const state = beginAssistantMessage(baseState(), 's1')
  assert.equal(state.runningBySession['s1'], true)
  const last = state.messagesBySession['s1']?.at(-1)
  assert.equal(last?.role, 'assistant')
  assert.equal(last?.status, 'streaming')
  assert.equal(last?.text, '')
})

test('beginAssistantMessage clears a previous session error', () => {
  const errored = applyError(baseState(), 's1', 'boom')
  const state = beginAssistantMessage(errored, 's1')
  assert.equal(state.errorBySession['s1'], null)
})

test('applyMessageDelta accumulates text into the latest assistant message', () => {
  let state = beginAssistantMessage(baseState(), 's1')
  state = applyMessageDelta(state, 's1', {
    method: 'event/message_delta',
    session_id: 's1',
    text: '你好'
  })
  state = applyMessageDelta(state, 's1', {
    method: 'event/message_delta',
    session_id: 's1',
    text: '，世界'
  })
  const last = state.messagesBySession['s1']?.at(-1)
  assert.equal(last?.text, '你好，世界')
})

test('applyMessageDelta opens a streaming message when none exists', () => {
  const state = applyMessageDelta(baseState(), 's1', {
    method: 'event/message_delta',
    session_id: 's1',
    text: 'hi'
  })
  const last = state.messagesBySession['s1']?.at(-1)
  assert.equal(last?.role, 'assistant')
  assert.equal(last?.text, 'hi')
})

test('applyFinalAnswer replaces the placeholder with the final answer', () => {
  let state = beginAssistantMessage(baseState(), 's1')
  state = applyMessageDelta(state, 's1', {
    method: 'event/message_delta',
    session_id: 's1',
    text: '你好'
  })
  state = applyFinalAnswer(state, 's1', {
    method: 'event/final',
    session_id: 's1',
    run_id: 'run-1',
    text: '完整回答'
  })
  const last = state.messagesBySession['s1']?.at(-1)
  assert.equal(last?.text, '完整回答')
  assert.equal(last?.status, 'complete')
  assert.equal(last?.runId, 'run-1')
  assert.equal(state.runningBySession['s1'], false)
})

test('applyFinalAnswer creates a complete assistant message when none is streaming', () => {
  const state = applyFinalAnswer(baseState(), 's1', {
    method: 'event/final',
    session_id: 's1',
    run_id: 'run-2',
    text: '直接回答'
  })
  const last = state.messagesBySession['s1']?.at(-1)
  assert.equal(last?.text, '直接回答')
  assert.equal(last?.status, 'complete')
  assert.equal(state.runningBySession['s1'], false)
})

test('applyFinalAnswer clears a previous session error', () => {
  const errored = applyError(baseState(), 's1', 'boom')
  const state = applyFinalAnswer(errored, 's1', {
    method: 'event/final',
    session_id: 's1',
    run_id: 'run-3',
    text: '成功回答'
  })
  assert.equal(state.errorBySession['s1'], null)
})

test('applyFinalAnswer finalizes tool cards that never received a tool_end event', () => {
  let state = applyToolBegin(baseState(), 's1', toolBegin('call-1', 'glob'))
  state = applyToolBegin(state, 's1', toolBegin('call-2', 'grep'))
  state = applyFinalAnswer(state, 's1', {
    method: 'event/final',
    session_id: 's1',
    run_id: 'run-final-tools',
    text: 'done'
  })

  assert.deepEqual(
    state.toolsBySession['s1']?.map((tool) => ({ status: tool.status, summary: tool.summary })),
    [
      { status: 'ok', summary: 'completed with final answer' },
      { status: 'ok', summary: 'completed with final answer' }
    ]
  )
  assert.deepEqual(
    timelineFor(state, 's1')
      .filter((item) => item.kind === 'tool_activity')
      .map((item) => ({ status: item.status, summary: item.summary })),
    [
      { status: 'ok', summary: 'completed with final answer' },
      { status: 'ok', summary: 'completed with final answer' }
    ]
  )
  assert.equal(
    timelineFor(state, 's1').some((item) => item.kind === 'tool_activity' && item.status === 'running'),
    false
  )
})

test('applyPromptResult records the final answer when no final event arrived', () => {
  let state = beginAssistantMessage(baseState(), 's1')
  state = applyPromptResult(state, 's1', {
    runId: 'run-9',
    status: 'succeeded',
    text: 'fallback answer'
  })
  const last = state.messagesBySession['s1']?.at(-1)
  assert.equal(last?.text, 'fallback answer')
  assert.equal(last?.status, 'complete')
  assert.equal(state.runningBySession['s1'], false)
})

test('applyPromptResult finalizes running tools as errors when the prompt failed without event/done', () => {
  let state = applyToolBegin(baseState(), 's1', toolBegin('call-1'))
  state = beginAssistantMessage(state, 's1')
  state = applyPromptResult(state, 's1', {
    runId: 'run-failed',
    status: 'failed',
    text: 'backend evidence failure'
  })
  const last = state.messagesBySession['s1']?.at(-1)
  const tool = state.toolsBySession['s1']?.[0]
  assert.equal(last?.text, 'backend evidence failure')
  assert.equal(last?.status, 'error')
  assert.equal(tool?.status, 'error')
  assert.equal(tool?.summary, 'run failed')
  assert.equal(state.runningBySession['s1'], false)
  assert.equal(state.errorBySession['s1'], 'run failed')
})

test('failed prompt with empty text does not render a blank Final Answer heading', () => {
  let state = beginAssistantMessage(baseState(), 's1')
  state = applyPromptResult(state, 's1', {
    runId: 'run-empty-failed',
    status: 'failed',
    text: ''
  })
  assert.equal(state.timelineBySession['s1']?.some((item) => item.kind === 'final_answer'), false)
  assert.equal(state.timelineBySession['s1']?.at(-1)?.kind, 'error')
  assert.equal(state.errorBySession['s1'], 'run failed')
})

test('applyPromptResult clears a previous session error', () => {
  const errored = applyError(baseState(), 's1', 'boom')
  const state = applyPromptResult(errored, 's1', {
    runId: 'run-10',
    status: 'succeeded',
    text: '成功回答'
  })
  assert.equal(state.errorBySession['s1'], null)
})

test('applyError marks the latest assistant message as errored and stops running', () => {
  let state = beginAssistantMessage(baseState(), 's1')
  state = applyError(state, 's1', 'boom')
  const last = state.messagesBySession['s1']?.at(-1)
  assert.equal(last?.status, 'error')
  assert.equal(last?.text, 'boom')
  assert.equal(state.runningBySession['s1'], false)
  assert.equal(state.errorBySession['s1'], 'boom')
})

test('prompt RPC reconciliation does not duplicate an already streamed final event', () => {
  let state = beginAssistantMessage(baseState(), 's1')
  state = applyFinalAnswer(state, 's1', {
    method: 'event/final',
    session_id: 's1',
    run_id: 'run-reconciled',
    text: 'streamed final'
  })
  state = applyPromptResult(state, 's1', {
    runId: 'run-reconciled',
    status: 'succeeded',
    text: 'streamed final'
  })
  assert.equal(timelineFor(state, 's1').filter((item) => item.kind === 'final_answer').length, 1)
  assert.equal(state.messagesBySession['s1']?.filter((message) => message.text === 'streamed final').length, 1)
})

test('task metadata supports model selection and reversible deletion', () => {
  let state = addSession(createInitialState(), {
    sessionId: 's1',
    workspaceRoot: WORKSPACE,
    modelId: 'deepseek/deepseek-v4',
    providerId: 'deepseek'
  })
  state = renameSession(state, 's1', 'Payment audit')
  state = setSessionModel(state, 's1', 'glm/glm-5', 'glm')
  assert.equal(state.sessions[0]?.title, 'Payment audit')
  assert.equal(state.sessions[0]?.modelId, 'glm/glm-5')
  assert.equal(state.sessions[0]?.providerId, 'glm')
  state = trashSession(state, 's1')
  assert.equal(state.sessions[0]?.trashedAt !== null, true)
  assert.equal(state.activeSessionId, null)
  state = restoreSession(state, 's1')
  assert.equal(state.sessions[0]?.trashedAt, null)
  state = purgeSession(state, 's1')
  assert.equal(state.sessions.length, 0)
})

test('pinSession toggles pinned without deleting the task', () => {
  let state = addSession(createInitialState(), {
    sessionId: 's1',
    workspaceRoot: WORKSPACE
  })
  assert.equal(state.sessions[0]?.pinned, false)
  state = pinSession(state, 's1', true)
  assert.equal(state.sessions[0]?.pinned, true)
  state = pinSession(state, 's1', false)
  assert.equal(state.sessions[0]?.pinned, false)
  assert.equal(state.sessions.length, 1)
})

test('hydrated task status restores active and terminal state without re-running the task', () => {
  const state = hydrateSessions(createInitialState(), [{
    session_id: 'persisted',
    workspace_root: WORKSPACE,
    title: 'Persisted task',
    status: 'approval',
    created_at: '2026-08-11T00:00:00Z',
    updated_at: '2026-08-11T00:01:00Z'
  }])
  assert.equal(state.runStateBySession.persisted, 'approval')
  assert.equal(state.runningBySession.persisted, true)
})

test('hydrated running status is stale after desktop restart and must not lock the composer', () => {
  const state = hydrateSessions(createInitialState(), [{
    session_id: 'stuck',
    workspace_root: WORKSPACE,
    title: 'New task',
    status: 'running',
    created_at: '2026-08-13T00:00:00Z',
    updated_at: '2026-08-13T00:01:00Z'
  }])
  assert.equal(state.runStateBySession.stuck, 'queued')
  assert.equal(state.runningBySession.stuck, false)
})

test('releaseStaleRun unlocks a replayed preparing worker and drops leftover progress', () => {
  let state = addSession(createInitialState(), { sessionId: 's1', workspaceRoot: WORKSPACE })
  state = applyProtocolNotification(state, 'event/progress', {
    session_id: 's1',
    text: 'Preparing Agent worker…'
  })
  state = applyProtocolNotification(state, 'event/task_started', { session_id: 's1' })
  assert.equal(state.runningBySession.s1, true)
  state = releaseStaleRun(state, 's1')
  assert.equal(state.runningBySession.s1, false)
  assert.equal(state.runStateBySession.s1, 'queued')
  assert.equal(state.progressBySession.s1, undefined)
})

test('applyError finalizes every running tool when the prompt transport fails', () => {
  let state = applyToolBegin(baseState(), 's1', toolBegin('call-1'))
  state = beginAssistantMessage(state, 's1')
  state = applyError(state, 's1', 'RPC timeout: session/prompt')
  const tool = state.toolsBySession['s1']?.[0]
  assert.equal(tool?.status, 'error')
  assert.equal(tool?.summary, 'RPC timeout: session/prompt')
  assert.equal(state.runningBySession['s1'], false)
})

test('applyTransportRecovery shows a recoverable row without finalizing the task as failed', () => {
  let state = beginAssistantMessage(baseState(), 's1')
  state = applyTransportRecovery(state, 's1', 'appserver degraded')
  const recovery = state.timelineBySession.s1?.find((item) => item.kind === 'recovery')
  assert.equal(recovery?.kind, 'recovery')
  assert.equal(recovery?.state, 'recovered')
  assert.equal(state.runningBySession.s1, false)
  assert.equal(state.runStateBySession.s1, 'queued')
  assert.equal(state.errorBySession.s1, null)
  assert.equal(state.timelineBySession.s1?.some((item) => item.kind === 'error'), false)
})

test('transport recovery after a prior final answer creates a new recovery row', () => {
  let state = addUserMessage(baseState(), 's1', 'first prompt')
  state = applyPromptResult(state, 's1', { runId: 'run-1', status: 'succeeded', text: 'first answer' })
  state = addUserMessage(state, 's1', 'second prompt')
  state = beginAssistantMessage(state, 's1')
  const recovered = applyTransportRecovery(state, 's1', 'connection lost')
  assert.equal(recovered.timelineBySession.s1?.at(-1)?.kind, 'recovery')
  assert.equal(recovered.timelineBySession.s1?.some((item) => item.kind === 'final_answer' && item.runId === 'run-1'), true)
  assert.equal(recovered.errorBySession.s1, null)
})

test('applyError does not append a duplicate message when the last one already errored', () => {
  let state = beginAssistantMessage(baseState(), 's1')
  state = applyError(state, 's1', 'demo failure')
  const once = state.messagesBySession['s1']
  state = applyError(state, 's1', 'demo failure')
  assert.equal(state.messagesBySession['s1']?.length, once?.length)
  assert.equal(state.messagesBySession['s1']?.at(-1)?.status, 'error')
  assert.equal(state.errorBySession['s1'], 'demo failure')
})

test('messages are kept per session', () => {
  const two = addSession(baseState(), {
    sessionId: 's2',
    workspaceRoot: WORKSPACE
  })
  const state = addUserMessage(two, 's2', 'second session')
  assert.equal(state.messagesBySession['s1']?.length, 0)
  assert.equal(state.messagesBySession['s2']?.length, 1)
})

test('setRunning flips the running flag', () => {
  const state = setRunning(baseState(), 's1', true)
  assert.equal(state.runningBySession['s1'], true)
  const stopped = setRunning(state, 's1', false)
  assert.equal(stopped.runningBySession['s1'], false)
})

function toolBegin(callId: string, toolName = 'read_file'): ToolBegin {
  return {
    method: 'event/tool_begin',
    session_id: 's1',
    call_id: callId,
    tool_name: toolName
  }
}

function toolEnd(callId: string, ok: boolean, summary: string): ToolEnd {
  return {
    method: 'event/tool_end',
    session_id: 's1',
    call_id: callId,
    ok,
    summary
  }
}

function runDone(status: 'succeeded' | 'failed' | 'cancelled' | 'timed_out'): RunComplete {
  return {
    method: 'event/done',
    session_id: 's1',
    run_id: 'run-7',
    status
  }
}

test('applyToolBegin appends a running tool card to the session', () => {
  const state = applyToolBegin(baseState(), 's1', {
    ...toolBegin('call-1'),
    arguments: { path: 'D:\\a.txt' }
  })
  const tools = state.toolsBySession['s1']
  assert.equal(tools?.length, 1)
  assert.equal(tools?.[0]?.callId, 'call-1')
  assert.equal(tools?.[0]?.toolName, 'read_file')
  assert.equal(tools?.[0]?.status, 'running')
  assert.deepEqual(tools?.[0]?.arguments, { path: 'D:\\a.txt' })
})

test('applyToolEnd marks the matching tool card ok with its summary', () => {
  let state = applyToolBegin(baseState(), 's1', toolBegin('call-1'))
  state = applyToolEnd(state, 's1', toolEnd('call-1', true, '2 lines'))
  const tool = state.toolsBySession['s1']?.[0]
  assert.equal(tool?.status, 'ok')
  assert.equal(tool?.summary, '2 lines')
})

test('applyToolEnd marks the matching tool card error when the call failed', () => {
  let state = applyToolBegin(baseState(), 's1', toolBegin('call-1'))
  state = applyToolEnd(state, 's1', toolEnd('call-1', false, 'boom'))
  const tool = state.toolsBySession['s1']?.[0]
  assert.equal(tool?.status, 'error')
  assert.equal(tool?.summary, 'boom')
})

test('applyToolEnd ignores unknown call ids without changing state', () => {
  const state = applyToolBegin(baseState(), 's1', toolBegin('call-1'))
  const next = applyToolEnd(state, 's1', toolEnd('call-nope', true, 'x'))
  assert.equal(next, state)
})

test('applyToolBegin replaces an existing card with the same call id', () => {
  let state = applyToolBegin(baseState(), 's1', toolBegin('call-1', 'read_file'))
  state = applyToolBegin(baseState(), 's1', {
    ...toolBegin('call-1', 'write_file'),
    arguments: { path: 'D:\\b.txt' }
  })
  const tools = state.toolsBySession['s1']
  assert.equal(tools?.length, 1)
  assert.equal(tools?.[0]?.toolName, 'write_file')
  assert.deepEqual(tools?.[0]?.arguments, { path: 'D:\\b.txt' })
})

test('applyRunComplete stops the session and keeps partial streaming text on cancel', () => {
  let state = beginAssistantMessage(baseState(), 's1')
  state = applyMessageDelta(state, 's1', {
    method: 'event/message_delta',
    session_id: 's1',
    text: 'partial'
  })
  state = applyRunComplete(state, 's1', runDone('cancelled'))
  assert.equal(state.runningBySession['s1'], false)
  const last = state.messagesBySession['s1']?.at(-1)
  assert.equal(last?.text, 'partial')
  assert.equal(last?.status, 'error')
  assert.equal(last?.runId, 'run-7')
})

test('applyRunComplete marks a failed run as an error', () => {
  let state = beginAssistantMessage(baseState(), 's1')
  state = applyMessageDelta(state, 's1', {
    method: 'event/message_delta',
    session_id: 's1',
    text: 'partial'
  })
  state = applyRunComplete(state, 's1', runDone('failed'))
  const last = state.messagesBySession['s1']?.at(-1)
  assert.equal(last?.status, 'error')
  assert.equal(state.errorBySession['s1'], 'run failed')
  assert.equal(state.runningBySession['s1'], false)
})

test('applyRunComplete clears a previous session error on success', () => {
  const errored = applyError(baseState(), 's1', 'boom')
  const state = applyRunComplete(errored, 's1', runDone('succeeded'))
  assert.equal(state.errorBySession['s1'], null)
  assert.equal(state.runningBySession['s1'], false)
})

test('applyRunComplete with no streaming message does not fabricate one', () => {
  const state = applyRunComplete(baseState(), 's1', runDone('succeeded'))
  assert.equal(state.messagesBySession['s1']?.length, 0)
  assert.equal(state.runningBySession['s1'], false)
})

test('applyRunComplete finalizes still-running tool cards as interrupted', () => {
  let state = applyToolBegin(baseState(), 's1', toolBegin('call-1'))
  state = applyRunComplete(state, 's1', runDone('cancelled'))
  const tool = state.toolsBySession['s1']?.[0]
  assert.equal(tool?.status, 'error')
  assert.equal(tool?.summary, 'interrupted')
})

test('applyProtocolNotification routes tool and done notifications into state', () => {
  let state = applyProtocolNotification(baseState(), 'event/tool_begin', toolBegin('call-1'))
  state = applyProtocolNotification(state, 'event/tool_end', toolEnd('call-1', true, 'ok'))
  state = applyProtocolNotification(state, 'event/done', runDone('cancelled'))
  const tool = state.toolsBySession['s1']?.[0]
  assert.equal(tool?.status, 'ok')
  assert.equal(state.runningBySession['s1'], false)
})

test('applyProtocolNotification maps event/team to a role progress line', () => {
  let state = addSession(createInitialState(), { sessionId: 's1', workspaceRoot: WORKSPACE })
  state = applyProtocolNotification(state, 'event/team', {
    session_id: 's1',
    role: 'architect',
    stage: 'plan',
    phase: 'stage_started',
    detail: 'design'
  })
  assert.equal(state.progressBySession.s1, '[architect] plan')
  assert.equal(state.teamEventsBySession.s1?.length, 1)
  assert.equal(state.teamEventsBySession.s1?.[0]?.phase, 'stage_started')
  assert.equal(state.teamEventsBySession.s1?.[0]?.detail, 'design')
})

test('applyProtocolNotification ignores unknown methods without changing state', () => {
  const state = baseState()
  assert.equal(applyProtocolNotification(state, 'event/unknown', { session_id: 's1' }), state)
})

test('replaySessionEvents rebuilds ordinary task timeline in persisted sequence order', () => {
  const state = replaySessionEvents(baseState(), 's1', [
    {
      seq: 1,
      method: 'event/tool_begin',
      params: { session_id: 's1', call_id: 'call-1', tool_name: 'rg', arguments: { query: 'TODO' } }
    },
    {
      seq: 2,
      method: 'event/tool_end',
      params: { session_id: 's1', call_id: 'call-1', tool_name: 'rg', ok: true, summary: '2 matches' }
    },
    {
      seq: 3,
      method: 'event/final',
      params: { session_id: 's1', run_id: 'run-1', text: '发现两个待处理项' }
    }
  ], 3, false)

  assert.deepEqual(timelineFor(state, 's1').map((item) => item.kind), [
    'tool_activity',
    'assistant_text',
    'final_answer'
  ])
  const tool = timelineFor(state, 's1')[0]
  assert.equal(tool?.kind, 'tool_activity')
  if (tool?.kind === 'tool_activity') assert.equal(tool.status, 'ok')
  assert.equal(timelineFor(state, 's1').at(-1)?.kind, 'final_answer')
  assert.equal(state.sessionEventCursorBySession['s1'], 3)
  assert.equal(state.sessionEventGapBySession['s1'], false)
})

test('replaySessionEvents records a cursor gap for the caller to repair from zero', () => {
  const state = replaySessionEvents(baseState(), 's1', [
    { seq: 4, method: 'event/final', params: { session_id: 's1', run_id: 'run-4', text: '完成' } }
  ], 4, true)

  assert.equal(state.sessionEventCursorBySession['s1'], 4)
  assert.equal(state.sessionEventGapBySession['s1'], true)
})

test('replayed final answer is idempotent when the live event arrived before reconnect', () => {
  const state = applyProtocolNotification(baseState(), 'event/final', {
    session_id: 's1',
    run_id: 'run-live',
    text: 'Release audit complete',
    input_tokens: null,
    output_tokens: null,
    cache_hit_tokens: null,
    reporting_status: 'not_reported'
  })
  const replayed = replaySessionEvents(state, 's1', [{
    seq: 1,
    method: 'event/final',
    params: {
      session_id: 's1',
      run_id: 'run-live',
      text: 'Release audit complete',
      input_tokens: null,
      output_tokens: null,
      cache_hit_tokens: null,
      reporting_status: 'not_reported'
    }
  }], 1, false)

  assert.equal(replayed.timelineBySession.s1?.filter((item) => item.kind === 'final_answer').length, 1)
})

test('cancelled run also finalizes the corresponding timeline tool activity', () => {
  let state = applyToolBegin(baseState(), 's1', toolBegin('cancelled-call'))
  state = applyRunComplete(state, 's1', {
    method: 'event/done', session_id: 's1', run_id: 'run-cancelled', status: 'cancelled'
  })
  const activity = timelineFor(state, 's1').find((item) => item.kind === 'tool_activity')
  assert.equal(activity?.kind, 'tool_activity')
  assert.equal(activity?.status, 'error')
  assert.equal(activity?.summary, 'interrupted')
})

test('timeline keeps prompts, tool results, recovery and final answer interleaved', () => {
  let state = addUserMessage(baseState(), 's1', 'audit the release build')
  state = beginAssistantMessage(state, 's1')
  state = applyMessageDelta(state, 's1', {
    method: 'event/message_delta',
    session_id: 's1',
    text: 'I will inspect the build. '
  })
  state = applyToolBegin(state, 's1', toolBegin('call-1', 'npm_test'))
  state = applyToolEnd(state, 's1', toolEnd('call-1', false, 'exit code 1'))
  state = applyProtocolNotification(state, 'event/recovery_started', {
    session_id: 's1', run_id: 'run-1', recovery_id: 'rec-1', event_id: 'e-1',
    seq: 1, timestamp: '2026-01-01T00:00:00Z', source_call_id: 'call-1',
    recovery_kind: 'model_recovery', error_kind: 'tool_error', max_attempts: 3
  })
  state = applyProtocolNotification(state, 'event/recovery_attempt', {
    session_id: 's1', run_id: 'run-1', recovery_id: 'rec-1', event_id: 'e-2',
    seq: 2, timestamp: '2026-01-01T00:00:01Z', attempt: 1,
    strategy: 'corrected_arguments', display_summary: 'corrected command'
  })
  state = applyToolBegin(state, 's1', toolBegin('call-2', 'npm_test'))
  state = applyToolEnd(state, 's1', toolEnd('call-2', true, '154 passed'))
  state = applyProtocolNotification(state, 'event/recovery_resolved', {
    session_id: 's1', run_id: 'run-1', recovery_id: 'rec-1', event_id: 'e-3',
    seq: 3, timestamp: '2026-01-01T00:00:02Z', attempts: 1,
    display_summary: 'recovered'
  })
  state = applyFinalAnswer(state, 's1', {
    method: 'event/final', session_id: 's1', run_id: 'run-1',
    text: 'Release audit passed'
  })

  assert.deepEqual(timelineFor(state, 's1').map((item) => item.kind), [
    'user_prompt', 'assistant_text', 'tool_activity', 'recovery',
    'tool_activity', 'assistant_text', 'final_answer'
  ])
  const tools = timelineFor(state, 's1').filter((item) => item.kind === 'tool_activity')
  assert.deepEqual(tools.map((item) => item.callId), ['call-1', 'call-2'])
  const recovery = timelineFor(state, 's1').find((item) => item.kind === 'recovery')
  assert.equal(recovery?.state, 'recovered')
  assert.equal(timelineFor(state, 's1').at(-1)?.kind, 'final_answer')
})

test('timeline keeps recovery failure intermediate until exhaustion', () => {
  let state = applyToolBegin(baseState(), 's1', toolBegin('call-1'))
  state = applyToolEnd(state, 's1', toolEnd('call-1', false, 'temporary failure'))
  state = applyProtocolNotification(state, 'event/recovery_started', {
    session_id: 's1', run_id: 'run-1', recovery_id: 'rec-2', event_id: 'e-1',
    seq: 1, timestamp: '2026-01-01T00:00:00Z', source_call_id: 'call-1',
    recovery_kind: 'model_recovery', error_kind: 'tool_error', max_attempts: 1
  })
  assert.equal(timelineFor(state, 's1').some((item) => item.kind === 'error'), false)
  state = applyProtocolNotification(state, 'event/recovery_exhausted', {
    session_id: 's1', run_id: 'run-1', recovery_id: 'rec-2', event_id: 'e-2',
    seq: 2, timestamp: '2026-01-01T00:00:01Z', attempts: 1,
    final_error: 'no recovery path'
  })
  state = applyError(state, 's1', 'no recovery path')
  assert.equal(timelineFor(state, 's1').at(-2)?.kind, 'recovery')
  assert.equal(timelineFor(state, 's1').at(-1)?.kind, 'error')
})

test('tool failure is visually held as recovering until recovery resolves', () => {
  let state = applyToolBegin(baseState(), 's1', toolBegin('recover-call', 'read_file'))
  state = applyToolEnd(state, 's1', toolEnd('recover-call', false, 'transient failure'))
  state = applyProtocolNotification(state, 'event/recovery_started', {
    session_id: 's1',
    run_id: 'run-recover',
    recovery_id: 'rec-1',
    source_call_id: 'recover-call',
    recovery_kind: 'model_recovery',
    error_kind: 'tool_error',
    max_attempts: 3,
    event_id: 'rec-event-1',
    seq: 1,
    timestamp: new Date().toISOString()
  })
  const tool = timelineFor(state, 's1').find((item) => item.kind === 'tool_activity')
  assert.equal(tool?.kind, 'tool_activity')
  assert.equal(tool?.status, 'recovering')
})

test('late recovery start cannot regress an exhausted recovery or errored tool', () => {
  let state = applyToolBegin(baseState(), 's1', toolBegin('late-call', 'websearch'))
  state = applyToolEnd(state, 's1', toolEnd('late-call', false, 'search timed out'))
  state = applyProtocolNotification(state, 'event/recovery_exhausted', {
    session_id: 's1',
    run_id: 'run-late',
    recovery_id: 'rec-late',
    event_id: 'late-exhausted',
    seq: 3,
    timestamp: '2026-01-01T00:00:03Z',
    attempts: 0,
    final_error: 'search timed out'
  })
  state = applyError(state, 's1', 'search timed out')
  state = applyProtocolNotification(state, 'event/recovery_started', {
    session_id: 's1',
    run_id: 'run-late',
    recovery_id: 'rec-late',
    event_id: 'late-started',
    seq: 1,
    timestamp: '2026-01-01T00:00:01Z',
    source_call_id: 'late-call',
    recovery_kind: 'model_recovery',
    error_kind: 'timeout',
    max_attempts: 3
  })

  const recovery = timelineFor(state, 's1').find((item) => item.kind === 'recovery')
  const tool = timelineFor(state, 's1').find((item) => item.kind === 'tool_activity')
  assert.equal(recovery?.state, 'exhausted')
  assert.equal(tool?.status, 'error')
})

test('token usage stays isolated per session and preserves unknown values', () => {
  let state = addSession(baseState(), {
    sessionId: 's2',
    workspaceRoot: WORKSPACE
  })
  state = applyProtocolNotification(state, 'event/token_usage', {
    session_id: 's1',
    input_tokens: 120,
    output_tokens: 24,
    cache_hit_tokens: 48
  })
  state = applyProtocolNotification(state, 'event/token_usage', {
    session_id: 's2',
    input_tokens: null,
    output_tokens: null,
    cache_hit_tokens: null
  })

  assert.deepEqual(state.usageBySession['s1'], {
    inputTokens: 120,
    outputTokens: 24,
    cacheHitTokens: 48,
    cacheWriteTokens: null,
    cacheHitRate: null,
    reportingStatus: 'not_reported'
  })
  assert.deepEqual(state.usageBySession['s2'], {
    inputTokens: null,
    outputTokens: null,
    cacheHitTokens: null,
    cacheWriteTokens: null,
    cacheHitRate: null,
    reportingStatus: 'not_reported'
  })
})

test('job status records an explainable terminal state without changing another session', () => {
  let state = addSession(baseState(), {
    sessionId: 's2',
    workspaceRoot: WORKSPACE
  })
  state = applyProtocolNotification(state, 'event/job_status', {
    session_id: 's1',
    state: 'running'
  })
  state = applyProtocolNotification(state, 'event/job_status', {
    session_id: 's2',
    state: 'timed_out'
  })

  assert.equal(state.runStateBySession['s1'], 'running')
  assert.equal(state.runStateBySession['s2'], 'timed_out')
  assert.equal(state.runningBySession['s1'], true)
  assert.equal(state.runningBySession['s2'], false)
})

test('plan step and progress remain isolated per session', () => {
  let state = addSession(baseState(), { sessionId: 's2', workspaceRoot: WORKSPACE })
  state = applyProtocolNotification(state, 'event/plan', {
    session_id: 's1',
    steps: ['Inspect', 'Verify']
  })
  state = applyProtocolNotification(state, 'event/step', {
    session_id: 's1', index: 1, total: 2, text: 'Inspect'
  })
  state = applyProtocolNotification(state, 'event/progress', {
    session_id: 's2', text: 'Waiting for provider'
  })

  assert.deepEqual(state.planBySession['s1'], ['Inspect', 'Verify'])
  assert.deepEqual(state.stepBySession['s1'], { index: 1, total: 2, text: 'Inspect' })
  assert.equal(state.progressBySession['s2'], 'Waiting for provider')
  assert.equal(state.progressBySession['s1'], undefined)
})

test('begin final cancelled and error synchronize run state and final usage', () => {
  let state = beginAssistantMessage(baseState(), 's1')
  assert.equal(state.runStateBySession['s1'], 'running')
  state = applyProtocolNotification(state, 'event/final', {
    session_id: 's1', run_id: 'run-1', text: 'done',
    input_tokens: 20, output_tokens: 5, cache_hit_tokens: null
  })
  assert.equal(state.runStateBySession['s1'], 'succeeded')
  assert.deepEqual(state.usageBySession['s1'], {
    inputTokens: 20, outputTokens: 5, cacheHitTokens: null,
    cacheWriteTokens: null, cacheHitRate: null, reportingStatus: 'not_reported'
  })

  state = beginAssistantMessage(state, 's1')
  state = applyProtocolNotification(state, 'event/done', {
    session_id: 's1', run_id: 'run-2', status: 'cancelled'
  })
  assert.equal(state.runStateBySession['s1'], 'cancelled')
  assert.equal(state.messagesBySession['s1']?.at(-1)?.status, 'error')

  state = beginAssistantMessage(state, 's1')
  state = applyError(state, 's1', 'transport failed')
  assert.equal(state.runStateBySession['s1'], 'failed')
})

test('child session events build a deduplicated tree without crossing root sessions', () => {
  let state = addSession(baseState(), {
    sessionId: 's2',
    workspaceRoot: WORKSPACE
  })
  const created = {
    event_id: 'child-event-1',
    seq: 1,
    root_session_id: 's1',
    parent_session_id: 's1',
    session_id: 'child-a',
    request_id: 'request-a',
    timestamp: 1,
    payload: { agent_id: 'explore' }
  }
  state = applyProtocolNotification(state, 'child_session/created', created)
  state = applyProtocolNotification(state, 'child_session/created', created)
  state = applyProtocolNotification(state, 'child_session/started', {
    ...created,
    event_id: 'child-event-2',
    seq: 2,
    root_session_id: 's2',
    session_id: 'child-b',
    parent_session_id: 's2',
    payload: { agent_id: 'scout' }
  })

  assert.deepEqual(state.childSessionsByRoot['s1'], [
    {
      sessionId: 'child-a',
      parentSessionId: 's1',
      agentId: 'explore',
      state: 'queued'
    }
  ])
  assert.deepEqual(state.childSessionsByRoot['s2'], [
    {
      sessionId: 'child-b',
      parentSessionId: 's2',
      agentId: 'scout',
      state: 'running'
    }
  ])
})

test('child replay never regresses terminal state and records cursor gaps', () => {
  const base = {
    root_session_id: 's1', parent_session_id: 's1', session_id: 'child-a',
    request_id: 'request-a', timestamp: 1, payload: { agent_id: 'reviewer' }
  }
  let state = applyProtocolNotification(baseState(), 'child_session/completed', {
    ...base, event_id: 'event-8', seq: 8
  })
  state = applyProtocolNotification(state, 'child_session/created', {
    ...base, event_id: 'event-2', seq: 2
  })

  assert.equal(state.childSessionsByRoot['s1']?.[0]?.state, 'succeeded')
  assert.equal(state.childSessionsByRoot['s1']?.[0]?.agentId, 'reviewer')
  assert.equal(state.childEventCursorByRoot['s1'], 8)
  assert.equal(state.childEventGapByRoot['s1'], true)
})

test('recovered child uses payload terminal status instead of assuming success', () => {
  const state = applyProtocolNotification(baseState(), 'child_session/recovered', {
    event_id: 'event-r', seq: 1, root_session_id: 's1',
    parent_session_id: 's1', session_id: 'child-r',
    payload: { agent_id: 'scout', status: 'running' }
  })
  assert.equal(state.childSessionsByRoot['s1']?.[0]?.state, 'running')
})

test('child terminal event keeps child usage separate from Primary usage', () => {
  const state = applyProtocolNotification(baseState(), 'child_session/completed', {
    event_id: 'event-usage', seq: 1, root_session_id: 's1',
    parent_session_id: 's1', session_id: 'child-usage',
    payload: {
      agent_id: 'reviewer',
      usage: { input_tokens: 120, output_tokens: 30, cache_hit_tokens: null }
    }
  })
  assert.deepEqual(state.childSessionsByRoot['s1']?.[0]?.usage, {
    inputTokens: 120, outputTokens: 30, cacheHitTokens: null,
    cacheWriteTokens: null, cacheHitRate: null, reportingStatus: 'not_reported'
  })
  assert.deepEqual(state.usageBySession['s1'], {
    inputTokens: null, outputTokens: null, cacheHitTokens: null,
    cacheWriteTokens: null, cacheHitRate: null, reportingStatus: 'not_reported'
  })
})

test('child events keep an inspectable activity timeline for the contextual inspector', () => {
  const base = {
    root_session_id: 's1', parent_session_id: 's1', session_id: 'child-inspect',
    request_id: 'request-child', timestamp: 1, payload: { agent_id: 'explore' }
  }
  let state = applyProtocolNotification(baseState(), 'child_session/started', {
    ...base, event_id: 'child-start', seq: 1
  })
  state = applyProtocolNotification(state, 'child_session/progress', {
    ...base, event_id: 'child-progress', seq: 2,
    payload: { agent_id: 'explore', text: 'Inspecting the release configuration', tool_name: 'grep' }
  })
  state = applyProtocolNotification(state, 'child_session/completed', {
    ...base, event_id: 'child-completed', seq: 3,
    payload: { agent_id: 'explore', summary: 'Found two configuration risks' }
  })

  assert.deepEqual(state.childSessionsByRoot['s1']?.[0]?.events, [
    { eventName: 'progress', text: 'Inspecting the release configuration', toolName: 'grep' },
    { eventName: 'completed', summary: 'Found two configuration risks' }
  ])
})

test('mention dispatch stays running until every requested child reaches a terminal state', () => {
  let state = beginAssistantMessage(addUserMessage(baseState(), 's1', '@explore @scout inspect'), 's1')
  state = beginMentionDispatch(state, 's1', ['explore', 'scout'])
  const base = {
    root_session_id: 's1', parent_session_id: 's1', request_id: 'request', timestamp: 1
  }
  state = applyProtocolNotification(state, 'child_session/completed', {
    ...base, event_id: 'event-1', seq: 1, session_id: 'child-explore',
    payload: { agent_id: 'explore', summary: 'local evidence' }
  })
  assert.equal(state.runningBySession['s1'], true)
  assert.equal(state.messagesBySession['s1']?.at(-1)?.status, 'streaming')

  state = applyProtocolNotification(state, 'child_session/completed', {
    ...base, event_id: 'event-2', seq: 2, session_id: 'child-scout',
    payload: { agent_id: 'scout', summary: 'external evidence' }
  })
  assert.equal(state.runningBySession['s1'], false)
  assert.equal(state.runStateBySession['s1'], 'succeeded')
  assert.equal(state.messagesBySession['s1']?.at(-1)?.status, 'complete')
  assert.match(state.messagesBySession['s1']?.at(-1)?.text ?? '', /@explore[\s\S]*local evidence/)
  assert.match(state.messagesBySession['s1']?.at(-1)?.text ?? '', /@scout[\s\S]*external evidence/)
  assert.equal(timelineFor(state, 's1').at(-1)?.kind, 'final_answer')
})

test('mention dispatch accepts out-of-order terminal sequence numbers from different children', () => {
  let state = beginMentionDispatch(
    beginAssistantMessage(baseState(), 's1'),
    's1',
    ['explore', 'scout']
  )
  const base = { root_session_id: 's1', parent_session_id: 's1', request_id: 'request' }
  state = applyProtocolNotification(state, 'child_session/completed', {
    ...base, event_id: 'event-8', seq: 8, session_id: 'child-explore',
    payload: { agent_id: 'explore', summary: 'local' }
  })
  state = applyProtocolNotification(state, 'child_session/completed', {
    ...base, event_id: 'event-7', seq: 7, session_id: 'child-scout',
    payload: { agent_id: 'scout', summary: 'external' }
  })
  assert.equal(state.runningBySession['s1'], false)
  assert.equal(state.childSessionsByRoot['s1']?.length, 2)
})

test('authoritative child list repairs a replay gap', () => {
  let state = applyProtocolNotification(baseState(), 'child_session/completed', {
    event_id: 'event-8', seq: 8, root_session_id: 's1',
    parent_session_id: 's1', session_id: 'child-old', payload: {}
  })
  state = hydrateChildSessions(state, 's1', [{
    session_id: 'child-current', parent_session_id: 's1',
    agent_id: 'reviewer', status: 'running'
  }], 12)

  assert.deepEqual(state.childSessionsByRoot['s1'], [{
    sessionId: 'child-current', parentSessionId: 's1',
    agentId: 'reviewer', state: 'running'
  }])
  assert.equal(state.childEventCursorByRoot['s1'], 12)
  assert.equal(state.childEventGapByRoot['s1'], false)
})

function approvalRequest(): ApprovalRequest {
  return {
    method: 'approval/request',
    session_id: 's1',
    request_id: 'apr-1',
    risk_level: 'WRITE',
    action: 'bash: write demo.txt',
    details: { tool_name: 'bash' }
  }
}

test('createInitialState starts with no approvals', () => {
  assert.deepEqual(createInitialState().approvals, [])
})

test('addApprovalRequest appends a pending approval item', () => {
  const state = addApprovalRequest(baseState(), approvalRequest())
  assert.equal(state.approvals.length, 1)
  const item = state.approvals[0]
  assert.equal(item?.requestId, 'apr-1')
  assert.equal(item?.sessionId, 's1')
  assert.equal(item?.riskLevel, 'WRITE')
  assert.equal(item?.action, 'bash: write demo.txt')
  assert.deepEqual(item?.details, { tool_name: 'bash' })
  assert.equal(item?.status, 'pending')
})

test('addApprovalRequest dedupes by request id', () => {
  const once = addApprovalRequest(baseState(), approvalRequest())
  const twice = addApprovalRequest(once, approvalRequest())
  assert.equal(twice.approvals.length, 1)
})

test('updateApprovalRequestStatus flips status and attaches an error', () => {
  let state = addApprovalRequest(baseState(), approvalRequest())
  state = updateApprovalRequestStatus(state, 'apr-1', 'submitting')
  assert.equal(state.approvals[0]?.status, 'submitting')
  state = updateApprovalRequestStatus(state, 'apr-1', 'error', '连接已断开')
  assert.equal(state.approvals[0]?.status, 'error')
  assert.equal(state.approvals[0]?.error, '连接已断开')
})

test('updateApprovalRequestStatus ignores unknown ids', () => {
  const state = addApprovalRequest(baseState(), approvalRequest())
  assert.equal(updateApprovalRequestStatus(state, 'nope', 'submitting'), state)
})

test('removeApprovalRequest removes the matching item', () => {
  let state = addApprovalRequest(baseState(), approvalRequest())
  state = removeApprovalRequest(state, 'apr-1')
  assert.equal(state.approvals.length, 0)
})

test('removeApprovalRequestsForSession removes only that session approvals', () => {
  let state = addApprovalRequest(baseState(), approvalRequest())
  state = addApprovalRequest(state, {
    ...approvalRequest(),
    request_id: 'apr-2',
    session_id: 's2'
  })
  const next = removeApprovalRequestsForSession(state, 's1')
  assert.equal(next.approvals.length, 1)
  assert.equal(next.approvals[0]?.requestId, 'apr-2')
})

test('applyRunComplete removes submitting approvals for the session', () => {
  let state = addApprovalRequest(baseState(), approvalRequest())
  state = updateApprovalRequestStatus(state, 'apr-1', 'submitting')
  state = applyRunComplete(state, 's1', runDone('succeeded'))
  assert.equal(state.approvals.length, 0)
  assert.equal(state.runningBySession['s1'], false)
})

test('applyPromptResult removes submitting approvals when the real worker omits event/done', () => {
  let state = addApprovalRequest(baseState(), approvalRequest())
  state = updateApprovalRequestStatus(state, 'apr-1', 'submitting')
  state = applyPromptResult(state, 's1', {
    runId: 'run-prompt-terminal',
    status: 'failed',
    text: 'write rejected after approval'
  })
  assert.equal(state.approvals.length, 0)
  assert.equal(state.runningBySession['s1'], false)
})
