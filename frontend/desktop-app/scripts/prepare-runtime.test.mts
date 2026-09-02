import test from 'node:test'
import assert from 'node:assert/strict'
import { mkdtempSync, mkdirSync, readFileSync, rmSync, writeFileSync, existsSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import {
  keepPythonFile,
  keepVendoredFile,
  rewritePosixConsoleScript,
  rewriteWindowsLauncherShebang,
  scriptContainsBuildMachinePath,
  windowsVersionedDllName,
  writeRelocatableRxycodeLaunchers
} from './prepare-runtime.mts'

function win(src: string): boolean {
  return keepPythonFile('C:/Python', src, 'win32', false)
}

function posix(src: string): boolean {
  return keepPythonFile('/opt/python', src, 'darwin', false)
}

function linux(src: string): boolean {
  return keepPythonFile('/opt/python', src, 'linux', false)
}

function winDir(src: string): boolean {
  return keepPythonFile('C:/Python', src, 'win32', true)
}

function posixDir(src: string): boolean {
  return keepPythonFile('/opt/python', src, 'darwin', true)
}
test('win32 keeps interpreter + stdlib, drops debug/Docs/test', () => {
  assert.equal(win('C:/Python/python.exe'), true)
  assert.equal(win('C:/Python/pythonw.exe'), true)
  assert.equal(win('C:/Python/python3.dll'), true)
  assert.equal(win('C:/Python/python312.dll'), true)
  assert.equal(win('C:/Python/python313.dll'), true)
  assert.equal(win('C:/Python/python314.dll'), true)
  assert.equal(win('C:/Python/vcruntime140.dll'), true)
  assert.equal(win('C:/Python/python_d.exe'), false) // debug interpreter dropped
  assert.equal(win('C:/Python/Lib/site-packages/pydantic'), true)
  assert.equal(win('C:/Python/Lib/test'), false)
  assert.equal(win('C:/Python/Lib/site-packages/pytest'), false)
  assert.equal(win('C:/Python/Lib/site-packages/scipy'), false)
  assert.equal(win('C:/Python/Doc'), false)
})

test('win32 filters pip and rxycode dist-info by dynamic version', () => {
  assert.equal(win('C:/Python/Scripts/pip.exe'), true)
  assert.equal(win('C:/Python/Scripts/pip3.12.exe'), true)
  assert.equal(win('C:/Python/Scripts/frobnicate.exe'), false)
  assert.equal(win('C:/Python/Lib/site-packages/rxycode-1.3.0.dist-info'), false)
  assert.equal(win('C:/Python/Lib/site-packages/rxycode-1.2.6.dist-info'), false)
})

test('win32 drops host RxyCode installs so junctions cannot break staging', () => {
  assert.equal(win('C:/Python/Lib/site-packages/RxyCode'), false)
  assert.equal(winDir('C:/Python/Lib/site-packages/RxyCode'), false)
  assert.equal(winDir('C:/Python/Lib/site-packages/RxyCode.old-broken-install'), false)
  assert.equal(winDir('C:/Python/Lib/site-packages/pydantic'), true)
})

test('POSIX keeps bin/python3 + lib/pythonX.Y stdlib, drops pip wrappers beyond pip3', () => {
  assert.equal(posix('/opt/python/bin/python3'), true)
  assert.equal(posix('/opt/python/bin/python3.14'), true)
  assert.equal(posix('/opt/python/bin/pip3'), true)
  assert.equal(posix('/opt/python/bin/frobnicate'), false)
  assert.equal(posix('/opt/python/lib/libpython3.14.so'), true)
  assert.equal(posix('/opt/python/lib/libpython3.14.dylib'), true)
  assert.equal(posix('/opt/python/lib/pkgconfig'), true)
  assert.equal(posix('/opt/python/lib/python3.14/site-packages/pydantic'), true)
  assert.equal(posix('/opt/python/lib/python3.14/site-packages/pytest'), false)
  assert.equal(posix('/opt/python/lib/python3.14/test'), false)
  assert.equal(posix('/opt/python/Doc'), false)
})

test('linux uses the same POSIX layout', () => {
  assert.equal(linux('/opt/python/bin/python3'), true)
  assert.equal(linux('/opt/python/lib/libpython3.13.so.1.0'), true)
  assert.equal(linux('/opt/python/lib/python3.13/site-packages/pydantic'), true)
  assert.equal(linux('/opt/python/lib/python3.13/site-packages/ruff'), false)
})

test('directory roots (bin/lib/Lib/DLLs) are always traversed', () => {
  // A directory that merely carries python executables must not be pruned
  // by the file-level name rules (this was the mac/linux ENOENT root cause).
  assert.equal(posixDir('/opt/python/bin'), true)
  assert.equal(posixDir('/opt/python/lib'), true)
  assert.equal(posixDir('/opt/python/lib/python3.14'), true)
  assert.equal(posixDir('/opt/python/lib/python3.14/site-packages'), true)
  assert.equal(winDir('C:/Python/Lib'), true)
  assert.equal(winDir('C:/Python/DLLs'), true)
  assert.equal(winDir('C:/Python/Scripts'), true)
  // Pruned subtrees stay pruned even as directories.
  assert.equal(posixDir('/opt/python/lib/python3.14/test'), false)
  assert.equal(winDir('C:/Python/Lib/site-packages/pytest'), false)
})

test('rewritePosixConsoleScript replaces CI shebangs with a relocatable wrapper', () => {
  const ci =
    '#!/home/runner/work/RxyCode/RxyCode/frontend/desktop-app/build/runtime/linux-x64/python/bin/python3\n' +
    'import sys\nfrom RxyCode.RxyCode1_1_0.entrypoint import main\n'
  const rewritten = rewritePosixConsoleScript(ci)
  assert.equal(scriptContainsBuildMachinePath(rewritten), false)
  assert.match(rewritten, /realpath/)
  assert.match(rewritten, /from RxyCode\.RxyCode1_1_0\.entrypoint import main/)
  const already =
    '#!/bin/sh\n\'\'\'exec\' "$(dirname -- "$(realpath -- "$0")")/python3.12" "$0" "$@"\n\' \'\'\'\n'
  assert.equal(rewritePosixConsoleScript(already), already)
})

test('rewriteWindowsLauncherShebang replaces the CI python.exe path in place', () => {
  const shebang = '#!D:\\a\\RxyCode\\RxyCode\\frontend\\desktop-app\\build\\runtime\\win32-x64\\python\\python.exe'
  const payload = Buffer.from(`MZ....${shebang}\nfrom RxyCode.RxyCode1_1_0.entrypoint import main\n`, 'latin1')
  const rewritten = rewriteWindowsLauncherShebang(payload)
  assert.equal(rewritten.length, payload.length)
  const text = rewritten.toString('latin1')
  assert.equal(scriptContainsBuildMachinePath(text), false)
  assert.match(text, /#!python\.exe/)
  assert.match(text, /from RxyCode\.RxyCode1_1_0\.entrypoint import main/)
})

test('windowsVersionedDllName maps CPython X.Y to pythonXY.dll', () => {
  assert.equal(windowsVersionedDllName('3.12.10'), 'python312.dll')
  assert.equal(windowsVersionedDllName('Python 3.12.10'), 'python312.dll')
  assert.equal(windowsVersionedDllName('3.14.2'), 'python314.dll')
  assert.equal(windowsVersionedDllName('not-a-version'), null)
})

test('writeRelocatableRxycodeLaunchers replaces hardcoded Windows exe', () => {
  const root = mkdtempSync(join(tmpdir(), 'rxycode-runtime-'))
  try {
    const scripts = join(root, 'Scripts')
    mkdirSync(scripts, { recursive: true })
    writeFileSync(join(scripts, 'rxycode.exe'), 'fake-ci-launcher')
    writeRelocatableRxycodeLaunchers(root, 'win32')
    assert.equal(existsSync(join(scripts, 'rxycode.exe')), false)
    const cmd = readFileSync(join(scripts, 'rxycode.cmd'), 'utf8')
    assert.match(cmd, /%~dp0\.\.\\python\.exe/)
    assert.match(cmd, /-m RxyCode/)
    assert.doesNotMatch(cmd, /D:\\a\\/)
  } finally {
    rmSync(root, { recursive: true, force: true })
  }
})

test('vendored app tree keeps appserver and drops repo junk', () => {
  const keep = (src: string): boolean => keepVendoredFile('C:/repo', src, true)
  assert.equal(keep('C:/repo/appserver/__main__.py'), true)
  assert.equal(keep('C:/repo/core/agent_v2.py'), true)
  assert.equal(keep('C:/repo/LICENSE'), true)
  assert.equal(keep('C:/repo/.github/workflows/ci.yml'), false)
  assert.equal(keep('C:/repo/evals/run.py'), false)
  assert.equal(keep('C:/repo/AGENTS.md'), false)
  assert.equal(keep('C:/repo/.coveragerc'), false)
  assert.equal(keep('C:/repo/scripts/test_phase1.py'), false)
  assert.equal(keep('C:/repo/pytest.ini'), false)
  assert.equal(keep('C:/repo/frontend/opentui-app/package.json'), false)
  assert.equal(keep('C:/repo/frontend/desktop-app/package.json'), false)
  assert.equal(keep('C:/repo/__pycache__/x.pyc'), false)
})
