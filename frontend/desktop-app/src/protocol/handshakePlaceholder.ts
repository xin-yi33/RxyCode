/**
 * PhaseG-H1 capability/version handshake placeholder.
 *
 * Schema truth remains `protocol/schema.json` (backend owner). This module
 * only consumes a version string and a capability map already produced by
 * appserver `initialize` / `initialized`. Full typed error projection
 * (timeout, disconnect, unsupported, overload, config missing, mismatch)
 * belongs to PhaseG-H2 — do not expand this file into a second protocol.
 *
 * DC-J3: undeclared capabilities must never render as available.
 */

export const H1_GENERATED_TYPES = 'frontend/protocol-client/src/generated/types.ts'
export const H1_SCHEMA_PATH = 'protocol/schema.json'

export type HandshakeStatus = 'pending' | 'started' | 'completed' | 'failed'

export type ProtocolMismatch = {
  ok: false
  code: 'protocol_mismatch'
  clientVersion: string
  serverVersion: string
}

export type ProtocolMatch = {
  ok: true
  protocolVersion: string
}

export function matchProtocolVersion(
  clientExpected: string,
  serverReported: string
): ProtocolMatch | ProtocolMismatch {
  if (clientExpected.length === 0 || serverReported.length === 0) {
    return {
      ok: false,
      code: 'protocol_mismatch',
      clientVersion: clientExpected,
      serverVersion: serverReported
    }
  }
  if (clientExpected !== serverReported) {
    return {
      ok: false,
      code: 'protocol_mismatch',
      clientVersion: clientExpected,
      serverVersion: serverReported
    }
  }
  return { ok: true, protocolVersion: serverReported }
}

/**
 * Capability entries enter the UI only when the handshake map explicitly
 * sets them to `true`. Presence of a key with any other value is not
 * treated as enabled (DC-J3).
 */
export function isDeclaredCapability(
  serverCapabilities: Readonly<Record<string, unknown>> | null | undefined,
  name: string
): boolean {
  if (serverCapabilities == null || name.length === 0) {
    return false
  }
  return serverCapabilities[name] === true
}
