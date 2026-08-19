/**
 * PhaseG-H1 baseline: package boundary, schema version, renderer isolation,
 * and the capability/version handshake placeholder required by complete-G G1.
 */
import assert from 'node:assert/strict'
import { readdirSync, readFileSync, statSync } from 'node:fs'
import { dirname, join, relative } from 'node:path'
import { fileURLToPath } from 'node:url'
import { test } from 'node:test'
import {
  H1_GENERATED_TYPES,
  H1_SCHEMA_PATH,
  isDeclaredCapability,
  matchProtocolVersion
} from '../src/protocol/handshakePlaceholder.ts'

const here = dirname(fileURLToPath(import.meta.url))
const desktopRoot = join(here, '..')
const repoRoot = join(desktopRoot, '..', '..')
const rendererSrc = join(desktopRoot, 'src', 'renderer', 'src')

function walkFiles(dir: string, acc: string[] = []): string[] {
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry)
    const st = statSync(full)
    if (st.isDirectory()) {
      walkFiles(full, acc)
    } else {
      acc.push(full)
    }
  }
  return acc
}

function isProductionRendererSource(filePath: string): boolean {
  const name = filePath.replaceAll('\\', '/')
  if (name.endsWith('.test.ts') || name.endsWith('.test.tsx') || name.endsWith('.test.mts')) {
    return false
  }
  return /\.(ts|tsx|mts)$/.test(name)
}

test('H1: Electron shell, protocol-client, schema, main/preload/renderer exist', () => {
  assert.equal(statSync(join(desktopRoot, 'package.json')).isFile(), true)
  assert.equal(statSync(join(desktopRoot, 'src', 'main', 'index.ts')).isFile(), true)
  assert.equal(statSync(join(desktopRoot, 'src', 'preload', 'index.ts')).isFile(), true)
  assert.equal(statSync(join(desktopRoot, 'src', 'renderer', 'src', 'App.tsx')).isFile(), true)
  assert.equal(statSync(join(desktopRoot, 'src', 'platform', 'index.mts')).isFile(), true)
  assert.equal(statSync(join(repoRoot, 'frontend', 'protocol-client', 'src', 'index.ts')).isFile(), true)
  assert.equal(statSync(join(repoRoot, H1_SCHEMA_PATH)).isFile(), true)
  assert.equal(statSync(join(repoRoot, H1_GENERATED_TYPES)).isFile(), true)
})

test('H1: generated types consume schema protocol_version 1.1.0', () => {
  const schema = JSON.parse(readFileSync(join(repoRoot, H1_SCHEMA_PATH), 'utf8')) as {
    protocol_version?: string
  }
  assert.equal(schema.protocol_version, '1.1.0')
  const generated = readFileSync(join(repoRoot, H1_GENERATED_TYPES), 'utf8')
  assert.match(generated, /Auto-generated/)
  assert.match(generated, /export interface InitializeRequest/)
  const pkg = JSON.parse(readFileSync(join(desktopRoot, 'package.json'), 'utf8')) as {
    dependencies?: Record<string, string>
  }
  assert.equal(pkg.dependencies?.['@rxycode/protocol-client'], 'file:../protocol-client')
})

test('H1: BrowserWindow hardens contextIsolation / no nodeIntegration / sandbox', () => {
  const main = readFileSync(join(desktopRoot, 'src', 'main', 'index.ts'), 'utf8')
  assert.match(main, /contextIsolation:\s*true/)
  assert.match(main, /nodeIntegration:\s*false/)
  assert.match(main, /sandbox:\s*true/)
})

test('H1: production renderer has no Python, Node fs/child_process, or backend HTTP client', () => {
  const forbidden = [
    /\bfrom\s+['"](?:node:)?child_process['"]/,
    /\bfrom\s+['"](?:node:)?fs['"]/,
    /\bfrom\s+['"](?:node:)?net['"]/,
    /\bfrom\s+['"](?:node:)?http['"]/,
    /\bfrom\s+['"](?:node:)?https['"]/,
    /\baxios\b/,
    /\bfetch\s*\(/,
    /\bXMLHttpRequest\b/,
    /\bpython\s+-m\b/,
    /\bimport\s+.*\.py['"]/
  ]
  const offenders: string[] = []
  for (const file of walkFiles(rendererSrc).filter(isProductionRendererSource)) {
    const source = readFileSync(file, 'utf8')
    for (const pattern of forbidden) {
      if (pattern.test(source)) {
        offenders.push(`${relative(desktopRoot, file)} matches ${pattern}`)
      }
    }
  }
  assert.deepEqual(offenders, [])
})

test('H1 handshake placeholder: undeclared capabilities are not available (DC-J3)', () => {
  assert.equal(isDeclaredCapability(undefined, 'threads'), false)
  assert.equal(isDeclaredCapability({}, 'threads'), false)
  assert.equal(isDeclaredCapability({ threads: false }, 'threads'), false)
  assert.equal(isDeclaredCapability({ threads: 'yes' }, 'threads'), false)
  assert.equal(isDeclaredCapability({ threads: true }, 'threads'), true)
})

test('H1 handshake placeholder: version mismatch is a typed protocol_mismatch', () => {
  assert.deepEqual(matchProtocolVersion('1.1.0', '1.1.0'), {
    ok: true,
    protocolVersion: '1.1.0'
  })
  const mismatch = matchProtocolVersion('1.1.0', '1.0.0')
  assert.equal(mismatch.ok, false)
  if (!mismatch.ok) {
    assert.equal(mismatch.code, 'protocol_mismatch')
  }
})
