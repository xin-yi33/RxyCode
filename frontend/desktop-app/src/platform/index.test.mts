import { test } from 'node:test'
import assert from 'node:assert/strict'
import {
  createConversationConnection,
  createAppserverPlatform,
  createDiagnosticsPlatform,
  type AppserverInfo,
  type AppserverPlatform
} from './index.mts'

const INFO: AppserverInfo = {
  repoRoot: 'D:\\repo',
  protocolVersion: '1.0.0',
  appVersion: '0.1.0'
}

function createFakePlatform(): {
  platform: AppserverPlatform
  lines: string[]
  emitLine: (line: string) => void
  lineSubscribers: () => number
} {
  const lineCallbacks: Array<(line: string) => void> = []
  const lines: string[] = []
  const platform: AppserverPlatform = {
    getInfo: async () => INFO,
    getStatus: async () => 'running',
    start: () => {},
    stop: () => {},
    onStatus: () => () => {},
    pickWorkspaceDirectory: async () => null,
    sendLine: (line) => {
      lines.push(line)
    },
    onLine: (callback) => {
      lineCallbacks.push(callback)
      return () => {
        const index = lineCallbacks.indexOf(callback)
        if (index >= 0) lineCallbacks.splice(index, 1)
      }
    }
  }
  return {
    platform,
    lines,
    emitLine: (line) => {
      for (const callback of [...lineCallbacks]) callback(line)
    },
    lineSubscribers: () => lineCallbacks.length
  }
}

test('createAppserverPlatform pickWorkspaceDirectory delegates to the preload bridge', async () => {
  let called = false
  const fakeWindow = {
    api: {
      appserver: {
        getStatus: async () => 'stopped',
        start: async () => 'stopped',
        stop: async () => 'stopped',
        onStatus: () => () => {},
        onLog: () => () => {},
        sendLine: async () => {},
        onLine: () => () => {},
        getInfo: async () => INFO
      },
      workspace: {
        pickDirectory: async () => {
          called = true
          return 'D:\\picked'
        }
      }
    }
  } as unknown as Window
  const holder = globalThis as { window?: unknown }
  const previous = holder.window
  holder.window = fakeWindow
  try {
    const platform = createAppserverPlatform()
    assert.equal(await platform.pickWorkspaceDirectory(), 'D:\\picked')
    assert.equal(called, true)
  } finally {
    if (previous === undefined) {
      delete holder.window
    } else {
      holder.window = previous
    }
  }
})

function initializeResponse(id: number): string {
  return JSON.stringify({
    jsonrpc: '2.0',
    id,
    result: { protocol_version: '1.0.0', server_name: 'rxycode-appserver' }
  })
}

function errorResponse(id: number, message = 'transient'): string {
  return JSON.stringify({
    jsonrpc: '2.0',
    id,
    error: { code: -32000, message }
  })
}

function delay(ms: number): Promise<void> {
  return new Promise((resolveWait) => setTimeout(resolveWait, ms))
}

async function attachWithResponse(
  connection: ReturnType<typeof createConversationConnection>,
  emitLine: (line: string) => void
): Promise<void> {
  const pending = connection.attach(INFO)
  emitLine(initializeResponse(1))
  await pending
}

test('attach creates a ProtocolClient and sends initialize over the platform transport', async () => {
  const fake = createFakePlatform()
  const connection = createConversationConnection({
    platform: fake.platform,
    onNotification: () => {},
    initializeTimeoutMs: 1000
  })
  const pending = connection.attach(INFO)
  assert.ok(connection.client !== null)
  assert.equal(fake.lines.length, 1)
  const sent = JSON.parse(fake.lines[0] ?? '{}') as {
    method: string
    id: number
    params: { protocol_version: string; client_name: string }
  }
  assert.equal(sent.method, 'initialize')
  assert.equal(sent.id, 1)
  assert.equal(sent.params.protocol_version, '1.0.0')
  assert.equal(sent.params.client_name, 'rxycode-desktop')
  fake.emitLine(initializeResponse(sent.id))
  await pending
})

