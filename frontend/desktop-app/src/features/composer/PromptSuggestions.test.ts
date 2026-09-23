import assert from 'node:assert/strict'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { test } from 'node:test'
import { PromptSuggestions } from './PromptSuggestions.ts'
import {
  applySuggestionKey,
  suggestionsFromGitLog,
  suggestionsFromRecentMessages,
  suggestionsVisible
} from './suggestions.ts'

test('GX12: git subject only, no LLM, hide after 5 user messages', () => {
  assert.deepEqual(suggestionsFromGitLog(['abc1234 fix login', 'def hide email']), ['fix login', 'hide email'])
  assert.deepEqual(suggestionsFromRecentMessages(['please review the board']), [
    'Continue please',
    'Explain please'
  ])
  assert.equal(suggestionsVisible(0, false), false)
  assert.equal(suggestionsVisible(1, true), true)
  assert.equal(suggestionsVisible(5, true), false)
  assert.equal(applySuggestionKey('Tab'), 'accept')
  assert.equal(applySuggestionKey('Escape'), 'dismiss')
})

test('GX12: suggestion chrome', () => {
  const html = renderToStaticMarkup(
    createElement(PromptSuggestions, {
      items: ['fix login'],
      visible: true,
      onPick: () => undefined
    })
  )
  assert.match(html, /fix login/)
})
