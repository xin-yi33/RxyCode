import assert from 'node:assert/strict'
import { test } from 'node:test'
import { isChatTextLocalized, normalizeLocale, t } from './t.ts'

test('H14: locale normalize and static strings switch; chat reply unchanged', () => {
  assert.equal(normalizeLocale('zh-Hans-CN'), 'zh-CN')
  assert.equal(normalizeLocale('en-US'), 'en')
  assert.equal(normalizeLocale('fr-FR'), 'zh-CN')
  assert.equal(t('zh-CN', 'settings'), '设置')
  assert.equal(t('en', 'settings'), 'Settings')
  assert.equal(t('en', 'skills'), 'Skills')
  assert.equal(isChatTextLocalized('en', '你好世界'), '你好世界')
})
