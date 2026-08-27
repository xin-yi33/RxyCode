import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { test } from 'node:test'
import { fileURLToPath } from 'node:url'
import { CliGallery } from './CliGallery.ts'
import { probeCli } from './cli.probe.ts'

const schema = readFileSync(
  join(dirname(fileURLToPath(import.meta.url)), '../../../../../protocol/schema.json'),
  'utf8'
)

test('GX25: cli/* is path A; gallery still reuses H19 PreviewGallery', () => {
  const probe = probeCli(schema)
  assert.equal(probe.path, 'A')
  assert.ok(probe.present.includes('cli/list'))
  const html = renderToStaticMarkup(
    createElement(CliGallery, { blocked: false, missing: [], artifacts: [] })
  )
  assert.match(html, /data-testid="cli-gallery"/)
})
