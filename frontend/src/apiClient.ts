const API_PORT = process.env.RXYCODE_API_PORT || '8765';

export const API_BASE = process.env.RXYCODE_API_URL || `http://127.0.0.1:${API_PORT}`;

const API_TOKEN = process.env.RXYCODE_API_TOKEN || '';

export function authorizationHeaders(): Record<string, string> {
  return API_TOKEN ? { Authorization: `Bearer ${API_TOKEN}` } : {};
}

export function safeCommandLabel(command: string): string {
  return command.trim().split(/\s+/, 1)[0] || '(empty)';
}
