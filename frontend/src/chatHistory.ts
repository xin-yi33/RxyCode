import type { Message, ToolStatus } from './types.js';

type RestoredRole = Message['role'];

const RESTORED_ROLES = new Set<RestoredRole>([
  'user', 'assistant', 'tool', 'thinking', 'system',
]);
const TOOL_STATUSES = new Set<ToolStatus>([
  'running', 'success', 'error', 'timeout', 'cancelled',
]);

interface ChatLoadedResponse {
  action: 'chat_loaded';
  messages: unknown[];
  schema_version?: number;
}

export function isChatLoadedResponse(value: unknown): value is ChatLoadedResponse {
  if (!value || typeof value !== 'object') return false;
  const response = value as { action?: unknown; messages?: unknown };
  return response.action === 'chat_loaded' && Array.isArray(response.messages);
}

export function mapLoadedChatMessages(records: unknown[], loadedAt = Date.now()): Message[] {
  return records.flatMap((record, index) => {
    if (!record || typeof record !== 'object') return [];

    const raw = record as Record<string, unknown>;
    const { role, content } = raw;
    if (typeof role !== 'string' || !RESTORED_ROLES.has(role as RestoredRole)) return [];
    if (typeof content !== 'string') return [];

    const restored: Message = {
      id: typeof raw.id === 'string' && raw.id ? raw.id : `loaded-${loadedAt}-${index}`,
      role: role as RestoredRole,
      content,
      timestamp: typeof raw.timestamp === 'number' && Number.isFinite(raw.timestamp)
        ? raw.timestamp
        : loadedAt + index,
    };
    if (typeof raw.version === 'number') restored.version = raw.version;
    if (typeof raw.run_id === 'string') restored.runId = raw.run_id;
    if (typeof raw.elapsed === 'number') restored.elapsed = raw.elapsed;

    if (restored.role === 'assistant') {
      restored.done = true;
    }
    if (restored.role === 'thinking') {
      if (typeof raw.done === 'boolean') restored.done = raw.done;
      if (typeof raw.live === 'boolean') restored.live = raw.live;
      if (typeof raw.stepIndex === 'number') restored.stepIndex = raw.stepIndex;
      if (typeof raw.stepTotal === 'number') restored.stepTotal = raw.stepTotal;
    }
    if (restored.role === 'tool') {
      if (typeof raw.toolName === 'string') restored.toolName = raw.toolName;
      if (typeof raw.toolArgs === 'string') restored.toolArgs = raw.toolArgs;
      if (typeof raw.toolStdout === 'string') restored.toolStdout = raw.toolStdout;
      if (typeof raw.toolError === 'string') restored.toolError = raw.toolError;
      if (typeof raw.toolDuration === 'number') restored.toolDuration = raw.toolDuration;
      if (typeof raw.toolExitCode === 'number') restored.toolExitCode = raw.toolExitCode;
      if (typeof raw.toolStatus === 'string' && TOOL_STATUSES.has(raw.toolStatus as ToolStatus)) {
        restored.toolStatus = raw.toolStatus as ToolStatus;
      }
    }
    return [restored];
  });
}
