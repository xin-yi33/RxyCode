import assert from 'node:assert/strict'
import { test } from 'node:test'
import {
  CREATE_TEAM_PROMPT,
  examplePromptsFromExtra,
  firstTeamIdInGroup,
  leaderFirstMembers,
  mapTeamGroups,
  mapTeamListItem
} from './team.model.ts'

test('maps team/list extra onto a WorkBuddy detail card: leader first, stages, example prompts', () => {
  const team = mapTeamListItem({
    id: 'software_dev',
    display_name: '软件研发团',
    summary: '10 位角色 · 7 阶段',
    description: '结构化分工',
    group: 'builtin',
    extra: {
      'ecosystem.category': '技术工程',
      'ecosystem.example_prompts': ['试试这样问我：拆这个需求']
    },
    members: [
      { role: 'coder', display_name: '编码员', extra: {} },
      { role: 'pm', display_name: '主理人', extra: { 'ecosystem.is_leader': true } }
    ],
    stages: [
      { name: 'clarify', role: 'pm' },
      { name: 'implement', role: 'coder' }
    ]
  })
  assert.equal(team.id, 'software_dev')
  assert.equal(team.members?.[0]?.role, 'pm')
  assert.equal(team.members?.[0]?.isLeader, true)
  assert.equal(team.stages?.[1]?.name, 'implement')
  assert.deepEqual(team.examplePrompts, ['试试这样问我：拆这个需求'])
  assert.deepEqual(examplePromptsFromExtra({}), [])
})

test('leaderFirst keeps a single leader at the front and leaves extra missing as-is', () => {
  const ordered = leaderFirstMembers([
    { role: 'coder', displayName: '编码员', isLeader: false },
    { role: 'pm', displayName: '主理人', isLeader: true }
  ])
  assert.deepEqual(
    ordered.map((item) => item.role),
    ['pm', 'coder']
  )
  const mapped = mapTeamListItem({ id: 'plain', display_name: 'plain' })
  assert.equal(mapped.members?.length ?? 0, 0)
  assert.deepEqual(mapped.examplePrompts ?? [], [])
})

test('mapTeamGroups keeps builtin flag; firstTeamIdInGroup picks a member team', () => {
  const groups = mapTeamGroups([
    { id: 'builtin', members: ['software_dev'], builtin: true },
    { id: 'other', members: [], builtin: false }
  ])
  assert.equal(groups[0]?.builtin, true)
  assert.equal(groups[0]?.name, 'builtin')
  assert.equal(
    firstTeamIdInGroup(
      [{ id: 'software_dev', name: '软件研发团', groupId: 'builtin' }],
      'builtin'
    ),
    'software_dev'
  )
})

test('conversational create prompt names team.yaml, roles, and team_install', () => {
  assert.match(CREATE_TEAM_PROMPT, /team\.yaml/)
  assert.match(CREATE_TEAM_PROMPT, /团长居首/)
  assert.match(CREATE_TEAM_PROMPT, /team_install/)
  assert.match(CREATE_TEAM_PROMPT, /~\/\.RxyCode\/teams/)
}
)