import assert from 'node:assert/strict'
import { test } from 'node:test'
import {
  ProtocolDisconnectError,
  ProtocolRpcError,
  ProtocolTimeoutError
} from '@rxycode/protocol-client'
import { isUiEntryEnabled } from '../src/protocol/capabilityGate.ts'
import {
  errorUiKind,
  isUnrecoverable,
  requiresUserAction,
  shouldRetry
} from '../src/protocol/errorProjection.ts'
import { isDeclaredCapability } from '../src/protocol/handshakePlaceholder.ts'

const serverCaps = {
  sessions: true,
  approval: true,
  models: true,
  credentials: true
}

test('H2: undeclared capabilities do not enable UI entries (DC-J3)', () => {
  assert.equal(isUiEntryEnabled(serverCaps, 'sessionList'), true)
  assert.equal(isUiEntryEnabled(serverCaps, 'approvalModal'), true)
  assert.equal(isUiEntryEnabled(serverCaps, 'modelsPanel'), true)
  assert.equal(isUiEntryEnabled(serverCaps, 'autoReview'), false)
  assert.equal(isUiEntryEnabled(serverCaps, 'multiAgent'), false)
  assert.equal(isDeclaredCapability(serverCaps, 'auto_review'), false)
})

test('H2: errors distinguish retry / user / unrecoverable', () => {
  const timeout = new ProtocolTimeoutError('initialize')
  const unsupported = new ProtocolRpcError({ code: -32601, message: 'Method not found' })
  const missing = new ProtocolRpcError({
    code: -32602,
    message: 'workspace_root is required'
  })
  const generic = new ProtocolRpcError({ code: -32000, message: 'server overloaded' })
  const overloaded = new ProtocolRpcError({ code: -32008, message: 'overloaded' })
  const closed = new ProtocolDisconnectError('appserver exited')

  assert.equal(shouldRetry(timeout), true)
  assert.equal(shouldRetry(closed), true)
  assert.equal(shouldRetry(overloaded), true)
  assert.equal(requiresUserAction(unsupported), true)
  assert.equal(requiresUserAction(missing), true)
  assert.equal(isUnrecoverable(generic), true)
  assert.equal(errorUiKind(timeout), 'retry')
  assert.equal(errorUiKind(unsupported), 'user')
  assert.equal(errorUiKind(generic), 'unrecoverable')
})