test('attach wires transport notifications to onNotification', async () => {
  const fake = createFakePlatform()
  const seen: Array<{ method: string; params: unknown }> = []
  const connection = createConversationConnection({
    platform: fake.platform,
    onNotification: (method, params) => {
      seen.push({ method, params })
    }
  })
  await attachWithResponse(connection, fake.emitLine)

  fake.emitLine(
    JSON.stringify({
      jsonrpc: '2.0',
      method: 'event/message_delta',
      params: { method: 'event/message_delta', session_id: 's1', text: '你好' }
    })
  )

  assert.equal(seen.length, 1)
  assert.equal(seen[0]?.method, 'event/message_delta')
  assert.deepEqual(seen[0]?.params, {
    method: 'event/message_delta',
    session_id: 's1',
    text: '你好'
  })
})

test('attach is idempotent while already attached', async () => {
  const fake = createFakePlatform()
  const connection = createConversationConnection({
    platform: fake.platform,
    onNotification: () => {}
  })
  await attachWithResponse(connection, fake.emitLine)
  await connection.attach(INFO)
  const initializes = fake.lines
    .map((line) => JSON.parse(line) as { method?: string })
    .filter((message) => message.method === 'initialize')
  assert.equal(initializes.length, 1)
})

test('initialize timeout retries and then rejects, leaving the connection clean for reattach', async () => {
  const fake = createFakePlatform()
  const connection = createConversationConnection({
    platform: fake.platform,
    onNotification: () => {},
    initializeTimeoutMs: 50,
    initializeRetryDelayMs: 10
  })
  await assert.rejects(connection.attach(INFO), /RPC timeout: initialize/)
  assert.equal(connection.client, null)
  assert.equal(fake.lineSubscribers(), 0)

  const retry = connection.attach(INFO)
  assert.equal(fake.lines.length, 4)
  assert.equal((JSON.parse(fake.lines[3] ?? '{}') as { id: number }).id, 1)
  fake.emitLine(initializeResponse(1))
  await retry
  assert.ok(connection.client !== null)
})

test('attach does not retry unrecoverable JSON-RPC -32000', async () => {
  const fake = createFakePlatform()
  const connection = createConversationConnection({
    platform: fake.platform,
    onNotification: () => {},
    initializeTimeoutMs: 1000,
    initializeRetryDelayMs: 10
  })
  const pending = connection.attach(INFO)
  fake.emitLine(errorResponse(1, 'transient'))
  await assert.rejects(pending, /transient/)
  assert.equal(connection.client, null)
  const initializes = fake.lines
    .map((line) => JSON.parse(line) as { method?: string })
    .filter((message) => message.method === 'initialize')
  assert.equal(initializes.length, 1)
})

test('attach gives up after max attempts, cleans up, and reports the connection error', async () => {
  const fake = createFakePlatform()
  const seenErrors: Error[] = []
  const connection = createConversationConnection({
    platform: fake.platform,
    onNotification: () => {},
    initializeTimeoutMs: 1000,
    initializeMaxAttempts: 2,
    initializeRetryDelayMs: 10,
    onConnectionError: (error) => {
      seenErrors.push(error)
    }
  })

  const pending = connection.attach(INFO)
  fake.emitLine(errorResponse(1, 'still down'))
  await assert.rejects(pending, /still down/)

  assert.equal(connection.client, null)
  assert.equal(fake.lineSubscribers(), 0)
  assert.equal(seenErrors.length, 1)
  assert.match(seenErrors[0]?.message ?? '', /still down/)
})

