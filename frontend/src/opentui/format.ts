/** Message/header formatting helpers (mirrored from opentui-app for Vitest coverage). */

import type { Message, Mode } from '../types.js';

export function formatMessageLine(msg: Message): string {
  switch (msg.role) {
    case 'user':
      return `> ${msg.content}`;
    case 'assistant':
      return msg.content;
    case 'thinking':
      return `思考: ${msg.content}`;
    case 'tool':
      return `⚙ ${msg.toolName || 'tool'} [${msg.toolStatus || 'running'}]`;
    case 'system':
      return `• ${msg.content}`;
    default:
      return msg.content;
  }
}

export function formatHeaderLine(mode: Mode, model: string, thinkingLive: boolean): string {
  const base = `RxyCode v1.2.0 · ${mode} · ${model}`;
  return thinkingLive ? `${base} · 思考中` : base;
}

export function formatInputHint(isStreaming: boolean): string {
  return isStreaming ? 'Processing...' : 'Ready';
}

export function messageFg(role: Message['role']): string {
  switch (role) {
    case 'user':
      return '#FFB6C1';
    case 'assistant':
      return '#cdd6f4';
    case 'thinking':
      return '#6c7086';
    case 'tool':
      return '#94e2d5';
    case 'system':
      return '#f9e2af';
    default:
      return '#cdd6f4';
  }
}
