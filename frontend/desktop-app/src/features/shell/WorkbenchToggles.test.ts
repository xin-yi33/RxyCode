import assert from 'node:assert/strict'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { test } from 'node:test'
import { BottomTerminal, RightPanelMenu, TerminalPane, WorkbenchToggles, terminalTabTitle } from './WorkbenchToggles.ts'

test('top-right toggles only open the right and bottom panels', () => {
  const html = renderToStaticMarkup(
    createElement(WorkbenchToggles, {
      rightOpen: false,
      bottomOpen: false,
      onToggleRight: () => undefined,
      onToggleBottom: () => undefined
    })
  )
  assert.match(html, /data-testid="toggle-right-panel"/)
  assert.match(html, /data-testid="toggle-bottom-panel"/)
  assert.doesNotMatch(html, /data-testid="right-panel-review"/)
  assert.doesNotMatch(html, /data-testid="right-panel-menu"/)
  assert.match(html, /Ctrl\+Alt\+B/)
  assert.match(html, /Ctrl\+J/)
})

test('right panel menu is a centered Codex launcher with shortcuts', () => {
  const html = renderToStaticMarkup(createElement(RightPanelMenu, { onChange: () => undefined }))
  assert.match(html, /class="right-panel-menu"/)
  assert.match(html, /审查/)
  assert.match(html, /终端/)
  assert.match(html, /浏览器/)
  assert.match(html, /文件/)
  assert.match(html, /侧边聊天/)
  assert.match(html, /Ctrl\+Shift\+G/)
  assert.match(html, /Ctrl\+`/)
  assert.match(html, /Ctrl\+T/)
  assert.match(html, /Ctrl\+P/)
  assert.match(html, /Ctrl\+Alt\+S/)
  assert.match(html, /<kbd>/)
  assert.match(html, /data-testid="right-panel-review"/)
  assert.match(html, /data-testid="right-panel-browser"/)
  assert.match(html, /data-testid="right-panel-files"/)
})

test('bottom terminal copies Codex tab chrome', () => {
  const html = renderToStaticMarkup(
    createElement(BottomTerminal, { cwd: 'C:\\Users\\Administrator\\Documents\\论文', onClose: () => undefined })
  )
  assert.match(html, /data-testid="bottom-terminal"/)
  assert.match(html, /管理员: C:\\Users\\Admin\.\.\./)
  assert.match(html, /data-testid="bottom-terminal-add"/)
  assert.match(html, /data-testid="bottom-terminal-close"/)
  assert.match(html, /Windows PowerShell/)
  assert.match(html, /PS C:\\Users\\Administrator\\Documents\\论文(&gt;|>)/)
  assert.equal(terminalTabTitle('C:\\Windowns-long-path-name'), '管理员: C:\\Windowns-lo...')
})

test('right terminal pane is independent of the bottom panel height', () => {
  const html = renderToStaticMarkup(createElement(TerminalPane))
  assert.match(html, /data-testid="right-view-terminal"/)
  assert.match(html, /data-testid="right-terminal-body"/)
  assert.doesNotMatch(html, /class="bottom-terminal"/)
})