test('detach rejects pending requests and unsubscribes; reattach sends a fresh initialize', async () => {
  const fake = createFakePlatform()
  const connection = createConversationConnection({
    platform: fake.platform,
    onNotification: () => {}
  })
  await attachWithResponse(connection, fake.emitLine)

  const promptPromise = connection.client?.request('session/prompt', {
    session_id: 's1',
    text: 'hang:blocked'
  })
  assert.ok(promptPromise)
  connection.detach('appserver exited')
  await assert.rejects(promptPromise, /appserver exited/)
  assert.equal(connection.client, null)
  assert.equal(fake.lineSubscribers(), 0)

  await attachWithResponse(connection, fake.emitLine)
  const initializes = fake.lines
    .map((line) => JSON.parse(line) as { method?: string; id: number })
    .filter((message) => message.method === 'initialize')
  assert.equal(initializes.length, 2)
  assert.equal(initializes[1]?.id, 1)
})

test('createAppserverPlatform restart stops and starts the appserver', async () => {
  const calls: string[] = []
  const fakeWindow = {
    api: {
      appserver: {
        getStatus: async () => 'running',
        start: async () => { calls.push('start'); return 'starting' },
        stop: async () => { calls.push('stop'); return 'stopped' },
        onStatus: () => () => {},
        onLog: () => () => {},
        sendLine: async () => {},
        onLine: () => () => {},
        getInfo: async () => INFO
      },
      workspace: { pickDirectory: async () => null }
    }
  } as unknown as Window
  const holder = globalThis as { window?: unknown }
  const previous = holder.window
  holder.window = fakeWindow
  try {
    await createAppserverPlatform().restart?.()
    assert.deepEqual(calls, ['stop', 'start'])
  } finally {
    if (previous === undefined) delete holder.window
    else holder.window = previous
  }
})

test('reconnect replaces the stale client and performs a fresh initialize', async () => {
  const fake = createFakePlatform()
  const connection = createConversationConnection({
    platform: fake.platform,
    onNotification: () => {}
  })
  await attachWithResponse(connection, fake.emitLine)
  const reconnecting = connection.reconnect(INFO)
  const secondInitialize = JSON.parse(fake.lines.at(-1) ?? '{}') as { id: number }
  fake.emitLine(initializeResponse(secondInitialize.id))
  await reconnecting
  assert.equal(fake.lineSubscribers(), 1)
  assert.equal(fake.lines.filter((line) => JSON.parse(line).method === 'initialize').length, 2)
})

test('stopped -> running -> stopped -> running creates a fresh client per running transition', async () => {
  const fake = createFakePlatform()
  const connection = createConversationConnection({
    platform: fake.platform,
    onNotification: () => {}
  })

  connection.detach('appserver not running')
  assert.equal(connection.client, null)

  await attachWithResponse(connection, fake.emitLine)
  assert.ok(connection.client !== null)

  connection.detach('appserver not running')
  assert.equal(connection.client, null)
  assert.equal(fake.lineSubscribers(), 0)

  await attachWithResponse(connection, fake.emitLine)
  assert.ok(connection.client !== null)

  const initializes = fake.lines
    .map((line) => JSON.parse(line) as { method?: string })
    .filter((message) => message.method === 'initialize')
  assert.equal(initializes.length, 2)
})

test('detach while initialize is in flight tears the connection down cleanly', async () => {
  const fake = createFakePlatform()
  const connection = createConversationConnection({
    platform: fake.platform,
    onNotification: () => {},
    initializeTimeoutMs: 5000
  })
  const pending = connection.attach(INFO).catch((error: unknown) => error)
  connection.detach('stopped mid-initialize')
  const error = await pending
  assert.match(String(error), /stopped mid-initialize/)
  assert.equal(connection.client, null)
  assert.equal(fake.lineSubscribers(), 0)
})

function approvalServerRequestLine(): string {
  return JSON.stringify({
    jsonrpc: '2.0',
    id: 'apr-1',
    method: 'approval/request',
    params: {
      method: 'approval/request',
      session_id: 's1',
      request_id: 'apr-1',
      risk_level: 'WRITE',
      action: 'bash: write demo.txt'
    }
  })
}

