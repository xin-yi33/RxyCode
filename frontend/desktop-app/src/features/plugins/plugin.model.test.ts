import assert from 'node:assert/strict'
import { test } from 'node:test'
import { parsePluginList } from './plugin.model.ts'
import { parseSkillSearch, skillPortraitSrc } from '../skills/skill.model.ts'

test('parsePluginList does not invent plugins', () => {
  assert.deepEqual(parsePluginList({}), [])
  const rows = parsePluginList({
    plugins: [{ name: 'github', version: '1.0.0', enabled: true, source: 'url', path: '/p' }]
  })
  assert.equal(rows[0]?.name, 'github')
})

test('parseSkillSearch keeps stars and does not invent rows', () => {
  assert.deepEqual(parseSkillSearch({}, new Set()), [])
  const rows = parseSkillSearch(
    {
      skills: [
        { name: 'tdd', repo: 'mxyhi/ok-skills', stars: 12, description: 'tests', scope: 'engineering' }
      ]
    },
    new Set(['tdd'])
  )
  assert.equal(rows[0]?.stars, 12)
  assert.equal(rows[0]?.installed, true)
  assert.match(skillPortraitSrc('tdd'), /skill-debug/)
})
