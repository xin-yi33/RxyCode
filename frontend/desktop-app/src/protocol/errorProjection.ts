/**
 * PhaseG-H2 UI projection of classified handshake/RPC errors.
 * Does not invent backend policy; maps client classification to UI copy.
 */
import {
  classifyProtocolError,
  type ClassifiedError,
  type ErrorHandling
} from '@rxycode/protocol-client'

export type ErrorUiKind = ErrorHandling

export function projectError(error: unknown): ClassifiedError {
  return classifyProtocolError(error)
}

export function errorUiKind(error: unknown): ErrorUiKind {
  return classifyProtocolError(error).handling
}

export function shouldRetry(error: unknown): boolean {
  return errorUiKind(error) === 'retry'
}

export function isUnrecoverable(error: unknown): boolean {
  return errorUiKind(error) === 'unrecoverable'
}

export function requiresUserAction(error: unknown): boolean {
  return errorUiKind(error) === 'user'
}