test('attach wires approval server requests to onServerRequest and writes the reply', async () => {
  const fake = createFakePlatform()
  const seen: Array<{ method: string; params: unknown }> = []
  const connection = createConversationConnection({
    platform: fake.platform,
    onNotification: () => {},
    onServerRequest: (method, params) => {
      seen.push({ method, params })
      return {
        request_id: (params as { request_id: string }).request_id,
        decision: 'approved'
      }
    }
  })
  await attachWithResponse(connection, fake.emitLine)

  fake.emitLine(approvalServerRequestLine())
  await delay(20)

  assert.equal(seen.length, 1)
  assert.equal(seen[0]?.method, 'approval/request')
  const responseLine = JSON.parse(fake.lines.at(-1) ?? '{}') as {
    id: string
    result: { decision: string }
  }
  assert.equal(responseLine.id, 'apr-1')
  assert.equal(responseLine.result.decision, 'approved')
})

test('detach aborts pending approval server requests with the detach reason', async () => {
  const fake = createFakePlatform()
  const aborted: Error[] = []
  const connection = createConversationConnection({
    platform: fake.platform,
    onNotification: () => {},
    // Never settles on its own; only the detach abort path can finish it.
    onServerRequest: () => new Promise<{ request_id: string; decision: string }>(() => {}),
    onServerRequestAborted: (error) => {
      aborted.push(error)
    }
  })
  await attachWithResponse(connection, fake.emitLine)

  fake.emitLine(approvalServerRequestLine())
  await delay(20)
  connection.detach('appserver exited')

  assert.equal(aborted.length, 1)
  assert.match(aborted[0]?.message ?? '', /appserver exited/)
})

test('createDiagnosticsPlatform delegates update and crash-report calls to the bridge', async () => {
  const calls: string[] = []
  const fakeWindow = {
    api: {
      appserver: {
        getStatus: async () => 'stopped',
        start: async () => 'stopped',
        stop: async () => 'stopped',
        onStatus: () => () => {},
        onLog: () => () => {},
        sendLine: async () => {},
        onLine: () => () => {},
        getInfo: async () => INFO
      },
      update: {
        getStatus: async () => ({ status: 'idle' }),
        check: async () => {
          calls.push('check')
          return { status: 'not-available' }
        },
        download: async () => {
          calls.push('download')
          return { status: 'downloaded' }
        },
        install: async () => {
          calls.push('install')
        },
        onStatus: () => () => {}
      },
      crashReport: {
        getConsent: async () => {
          calls.push('getConsent')
          return true
        },
        setConsent: async (enabled: boolean) => {
          calls.push(`setConsent:${String(enabled)}`)
        },
        list: async () => {
          calls.push('list')
          return [{ id: 'a', capturedAt: '2026-01-01', source: 'render-process-gone', path: 'x' }]
        },
        onCaptured: () => () => {}
      },
      workspace: {
        pickDirectory: async () => null
      }
    }
  } as unknown as Window
  const holder = globalThis as { window?: unknown }
  const previous = holder.window
  holder.window = fakeWindow
  try {
    const platform = createDiagnosticsPlatform()
    const afterCheck = await platform.checkForUpdates()
    assert.equal(afterCheck.status, 'not-available')
    const afterDownload = await platform.downloadUpdate()
    assert.equal(afterDownload.status, 'downloaded')
    platform.installUpdate()
    assert.equal(await platform.getCrashConsent(), true)
    await platform.setCrashConsent(false)
    const reports = await platform.listCrashReports()
    assert.equal(reports[0].source, 'render-process-gone')
    assert.deepEqual(calls, [
      'check',
      'download',
      'install',
      'getConsent',
      'setConsent:false',
      'list'
    ])
  } finally {
    holder.window = previous
  }
})
