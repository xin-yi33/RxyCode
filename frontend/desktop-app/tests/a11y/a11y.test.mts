import assert from 'node:assert/strict'
import { test } from 'node:test'
import { colors, themes } from '../../src/ui/tokens.ts'
import { dedupeNotices } from '../../src/features/notifications/notify.ts'
import { projectRecovery } from '../../src/features/recovery/recoveryProjection.ts'

test('H12: risk is not color-only; themes include high-contrast', () => {
  assert.ok(colors.risk.text.length > 0)
  assert.ok(colors.risk.icon.length > 0)
  assert.ok(themes.includes('high-contrast'))
})

test('H12: notices dedupe; recovery_required is projected', () => {
  const first = dedupeNotices([], { id: 'n1', kind: 'failure', title: 'x', body: 'y' })
  const second = dedupeNotices(first, { id: 'n1', kind: 'failure', title: 'x', body: 'y' })
  assert.equal(second.length, 1)
  assert.equal(projectRecovery('recovery_required'), 'recovery_required')
})
