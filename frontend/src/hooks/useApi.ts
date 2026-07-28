import { useCallback, useRef, useState, useEffect } from 'react';
import axios from 'axios';
import type { Message, StatusInfo, ToolStatus } from '../types.js';
import { logInfo, logWarn, logError, logDebug } from '../log.js';
import { API_BASE, authorizationHeaders, safeCommandLabel } from '../apiClient.js';
import { consumeJsonSseStream } from './sseParser.js';
import { formatUserFacingStreamError } from '../userFacingErrors.js';

/** Bug A: pure guard used by sendMessage to refuse a new turn while streaming. */
export function isSendBlocked(currentlyStreaming: boolean): boolean {
  return currentlyStreaming;
}

export function resolveFinalContent(accumulatedTokens: string, finalText?: string): string {
  return finalText !== undefined ? finalText : accumulatedTokens;
}

/** U3: reasoning deltas append; progress/step/approval/snapshot replace. */
export function applyThinkingAccum(
  acc: string,
  text: string,
  mode: 'append' | 'replace',
): string {
  return mode === 'replace' ? text : acc + text;
}

export function settleActiveMessages(
  messages: Message[],
  toolStatus: Extract<ToolStatus, 'error' | 'timeout' | 'cancelled'>,
): Message[] {
  let changed = false;
  const settled = messages.map(message => {
    if (message.role === 'assistant' && message.done !== true) {
      changed = true;
      return { ...message, done: true };
    }
    if (message.role === 'thinking' && (message.done !== true || message.live !== false)) {
      changed = true;
      return { ...message, done: true, live: false };
    }
    if (message.role === 'tool' && message.toolStatus === 'running') {
      changed = true;
      return { ...message, toolStatus };
    }
    return message;
  });
  return changed ? settled : messages;
}

function insertBeforeMessage(messages: Message[], beforeId: string, message: Message): Message[] {
  const beforeIndex = messages.findIndex(item => item.id === beforeId);
  const insertAt = beforeIndex >= 0 ? beforeIndex : messages.length;
  return [...messages.slice(0, insertAt), message, ...messages.slice(insertAt)];
}

function moveMessageToEnd(messages: Message[], messageId: string, update: (message: Message) => Message): Message[] {
  const index = messages.findIndex(message => message.id === messageId);
  if (index < 0) return messages;
  const message = update(messages[index]);
  return [...messages.slice(0, index), ...messages.slice(index + 1), message];
}

interface StreamEvent {
  type: string;
  text?: string;
  thinking?: string;
  message?: string;
  name?: string;
  args?: string;
  result?: string;
  status?: string;
  index?: number;
  total?: number;
  steps?: string[];
  exitCode?: number;
  duration?: number;
  error?: string;
  error_type?: string;
  kind?: string;
  // 阶段二 safety gate: approval_request payload
  approval_id?: string;
  tool?: string;
  risk?: string;
  question_id?: string;
  question?: string;
  header?: string;
  options?: QuestionOption[];
  input_type?: 'choice' | 'text';
  input_tokens?: number;
  output_tokens?: number;
  message_id?: string;
  timestamp?: number;
  session_schema_version?: number;
  /** Mid-stream /thinking expand: full recorder snapshot (replace, not append). */
  snapshot?: boolean;
}

export interface ApprovalInfo {
  approvalId: string;
  tool: string;
  risk: string;
  args: string;
}

export type ApprovalDecision = 'approved' | 'rejected' | 'always_allow_level';

export interface QuestionOption {
  label: string;
  value: string;
}

export interface QuestionInfo {
  questionId: string;
  question: string;
  header: string;
  options: QuestionOption[];
}

export interface QuestionReply {
  answer?: string;
  cancelled?: boolean;
}

interface ChatListItem {
  name: string;
  preview?: string;
  time?: number;
}

interface MemoryListItem {
  id: number;
  text: string;
  created?: string;
}

interface TaskListItem {
  id: string;
  prompt: string;
  status?: string;
}

