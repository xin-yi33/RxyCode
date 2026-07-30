/**
 * 前端日志工具 — fire-and-forget POST 到后端 /log 端点
 * 日志统一写入 ~/.rxycode/logs/rxycode.log，与后端日志合并
 */

import { API_BASE, authorizationHeaders } from './apiClient.js';
// 127.0.0.1 (not "localhost") to avoid IPv6 ::1 resolution mismatches with the
// IPv4-only API bind — a common cause of "error connect".

export function log(level: string, message: string, context?: Record<string, any>) {
  fetch(`${API_BASE}/log`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authorizationHeaders() },
    body: JSON.stringify({ level, message, context }),
  }).catch(() => {}); // 静默失败，日志不应影响应用
}

export const logInfo = (msg: string, ctx?: Record<string, any>) => log('INFO', msg, ctx);
export const logWarn = (msg: string, ctx?: Record<string, any>) => log('WARN', msg, ctx);
export const logError = (msg: string, ctx?: Record<string, any>) => log('ERROR', msg, ctx);
export const logDebug = (msg: string, ctx?: Record<string, any>) => log('DEBUG', msg, ctx);
