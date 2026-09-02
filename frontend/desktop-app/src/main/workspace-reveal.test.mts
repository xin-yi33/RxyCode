import assert from 'node:assert/strict'
import { test } from 'node:test'
import { revealDirectory } from './workspace-reveal.ts'

test('revealDirectory opens a folder path and rejects blanks', async () => {
  const opened: string[] = []
  const opener = {
    openPath: async (target: string): Promise<string> => {
      opened.push(target)
      return ''
    }
  }
  assert.equal(await revealDirectory(opener, 'D:\\agent-demo\\RxyCode-phase-g-integrate'), true)
  assert.deepEqual(opened, ['D:\\agent-demo\\RxyCode-phase-g-integrate'])
  assert.equal(await revealDirectory(opener, '   '), false)
})
