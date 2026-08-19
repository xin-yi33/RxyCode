import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { test } from 'node:test'
import { fileURLToPath } from 'node:url'
import { isChatTextLocalized, localeKeys, LOCALE_TABLES, normalizeLocale, t } from './t.ts'

const dir = dirname(fileURLToPath(import.meta.url))

test('H14: JSON catalogs are the t() source and share the same keys', () => {
  const zh = JSON.parse(readFileSync(join(dir, 'locales/zh-CN.json'), 'utf8')) as Record<string, string>
  const en = JSON.parse(readFileSync(join(dir, 'locales/en.json'), 'utf8')) as Record<string, string>
  assert.deepEqual(Object.keys(zh).sort(), Object.keys(en).sort())
  assert.deepEqual(LOCALE_TABLES['zh-CN'], zh)
  assert.deepEqual(LOCALE_TABLES.en, en)
  assert.ok(localeKeys().length >= 80)
})

test('H14: locale normalize and static strings switch; chat reply unchanged', () => {
  assert.equal(normalizeLocale('zh-Hans-CN'), 'zh-CN')
  assert.equal(normalizeLocale('en-US'), 'en')
  assert.equal(normalizeLocale('fr-FR'), 'zh-CN')
  assert.equal(t('zh-CN', 'settings'), '设置')
  assert.equal(t('en', 'settings'), 'Settings')
  assert.equal(t('en', 'skills'), 'Skills')
  assert.equal(t('zh-CN', 'connectionFailed', { error: 'timeout' }), 'appserver 连接失败：timeout')
  assert.equal(isChatTextLocalized('en', '你好世界'), '你好世界')
  assert.equal(isChatTextLocalized('zh-CN', 'hello from the model'), 'hello from the model')
})

test('H14: GX22 chrome keys exist in both locales and never rewrite chat', () => {
  const required = [
    'settings',
    'skills',
    'tasks',
    'recycle',
    'general',
    'appearance',
    'models',
    'addModel',
    'mcp',
    'team',
    'pinned',
    'projects',
    'recent',
    'languageHint'
  ]
  for (const key of required) {
    assert.notEqual(t('zh-CN', key), key)
    assert.notEqual(t('en', key), key)
  }
})
