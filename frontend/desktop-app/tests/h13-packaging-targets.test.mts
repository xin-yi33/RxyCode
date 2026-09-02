import assert from 'node:assert/strict'
import { existsSync, readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { test } from 'node:test'
import { fileURLToPath } from 'node:url'
import { shouldDisableLinuxSandbox } from '../src/main/linuxStartup.ts'

const desktopRoot = join(dirname(fileURLToPath(import.meta.url)), '..')
const yaml = readFileSync(join(desktopRoot, 'electron-builder.yml'), 'utf8')
const pkg = JSON.parse(readFileSync(join(desktopRoot, 'package.json'), 'utf8')) as {
  homepage?: string
}
const tSource = readFileSync(join(desktopRoot, 'src/i18n/t.ts'), 'utf8')
const platform = readFileSync(join(desktopRoot, 'src/platform/index.mts'), 'utf8')

test('H13 P3: win/mac/linux targets include nsis, dmg, AppImage, deb', () => {
  assert.match(yaml, /nsis/)
  assert.match(yaml, /^dmg:/m)
  assert.match(yaml, /AppImage/)
  assert.match(yaml, /\n\s+-\s+deb/)
})

test('Linux electron-builder metadata includes a project homepage', () => {
  assert.equal(pkg.homepage, 'https://github.com/xin-yi33/RxyCode')
})

test('H13 P3: locale JSON exists and is imported into the Desktop bundle', () => {
  assert.equal(existsSync(join(desktopRoot, 'src/i18n/locales/zh-CN.json')), true)
  assert.equal(existsSync(join(desktopRoot, 'src/i18n/locales/en.json')), true)
  assert.match(tSource, /locales\/zh-CN\.json/)
  assert.match(tSource, /locales\/en\.json/)
  assert.match(yaml, /from:\s+src\/i18n\/locales/)
  assert.match(yaml, /to:\s+locales/)
})

test('H13 P3: packaged handshake stays on protocol-client; Linux sandbox helper exists', () => {
  assert.match(platform, /initializeHandshake/)
  assert.match(platform, /ProtocolClient/)
  assert.equal(shouldDisableLinuxSandbox('linux', true), true)
  assert.equal(shouldDisableLinuxSandbox('linux', false), false)
  assert.equal(shouldDisableLinuxSandbox('win32', true), false)
  assert.equal(shouldDisableLinuxSandbox('darwin', true), false)
})
