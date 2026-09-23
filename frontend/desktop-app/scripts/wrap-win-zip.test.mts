import test from 'node:test'
import assert from 'node:assert/strict'
import { spawnSync } from 'node:child_process'
import { mkdtempSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { createRequire } from 'node:module'

const require = createRequire(import.meta.url)
const { wrapWindowsZip, wrapperNameFromZip } = require('./wrap-win-zip.cjs') as {
  wrapWindowsZip: (zipPath: string, python?: string) => string
  wrapperNameFromZip: (zipPath: string) => string
}

test('wrapperNameFromZip strips the .zip suffix', () => {
  assert.equal(
    wrapperNameFromZip('C:/out/RxyCode.Desktop-1.3.0-win.zip'),
    'RxyCode.Desktop-1.3.0-win'
  )
})

test('wrapWindowsZip prefixes a flat archive and is idempotent', () => {
  const dir = mkdtempSync(join(tmpdir(), 'rxycode-wrap-zip-'))
  const zipPath = join(dir, 'RxyCode.Desktop-1.3.0-win.zip')
  const python = process.platform === 'win32' ? 'python' : 'python3'
  const makeFlat = spawnSync(
    python,
    [
      '-c',
      'import zipfile, sys\n'
        + 'z=zipfile.ZipFile(sys.argv[1],"w")\n'
        + 'z.writestr("rxycode-desktop.exe", b"exe")\n'
        + 'z.writestr("resources/runtime/win32-x64/python/python312.dll", b"dll")\n'
        + 'z.close()\n',
      zipPath
    ],
    { encoding: 'utf8' }
  )
  assert.equal(makeFlat.status, 0, makeFlat.stderr)

  try {
    const wrapper = wrapWindowsZip(zipPath, python)
    assert.equal(wrapper, 'RxyCode.Desktop-1.3.0-win')
    const listed = spawnSync(
      python,
      [
        '-c',
        'import zipfile, sys\n'
          + 'print("\\n".join(zipfile.ZipFile(sys.argv[1]).namelist()))\n',
        zipPath
      ],
      { encoding: 'utf8' }
    )
    assert.equal(listed.status, 0, listed.stderr)
    const names = listed.stdout.trim().split(/\r?\n/)
    assert.ok(names.every((name) => name.startsWith('RxyCode.Desktop-1.3.0-win/')))
    assert.ok(names.includes('RxyCode.Desktop-1.3.0-win/rxycode-desktop.exe'))

    wrapWindowsZip(zipPath, python)
    const again = spawnSync(
      python,
      [
        '-c',
        'import zipfile, sys\n'
          + 'print("\\n".join(zipfile.ZipFile(sys.argv[1]).namelist()))\n',
        zipPath
      ],
      { encoding: 'utf8' }
    )
    assert.ok(
      again.stdout
        .trim()
        .split(/\r?\n/)
        .every((name) => name.startsWith('RxyCode.Desktop-1.3.0-win/'))
    )
    assert.ok(!again.stdout.includes('RxyCode.Desktop-1.3.0-win/RxyCode.Desktop-1.3.0-win/'))
  } finally {
    rmSync(dir, { recursive: true, force: true })
  }
})