export interface AddModelInput {
  providerModelId: string;
  nickname?: string;
  apiKey: string;
  baseUrl: string;
}

export function useApi() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [streamingContent, setStreamingContent] = useState("");
  const [status, setStatus] = useState<StatusInfo | null>(null);
  const [isStreaming, setIsStreaming] = useState(false);
  // 阶段二: pending tool-approval request from the safety gate
  const [pendingApproval, setPendingApproval] = useState<ApprovalInfo | null>(null);
  const [pendingQuestion, setPendingQuestion] = useState<QuestionInfo | null>(null);
  // Bug A fix: mirror isStreaming into a ref so the (async) sendMessage guard
  // reads the freshest value even within the same render tick.  This blocks
  // a 2nd/3rd message from being fired while a response is still streaming.
  const isStreamingRef = useRef(false);
  const cancelRef = useRef<AbortController | null>(null);
  const commandCancelRef = useRef<AbortController | null>(null);
  const debounceTimerRef = useRef<NodeJS.Timeout | null>(null);
  const pendingThinkingRef = useRef<string | null>(null);
  const hasReasoningRef = useRef<boolean>(false);
  const pendingStepRef = useRef<{ index: number; total: number } | null>(null);
  const tokenBatchTimerRef = useRef<NodeJS.Timeout | null>(null);
  const tokenBatchRef = useRef<string>("");
  // Live assistant message id (created when first token arrives, replaced on final)
  const liveAssistantIdRef = useRef<string | null>(null);
  // FIX: Batch queue for message updates during streaming
  // Instead of calling setMessages() on every event (causing flicker),
  // queue updater functions and flush them in batches.
  const msgQueueRef = useRef<Array<(prev: Message[]) => Message[]>>([]);
  const msgFlushTimerRef = useRef<NodeJS.Timeout | null>(null);

  // Flush the message update queue in a single batch
  const flushMsgQueue = useCallback(() => {
    if (msgFlushTimerRef.current) {
      clearTimeout(msgFlushTimerRef.current);
      msgFlushTimerRef.current = null;
    }
    const queue = msgQueueRef.current;
    if (queue.length === 0) return;
    msgQueueRef.current = [];
    setMessages(prev => {
      let result = prev;
      for (const fn of queue) {
        result = fn(result);
      }
      return result;
    });
  }, []);

  // Enqueue a message update (batched, not immediate)
  const queueMsgUpdate = useCallback((fn: (prev: Message[]) => Message[]) => {
    msgQueueRef.current.push(fn);
    if (!msgFlushTimerRef.current) {
      msgFlushTimerRef.current = setTimeout(() => {
        msgFlushTimerRef.current = null;
        flushMsgQueue();
      }, 100); // Flush every 100ms
    }
  }, [flushMsgQueue]);

  useEffect(() => {
    return () => {
      if (tokenBatchTimerRef.current) { clearTimeout(tokenBatchTimerRef.current); tokenBatchTimerRef.current = null; }
      if (cancelRef.current) { cancelRef.current.abort(); cancelRef.current = null; }
      if (commandCancelRef.current) { commandCancelRef.current.abort(); commandCancelRef.current = null; }
      if (debounceTimerRef.current) { clearTimeout(debounceTimerRef.current); debounceTimerRef.current = null; }
      if (msgFlushTimerRef.current) { clearTimeout(msgFlushTimerRef.current); msgFlushTimerRef.current = null; }
    };
  }, []);

  const addMessage = useCallback((msg: Omit<Message, 'id' | 'timestamp'>) => {
    setMessages(prev => {
      if (prev.length > 0) {
        const last = prev[prev.length - 1];
        if (msg.role === 'system' && last.role === 'system' && last.content === msg.content) {
          return prev;
        }
      }
      return [
        ...prev,
        { ...msg, id: `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`, timestamp: Date.now() },
      ];
    });
  }, []);

  const toolStartTimesRef = useRef<Map<string, number>>(new Map());

  const parseToolResult = (raw: string): { stdout: string; stderr?: string; exitCode?: number; status: ToolStatus } => {
    if (!raw) return { stdout: '', status: 'success' };
    const exitMatch = raw.match(/\[?\s*exit(?:\s*code)?\s*:\s*(-?\d+)\s*\]?/i);
    const exitCode = exitMatch ? parseInt(exitMatch[1], 10) : undefined;
    const status: ToolStatus = exitCode !== undefined && exitCode !== 0 ? 'error' : 'success';
    return { stdout: raw, exitCode, status };
  };

  const sendMessage = useCallback(async (content: string, mode: string) => {
    // Bug A: refuse to start a new turn while one is already streaming.
    // Prevents the user (or a fast double-Enter) from firing 2nd/3rd messages
    // into a still-"thinking" agent, which previously spawned N parallel
    // /chat/stream calls (each wasting 26-38s) and looked like a hang.
    if (isSendBlocked(isStreamingRef.current)) {
      logWarn('Ignored duplicate send: a response is already streaming', { mode });
      return;
    }
    isStreamingRef.current = true;
    hasReasoningRef.current = false;
    logInfo('Chat request sent', { len: content.length, mode });
    addMessage({ role: 'user', content });
    setIsStreaming(true);

    const thinkingId = `${Date.now()}-thinking`;
    const assistantId = `${Date.now()}-assistant`;
    const startedAt = Date.now();
    let acc = '';
    let terminalToolStatus: Extract<ToolStatus, 'error' | 'timeout' | 'cancelled'> = 'error';

    // Add thinking message immediately (one-time, not batched)
    setMessages(prev => [
      ...prev,
      { id: thinkingId, role: 'thinking', content: 'Analyzing request...', done: false, live: false, timestamp: startedAt },
    ]);

    // Debounced thinking update (uses queue for batching)
    // 50ms = near-real-time stream of reasoning tokens (was 800ms which felt
    // like a single dump instead of live thinking like opencode/hermes).
    let reasoningAcc = '';
    const debouncedUpdateThinking = (
      text: string,
      opts?: { step?: { index: number; total: number }; mode?: 'append' | 'replace' },
    ) => {
      const mode = opts?.mode ?? 'append';
      const step = opts?.step;
      reasoningAcc = applyThinkingAccum(reasoningAcc, text, mode);
      pendingThinkingRef.current = reasoningAcc;
      if (step) pendingStepRef.current = step;
      if (debounceTimerRef.current) return;
      debounceTimerRef.current = setTimeout(() => {
        debounceTimerRef.current = null;
        const t = pendingThinkingRef.current;
        const s = pendingStepRef.current;
        pendingThinkingRef.current = null;
        pendingStepRef.current = null;
        if (t) {
          queueMsgUpdate(prev => prev.map(m => {
            if (m.id !== thinkingId) return m;
            const update: Partial<Message> = { content: t };
            if (s) { update.stepIndex = s.index; update.stepTotal = s.total; }
            return { ...m, ...update } as Message;
          }));
        }
      }, 50);
    };

    const handleEvent = (ev: StreamEvent) => {
      if (ev.type !== 'token') {
        logDebug('Stream event', { type: ev.type, name: ev.name });
      }
      switch (ev.type) {
        case 'approval_request': {
          // 阶段二 safety gate: surface the approval dialog and reflect the
          // waiting state in the thinking panel.
          const info: ApprovalInfo = {
            approvalId: ev.approval_id || '',
            tool: ev.tool || ev.name || 'unknown',
            risk: ev.risk || 'WRITE',
            args: typeof ev.args === 'string' ? ev.args : JSON.stringify(ev.args ?? {}),
          };
          setPendingApproval(info);
          if (!hasReasoningRef.current) {
            debouncedUpdateThinking(`等待用户确认: ${info.tool} [${info.risk}]`, { mode: 'replace' });
          }
          break;
        }
        case 'question_request': {
          const info: QuestionInfo = {
            questionId: ev.question_id || '',
            question: ev.question || '',
            header: ev.header || '',
            options: Array.isArray(ev.options) ? ev.options : [],
          };
          setPendingQuestion(info);
          if (!hasReasoningRef.current) {
            debouncedUpdateThinking(`Waiting for user answer: ${info.question}`, { mode: 'replace' });
          }
          break;
        }
        case 'reasoning': {
          // Live model reasoning (thinking). Mark the thinking panel as live so
          // it renders during streaming, and make it authoritative over progress.
          // CRITICAL: delta chunks append; mid-run snapshot (and first live chunk
          // after progress status) replace so progress never tapes into reasoning.
          const rt = ev.text || '';
          if (rt.length > 0) {
            const isFirst = !hasReasoningRef.current;
            hasReasoningRef.current = true;
            queueMsgUpdate(prev => prev.map(m =>
              m.id === thinkingId ? { ...m, live: true } : m
            ));
            const mode = ev.snapshot || isFirst ? 'replace' : 'append';
            debouncedUpdateThinking(rt, { mode });
          }
          break;
        }
        case 'progress': {
          // Once live reasoning is streaming, don't let agent progress text
          // overwrite the thinking panel content.
          if (hasReasoningRef.current) break;
          const progressText = ev.text || '';
          // Show all meaningful progress messages (graph node events, step info, etc.)
          // Filter out very long raw model thinking (>150 chars) but show everything else
          if (progressText.length > 0 && progressText.length < 150) {
            debouncedUpdateThinking(progressText, { mode: 'replace' });
          } else if (progressText.length >= 150) {
            // For long messages, show first line only
            const firstLine = progressText.split('\n')[0].slice(0, 120);
            debouncedUpdateThinking(firstLine + '...', { mode: 'replace' });
          }
          break;
        }
        case 'plan': {
          if (hasReasoningRef.current) break;
          const steps = (ev.steps || []).map((s: string, i: number) => `${i + 1}. ${s}`).join('\n');
          reasoningAcc = `Plan (${ev.steps?.length || 0} steps):\n${steps}`;
          pendingThinkingRef.current = reasoningAcc;
          queueMsgUpdate(prev => prev.map(m =>
            m.id === thinkingId ? { ...m, content: reasoningAcc } : m
          ));
          break;
        }
        case 'step': {
          if (hasReasoningRef.current) break;
          debouncedUpdateThinking(`Step ${ev.index}/${ev.total}: ${ev.text}`, {
            step: { index: ev.index || 0, total: ev.total || 0 },
            mode: 'replace',
          });
          break;
        }
        case 'tool_call': {
          const toolMsgId = ev.message_id || `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
          const toolTimestamp = ev.timestamp || Date.now();
          toolStartTimesRef.current.set(toolMsgId, toolTimestamp);
          queueMsgUpdate(prev => insertBeforeMessage(prev, assistantId, {
            id: toolMsgId,
            role: 'tool',
            content: '',
            toolName: ev.name || 'unknown',
            toolArgs: ev.args,
            toolStatus: 'running',
            timestamp: toolTimestamp,
          }));
          break;
        }
        case 'tool_result': {
          queueMsgUpdate(prev => {
            const c = [...prev];
            let targetIdx = -1;
            for (let k = c.length - 1; k >= 0; k--) {
              if (c[k].role === 'tool' && (!ev.message_id || c[k].id === ev.message_id)) { targetIdx = k; break; }
            }
            if (targetIdx >= 0) {
              const target = c[targetIdx];
              const toolStartedAt = toolStartTimesRef.current.get(target.id) || target.timestamp;
              const duration = (Date.now() - toolStartedAt) / 1000;
              toolStartTimesRef.current.delete(target.id);
              const parsed = parseToolResult(ev.result || '');
              const toolStatus: ToolStatus = (ev.status as ToolStatus) || parsed.status;
              c[targetIdx] = {
                ...target,
                content: ev.result || '',
                toolStdout: ev.result || '',
                toolStatus: toolStatus,
                toolDuration: ev.duration ?? duration,
                toolExitCode: ev.exitCode ?? parsed.exitCode,
                toolError: ev.error || (toolStatus === 'error' ? parsed.stdout : undefined),
              };
            }
            return c;
          });
          break;
        }
        case 'token': {
          acc += ev.text;
          tokenBatchRef.current = acc;
          // Create or update a LIVE assistant message so the user watches
          // the answer stream in real time (opencode/hermes style) instead
          // of waiting for the final event to dump it all at once.
          if (!liveAssistantIdRef.current) {
            liveAssistantIdRef.current = assistantId;
          }
          if (!tokenBatchTimerRef.current) {
            tokenBatchTimerRef.current = setTimeout(() => {
              tokenBatchTimerRef.current = null;
              const currentAcc = tokenBatchRef.current;
              setStreamingContent(currentAcc);
              // Update the live assistant message content in the chat panel
              queueMsgUpdate(prev => {
                const idx = prev.findIndex(m => m.id === assistantId);
                if (idx >= 0) {
                  const updated = [...prev];
                  updated[idx] = { ...updated[idx], content: currentAcc };
                  return updated;
                }
                // First token: insert a live assistant message right after thinking
                const thinkIdx = prev.findIndex(m => m.id === thinkingId);
                const insertAt = thinkIdx >= 0 ? thinkIdx + 1 : prev.length;
                const newMsg: Message = {
                  id: assistantId,
                  role: 'assistant',
                  content: currentAcc,
                  done: false,
                  timestamp: Date.now(),
                };
                return [...prev.slice(0, insertAt), newMsg, ...prev.slice(insertAt)];
              });
            }, 50); // 50ms batch for smooth streaming (was 300ms)
          }
          break;
        }
        case 'final': {
          const finalContent = resolveFinalContent(acc, ev.text);
          if (tokenBatchTimerRef.current) {
            clearTimeout(tokenBatchTimerRef.current);
            tokenBatchTimerRef.current = null;
          }
          tokenBatchRef.current = finalContent;
          if (debounceTimerRef.current) {
            clearTimeout(debounceTimerRef.current);
            debounceTimerRef.current = null;
          }
          // Merge pending thinking flush + final update into ONE setMessages call
          // to avoid double render (was: flushMsgQueue() then setMessages())
          const pendingThinking = pendingThinkingRef.current || reasoningAcc || '';
          pendingThinkingRef.current = null;
          reasoningAcc = '';
          // Clear the message queue since we're doing a single batch update
          const queuedUpdates = msgQueueRef.current;
          msgQueueRef.current = [];
          if (msgFlushTimerRef.current) {
            clearTimeout(msgFlushTimerRef.current);
            msgFlushTimerRef.current = null;
          }
          setMessages(prev => {
            // Apply any queued updates first
            let c = prev;
            for (const fn of queuedUpdates) {
              c = fn(c);
            }
            // Mark thinking done + use pending thinking content if no ev.thinking
            const thinkingContent = ev.thinking || pendingThinking || 'Done';
            c = c.map(m =>
              m.id === thinkingId
                ? { ...m, content: thinkingContent, done: true, live: false, elapsed: (Date.now() - startedAt) / 1000 }
                : m
            );
            // Keep the authoritative answer dynamic until the terminal done event.
            // Late process/tool events must still be able to render before it.
            const elapsed = (Date.now() - startedAt) / 1000;
            const idx = c.findIndex(m => m.id === assistantId);
            if (idx >= 0) {
              c = moveMessageToEnd(c, assistantId, message => ({
                ...message,
                content: finalContent,
                done: false,
                elapsed,
              }));
            } else if (finalContent.trim()) {
              c = [...c, { id: assistantId, role: 'assistant', content: finalContent, done: false, elapsed, timestamp: Date.now() }];
            }
            return c;
          });
          liveAssistantIdRef.current = null;
          setStreamingContent('');
          break;
        }
        case 'error': {
          const errType = ev.error_type || ev.kind || 'agent';
          const elapsedSoFar = ((Date.now() - startedAt) / 1000).toFixed(1);
          logError('Stream error received', { message: ev.message, type: errType });
          addMessage({ role: 'system', content: formatUserFacingStreamError(ev.message || '') });
          break;
        }
        default:
          break;
      }
    };

    try {
      const controller = new AbortController();
      cancelRef.current = controller;

      // Retry once on a pure network failure (e.g. backend still starting up),
      // so a briefly-unready API doesn't permanently surface "error connect".
      let resp: Response | null = null;
      let lastErr: unknown = null;
      for (let attempt = 0; attempt < 2; attempt++) {
        try {
          resp = await fetch(`${API_BASE}/chat/stream`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', ...authorizationHeaders() },
            body: JSON.stringify({ message: content, mode }),
            signal: controller.signal,
          });
          lastErr = null;
          break;
        } catch (e) {
          lastErr = e;
          if (attempt === 0) {
            logWarn('Chat stream connect failed, retrying once', { error: e instanceof Error ? e.message : String(e), api: API_BASE });
            await new Promise((r) => setTimeout(r, 1500));
          }
        }
      }
      if (!resp) throw lastErr ?? new Error('Unknown connection error');
      if (!resp.ok || !resp.body) throw new Error(`HTTP ${resp.status}`);

      const reader = (resp.body as ReadableStream<Uint8Array>).getReader();
      await consumeJsonSseStream<StreamEvent>(
        reader,
        handleEvent,
        (event) => event.type === 'done',
      );
    } catch (err: unknown) {
      const errorMessage = err instanceof Error ? err.message : String(err);
      const elapsedSoFar = ((Date.now() - startedAt) / 1000).toFixed(1);
      logError('Chat request failed', { error: errorMessage, elapsed: elapsedSoFar });
      setMessages(prev => prev.map(m =>
        m.id === thinkingId ? { ...m, content: (err instanceof Error ? err.name : '') === 'AbortError' ? 'Cancelled' : m.content, done: true, live: false } : m
      ));
      if ((err instanceof Error ? err.name : '') === 'AbortError') {
        terminalToolStatus = 'cancelled';
        addMessage({ role: 'system', content: `Cancelled (${elapsedSoFar}s)` });
      } else if ((err instanceof Error ? err.name : '') === 'TimeoutError' || /timeout/i.test(errorMessage || '')) {
        terminalToolStatus = 'timeout';
        addMessage({ role: 'system', content: `Timeout (${elapsedSoFar}s): ${errorMessage}` });
      } else {
        terminalToolStatus = 'error';
        addMessage({ role: 'system', content: `连接后端失败 (${API_BASE})：${errorMessage}` });
      }
    } finally {
      const totalElapsed = ((Date.now() - startedAt) / 1000).toFixed(1);
      logInfo('Chat stream done', { elapsed: totalElapsed });
      // Flush any remaining batched updates before settling every active message.
      flushMsgQueue();
      setMessages(prev => settleActiveMessages(prev, terminalToolStatus));
      setIsStreaming(false);
      isStreamingRef.current = false;
      cancelRef.current = null;
      setStreamingContent('');
      setPendingQuestion(null);
      if (debounceTimerRef.current) { clearTimeout(debounceTimerRef.current); debounceTimerRef.current = null; }
      pendingThinkingRef.current = null;
      if (tokenBatchTimerRef.current) { clearTimeout(tokenBatchTimerRef.current); tokenBatchTimerRef.current = null; }
      tokenBatchRef.current = '';
      liveAssistantIdRef.current = null;
      toolStartTimesRef.current.clear();
      msgQueueRef.current = [];
      if (msgFlushTimerRef.current) { clearTimeout(msgFlushTimerRef.current); msgFlushTimerRef.current = null; }
    }
  }, [addMessage, flushMsgQueue, queueMsgUpdate]);

  const sendCommand = useCallback(async (command: string) => {
    const commandName = safeCommandLabel(command);
    logDebug('Command sent', { command: commandName });
    const controller = new AbortController();
    commandCancelRef.current = controller;
    try {
      const resp = await axios.post(
        `${API_BASE}/command`,
        { command },
        { headers: authorizationHeaders(), signal: controller.signal },
      );
      const data = resp.data;
      if (data.action === 'mode_changed') { return data; }
      // 列表型数据不再 addMessage，由 App 层弹窗展示
      return data;
    } catch (err: unknown) {
      const errorMessage = err instanceof Error ? err.message : String(err);
      logError('Command error', { command: commandName, error: errorMessage });
      console.error('Command error:', errorMessage);
      addMessage({ role: 'system', content: 'Command error: ' + errorMessage });
      return null;
    } finally {
      if (commandCancelRef.current === controller) commandCancelRef.current = null;
    }
  }, [addMessage]);

  const addModel = useCallback(async (input: AddModelInput) => {
    try {
      const resp = await axios.post(
        `${API_BASE}/models/onboard`,
        {
          provider_model_id: input.providerModelId,
          nickname: input.nickname || undefined,
          api_key: input.apiKey,
          base_url: input.baseUrl,
        },
        { headers: authorizationHeaders() },
      );
      return resp.data;
    } catch (err: unknown) {
      const responseDetail = axios.isAxiosError(err) ? err.response?.data?.detail : undefined;
      const message = typeof responseDetail === 'string'
        ? responseDetail
        : (err instanceof Error ? err.message : String(err));
      logError('Model onboarding failed', { error: message });
      return { action: 'error', message };
    }
  }, []);

  const fetchStatus = useCallback(async () => {
    try {
      const resp = await axios.get(`${API_BASE}/status`, {
        timeout: 5000,
        headers: authorizationHeaders(),
      });
      setStatus(resp.data);
    } catch {
      // silent
    }
  }, []);

  const cancelRequest = useCallback(() => {
    const question = pendingQuestion;
    setPendingQuestion(null);
    if (question) {
      void axios.post(`${API_BASE}/question/respond`, {
        question_id: question.questionId,
        cancelled: true,
      }, { headers: authorizationHeaders() }).catch(() => {});
    }
    void axios.post(
      `${API_BASE}/cancel`,
      undefined,
      { headers: authorizationHeaders() },
    ).catch(() => {});
    if (cancelRef.current) {
      cancelRef.current.abort();
      cancelRef.current = null;
    }
    if (commandCancelRef.current) {
      commandCancelRef.current.abort();
      commandCancelRef.current = null;
    }
  }, [pendingQuestion]);

  // 阶段二: POST the user's decision back to the safety gate.
  const respondApproval = useCallback(async (decision: ApprovalDecision) => {
    const pending = pendingApproval;
    if (!pending) return;
    setPendingApproval(null);
    try {
      await axios.post(`${API_BASE}/approve`, {
        approval_id: pending.approvalId,
        decision,
      }, { headers: authorizationHeaders() });
      logInfo('Approval responded', { tool: pending.tool, decision });
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      logError('Approval respond failed', { error: msg });
      addMessage({ role: 'system', content: 'Approval failed: ' + msg });
    }
  }, [pendingApproval, addMessage]);

  const respondQuestion = useCallback(async (reply: QuestionReply) => {
    const pending = pendingQuestion;
    if (!pending) return;
    setPendingQuestion(null);
    try {
      await axios.post(`${API_BASE}/question/respond`, {
        question_id: pending.questionId,
        answer: reply.cancelled ? undefined : (reply.answer ?? ''),
        cancelled: Boolean(reply.cancelled),
      }, { headers: authorizationHeaders() });
      logInfo('Question responded', {
        question_id: pending.questionId,
        cancelled: Boolean(reply.cancelled),
      });
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      logError('Question respond failed', { error: msg });
      addMessage({ role: 'system', content: 'Question response failed: ' + msg });
    }
  }, [pendingQuestion, addMessage]);

  return { messages, streamingContent, status, isStreaming, sendMessage, sendCommand, addModel, fetchStatus, cancelRequest, addMessage, setMessages, pendingApproval, respondApproval, pendingQuestion, respondQuestion };
}
