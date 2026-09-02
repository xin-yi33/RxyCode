#!/usr/bin/env node
/**
 * Phase4-D6 runtime staging.
 *
 * Builds a self-contained Python runtime + vendored RxyCode source under
 * build/runtime/<platform>-<arch>/, which electron-builder copies into the
 * packaged app as resources/runtime/ (extraResources).
 *
 * Self-contained means the packaged app must not depend on the dev
 * machine's ../RxyCode-master checkout or a system python: the staged
 * runtime carries its own interpreter, its own site-packages and a
 * vendored copy of the RxyCode source tree. RxyCode-master is only READ.
 *
 * The RxyCode version is read from pyproject.toml at staging time (no
 * hard-coded pin), so a 1.3.0 tag bundles 1.3.0 automatically.
 */
import { spawnSync } from 'node:child_process'
import {
  copyFileSync,
  cpSync,
  existsSync,
  lstatSync,
  mkdirSync,
  readFileSync,
  readdirSync,
  readlinkSync,
  rmSync,
  statSync,
  writeFileSync
} from 'node:fs'
import { basename, dirname, join, relative, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

function fail(message: string): never {
  console.error(`RUNTIME_PREPARE_FAIL ${message}`)
  process.exit(1)
}

function pythonRelExe(platform: string): string {
  return platform === 'win32' ? 'python.exe' : join('bin', 'python3')
}

function argValue(argv: string[], name: string): string | null {
  const index = argv.indexOf(`--${name}`)
  return index >= 0 && argv[index + 1] !== undefined ? argv[index + 1] : null
}

export function windowsVersionedDllName(pythonVersion: string): string | null {
  // "3.12.10" / "Python 3.12.10" -> python312.dll. The unversioned
  // python3.dll stub cannot start CPython without this sibling DLL.
  const match = /(\d+)\.(\d+)/.exec(pythonVersion)
  if (match === null) return null
  return `python${match[1]}${match[2]}.dll`
}

function runPython(pythonExe: string, args: string[], cwd?: string): string {
  const result = spawnSync(pythonExe, args, {
    cwd,
    encoding: 'utf8',
    timeout: 120_000,
    env: {
      ...process.env,
      PYTHONDONTWRITEBYTECODE: '1'
    }
  })
  if (result.status !== 0) {
    fail(`python ${args.join(' ')} failed (status ${String(result.status)}): ${result.stderr}`)
  }
  return result.stdout.trim()
}

function keepPythonFile(
  pythonRoot: string,
  src: string,
  platform: string,
  isDirectory: boolean
): boolean {
  if (src === pythonRoot) return true
  // Split on both separators so layout checks work identically on every OS.
  const parts = relative(pythonRoot, src).split(/[\\/]/)
  const name = basename(src)
  if (name === '__pycache__' || name.endsWith('.pyc') || name.endsWith('.pdb')) return false
  if (name === 'include' || name === 'share' || name === 'Doc' || name === 'docs') return false
  const top = parts[0]
  // Directories are kept unless they are a known non-runtime subtree; only
  // files get the precise name-based filtering. This matters for the POSIX
  // bin/ and lib/ roots, whose directory names never match the file rules.
  if (isDirectory) {
    if (top === 'test' || name === 'test' || name === 'tests' || name === 'idlelib') return false
    if (name === 'site-packages') {
      // Keep the directory itself; per-package pruning happens on children.
      return true
    }
    if (parts.includes('site-packages')) {
      return keepSitePackages(parts, name)
    }
    if (top === 'bin' || top === 'lib' || top === 'DLLs' || top === 'Lib' || top === 'Scripts') {
      return true
    }
    return true
  }
  // Windows layout: DLLs / Lib / Scripts / python*.dll.
  if (platform === 'win32') {
    if (top === 'Doc' || top === 'include' || top === 'libs' || top === 'share') return false
    if (top === 'DLLs') return !/_d\.pyd$/.test(name) && !/_t\.pyd$/.test(name)
    if (top === 'Lib') return keepStdLib(parts, name)
    if (top === 'Scripts') return /^pip(3(\.\d+)?)?\.exe$/.test(name)
    if (parts.length === 1) {
      return (
        name === 'python.exe' ||
        name === 'pythonw.exe' ||
        // python3.dll (stub) + python3XY.dll (3.12, 3.13, 3.14, …)
        /^python3\d*\.dll$/i.test(name) ||
        name.startsWith('vcruntime140') ||
        name === 'LICENSE.txt'
      )
    }
    return true
  }
  // POSIX layout (macOS / Linux): bin / lib / lib/pythonX.Y / share.
  if (top === 'Doc' || top === 'include' || top === 'libs' || top === 'share') return false
  if (top === 'bin') {
    return (
      name === 'python3' ||
      name === 'python3.12' ||
      name === 'python3.13' ||
      name === 'python3.14' ||
      name.startsWith('pip3')
    )
  }
  if (top === 'lib') {
    const second = parts[1]
    if (second && second.startsWith('python')) {
      const third = parts[2]
      if (third === 'site-packages') return keepSitePackages(parts, name)
      // Keep stdlib modules but prune tests/docs/caches.
      if (third === 'test' || third === 'idlelib' || third === 'turtledemo') {
        return false
      }
      return true
    }
    // libpython*.so / libpython*.dylib and pkgconfig live here.
    return /^libpython/.test(name) || name === 'pkgconfig'
  }
  return true
}

function keepStdLib(parts: string[], name: string): boolean {
  const second = parts[1]
  if (second === 'test' || second === 'idlelib' || second === 'turtledemo') {
    return false
  }
  if (second === 'site-packages') return keepSitePackages(parts, name)
  return true
}

function keepSitePackages(parts: string[], name: string): boolean {
  // parts is the full relative path; find the entry right after "site-packages"
  // so the same logic works for Lib\site-packages\X and lib/pythonX.Y/site-packages/X.
  const spIdx = parts.indexOf('site-packages')
  const pkgName = spIdx >= 0 && parts[spIdx + 1] !== undefined ? parts[spIdx + 1] : name
  if (
    ['scipy', 'pandas', 'matplotlib', 'coverage', 'pytest', '_pytest', 'ruff'].includes(pkgName)
  ) {
    return false
  }
  if (/^rxycode/i.test(pkgName)) return false
  if (name.endsWith('.dist-info') && /^rxycode-/.test(name)) return false
  if (name.startsWith('__editable__')) return false
  return true
}

export function writeRelocatableRxycodeLaunchers(pythonRoot: string, platform: string): void {
  // pip's Windows .exe launchers embed the build-machine python path
  // (e.g. D:\a\RxyCode\...\python.exe). After the runtime is copied into a
  // portable zip those launchers exit 1 with no output. Replace them with
  // wrappers that resolve python next to the script.
  if (platform === 'win32') {
    const scripts = join(pythonRoot, 'Scripts')
    mkdirSync(scripts, { recursive: true })
    writeFileSync(
      join(scripts, 'rxycode.cmd'),
      '@echo off\r\n' +
        'setlocal\r\n' +
        'set "PY=%~dp0..\\python.exe"\r\n' +
        'if not exist "%PY%" set "PY=%~dp0python.exe"\r\n' +
        '"%PY%" -m RxyCode %*\r\n'
    )
    for (const name of ['rxycode.exe', 'rxycode-script.py']) {
      const stale = join(scripts, name)
      if (existsSync(stale)) rmSync(stale, { force: true })
    }
    return
  }
  const bin = join(pythonRoot, 'bin')
  mkdirSync(bin, { recursive: true })
  writeFileSync(
    join(bin, 'rxycode'),
    '#!/bin/sh\n' +
      'DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)\n' +
      'if [ -x "$DIR/python3" ]; then exec "$DIR/python3" -m RxyCode "$@"\n' +
      'elif [ -x "$DIR/../bin/python3" ]; then exec "$DIR/../bin/python3" -m RxyCode "$@"\n' +
      'else exec python3 -m RxyCode "$@"\n' +
      'fi\n',
    { mode: 0o755 }
  )
}

const BUILD_MACHINE_PATH_RE =
  /(?:\/home\/runner\/|\/Users\/runner\/|[A-Za-z]:\\a\\)/i

const POSIX_RELOCATABLE_SHEBANG =
  '#!/bin/sh\n' +
  '\'\'\'exec\' "$(dirname -- "$(realpath -- "$0")")/python3" "$0" "$@"\n' +
  '\' \'\'\'\n'

export function posixRelocatableShebang(): string {
  return POSIX_RELOCATABLE_SHEBANG
}

export function scriptContainsBuildMachinePath(text: string): boolean {
  return BUILD_MACHINE_PATH_RE.test(text)
}

export function rewritePosixConsoleScript(text: string): string {
  if (!text.startsWith('#!')) return text
  const newline = text.indexOf('\n')
  const first = newline === -1 ? text : text.slice(0, newline)
  if (!/python/i.test(first)) return text
  if (first.includes('realpath') && first.includes('dirname')) return text
  const rest = newline === -1 ? '' : text.slice(newline + 1)
  return POSIX_RELOCATABLE_SHEBANG + rest
}

export function rewriteWindowsLauncherShebang(buffer: Buffer): Buffer {
  const text = buffer.toString('latin1')
  const match = /#![^\r\n]*python(?:w)?\.exe/i.exec(text)
  if (match === null) return buffer
  const old = match[0]
  if (/^#!python(?:w)?\.exe$/i.test(old.trim()) && !scriptContainsBuildMachinePath(old)) {
    return buffer
  }
  const replacement = '#!python.exe'.padEnd(old.length, ' ')
  const out = Buffer.from(buffer)
  out.write(replacement, match.index, replacement.length, 'latin1')
  return out
}

function rewriteStagedConsoleScripts(pythonDir: string, platform: string): void {
  const scriptDir = platform === 'win32' ? join(pythonDir, 'Scripts') : join(pythonDir, 'bin')
  if (!existsSync(scriptDir)) return
  for (const name of readdirSync(scriptDir)) {
    const full = join(scriptDir, name)
    const stat = lstatSync(full)
    if (!stat.isFile()) continue
    if (platform === 'win32') {
      if (!name.toLowerCase().endsWith('.exe')) continue
      const rewritten = rewriteWindowsLauncherShebang(readFileSync(full))
      writeFileSync(full, rewritten)
      continue
    }
    if (/^python3(\.\d+)?$/.test(name)) continue
    const raw = readFileSync(full)
    if (raw[0] !== 0x23 || raw[1] !== 0x21) continue
    const text = raw.toString('utf8')
    const rewritten = rewritePosixConsoleScript(text)
    if (rewritten !== text) {
      writeFileSync(full, rewritten, { encoding: 'utf8', mode: stat.mode })
    }
  }
}

export { keepPythonFile, keepSitePackages, keepVendoredFile, rewriteStagedConsoleScripts }

/** Top-level repo entries that the packaged Desktop appserver actually needs. */
const VENDORED_TOP_LEVEL = new Set([
  'appserver',
  'cache',
  'config',
  'core',
  'execution',
  'history',
  'log',
  'lsp',
  'mcp',
  'memory',
  'planning',
  'protocol',
  'rag',
  'recovery',
  'scheduler',
  'synthesis',
  'tools',
  'utils',
  'validation',
  '_package_root',
  'api_server.py',
  'api_server_models.py',
  'api_server_stream.py',
  'entrypoint.py',
  'main.py',
  '__init__.py',
  '__main__.py',
  'LICENSE',
  'requirements.txt'
])

function keepVendoredFile(repo: string, src: string, isDirectory: boolean): boolean {
  void isDirectory // signature parity with keepPythonFile
  if (src === repo) return true
  const parts = relative(repo, src).split(/[\\/]/)
  const name = basename(src)
  if (name === '__pycache__' || name.endsWith('.pyc')) return false
  const top = parts[0]
  if (!VENDORED_TOP_LEVEL.has(top)) return false
  if (top === 'log' && (name.endsWith('.out') || name === 'status.json' || name.endsWith('.log'))) {
    return false
  }
  return true
}

function stripBytecode(root: string): void {
  const stack = [root]
  while (stack.length > 0) {
    const current = stack.pop() as string
    for (const name of readdirSync(current)) {
      const full = join(current, name)
      const stat = lstatSync(full)
      if (stat.isDirectory()) {
        if (name === '__pycache__') {
          rmSync(full, { recursive: true, force: true })
        } else {
          stack.push(full)
        }
      } else if (name.endsWith('.pyc')) {
        rmSync(full, { force: true })
      }
    }
  }
}

function dirSize(dir: string): number {
  let total = 0
  const stack = [dir]
  while (stack.length > 0) {
    const current = stack.pop() as string
    for (const name of readdirSync(current)) {
      const full = join(current, name)
      const stat = statSync(full)
      if (stat.isDirectory()) stack.push(full)
      else total += stat.size
    }
  }
  return total
}

// Manual recursive copy with a per-node keep filter.
//
// Node >= 24's fs.cpSync pre-validates that the destination is not inside
// the source tree and throws ERR_FS_CP_EINVAL before the `filter` runs. Our
// staging layout (repo -> repo/frontend/desktop-app/build/runtime/<plat>/app)
// is inherently nested, so we walk the tree ourselves and skip excluded
// paths explicitly. The keep predicates are shared with the unit tests.
//
// Symbolic links (macOS/Linux `bin/python3`, `lib/libpython*.dylib`, pip
// wrappers) are dereferenced and copied as real files: a staged runtime must
// be self-contained and must not keep a dangling pointer back to the build
// machine's interpreter.
function copyTree(
  srcRoot: string,
  dstRoot: string,
  keep: (src: string, isDirectory: boolean) => boolean
): void {
  const stack: Array<{ src: string; dst: string }> = [{ src: srcRoot, dst: dstRoot }]
  while (stack.length > 0) {
    const { src, dst } = stack.pop() as { src: string; dst: string }
    if (!keep(src, true)) continue
    mkdirSync(dst, { recursive: true })
    for (const name of readdirSync(src)) {
      const full = join(src, name)
      const target = join(dst, name)
      const stat = lstatSync(full)
      if (stat.isSymbolicLink()) {
        // Dereference: copy the link target's *content* as a real file. The
        // keep predicate was already applied to the link itself, and the
        // target may live outside pythonRoot (macOS setup-python links
        // bin/python3 to the framework), so do not re-filter the target.
        // Directory junctions cannot be copyFileSync'd; skip them. Host
        // RxyCode installs are already pruned by keepSitePackages.
        const resolved = resolve(src, readlinkSync(full))
        if (!existsSync(resolved)) continue
        const targetStat = lstatSync(resolved)
        if (targetStat.isDirectory()) {
          continue
        }
        if (keep(full, false)) {
          copyFileSync(resolved, target)
        }
      } else if (stat.isDirectory()) {
        stack.push({ src: full, dst: target })
      } else if (keep(full, false)) {
        cpSync(full, target)
      }
    }
  }
}

const argv = process.argv.slice(2)
const isMain = process.argv[1] === fileURLToPath(import.meta.url)

if (isMain) {
  await main(argv)
}

async function main(argv: string[]): Promise<void> {
  const platform = argValue(argv, 'platform') ?? process.platform
  const arch = argValue(argv, 'arch') ?? process.arch
  const appDir = resolve(dirname(fileURLToPath(import.meta.url)), '..')
  const outDir = resolve(
    argValue(argv, 'out') ?? join(appDir, 'build', 'runtime', `${platform}-${arch}`)
  )
  console.log(`RUNTIME_PREPARE_START platform=${platform} arch=${arch} out=${outDir}`)

  // 1) RxyCode source (read-only)
  const repo = resolve(
    argValue(argv, 'repo') ?? process.env.RXYCODE_REPO_DIR ?? join(appDir, '..', 'RxyCode-master')
  )
  if (!existsSync(join(repo, 'appserver', '__main__.py'))) {
    fail(`RxyCode source not found at ${repo} (appserver/__main__.py missing)`)
  }
  const pyproject = readFileSync(join(repo, 'pyproject.toml'), 'utf8')
  const versionMatch = pyproject.match(/^version\s*=\s*"([^"]+)"/m)
  if (versionMatch === null) {
    fail('unable to read rxycode version from pyproject.toml')
  }
  const rxycodeVersion = versionMatch[1]
  // No hard-coded version pin: the release pipeline guarantees pyproject's
  // version matches the tag; the runtime bundles whatever the checkout has.

  // 2) python source (full install). Probe the *base prefix* (sys.base_prefix)
  // instead of sys.executable's dirname so a venv/conda python still resolves
  // to its real stdlib + site-packages root for staging.
  //
  // macOS framework Pythons (setup-python installs /Library/Frameworks/...)
  // are not copyable: their bin/python3 is a symlink into the framework and
  // include/ is a symlinked directory, so staging fails with ENOTSUP. When no
  // explicit --python is given we prefer an astral python-build-standalone
  // install via uv, which is self-contained and layout-identical on POSIX.
  const explicitPython = argValue(argv, 'python')
  let pythonRoot: string
  if (explicitPython) {
    const probe = spawnSync(explicitPython, ['-c', 'import sys; print(sys.base_prefix)'], {
      encoding: 'utf8'
    })
    if (probe.status !== 0) {
      fail(`cannot resolve python: ${probe.stderr}`)
    }
    pythonRoot = probe.stdout.trim()
  } else if (platform === 'win32') {
    const probe = spawnSync('python', ['-c', 'import sys; print(sys.base_prefix)'], {
      encoding: 'utf8'
    })
    if (probe.status !== 0) {
      fail(`cannot resolve python: ${probe.stderr}`)
    }
    pythonRoot = probe.stdout.trim()
  } else {
    // POSIX: fetch a standalone CPython with uv so the staged runtime is
    // self-contained (no framework symlinks, no hard-coded sys.prefix).
    const uvProbe = spawnSync('uv', ['python', 'find'], { encoding: 'utf8' })
    if (uvProbe.status !== 0) {
      fail('uv is required to stage the POSIX runtime (install from https://astral.sh/uv)')
    }
    const uvInstall = spawnSync(
      'uv',
      [
        'python',
        'install',
        '--preview',
        'cpython-3.12',
        '--mirror',
        'https://github.com/astral-sh/python-build-standalone/releases/download'
      ],
      { encoding: 'utf8' }
    )
    if (uvInstall.status !== 0) {
      // fall back to a system python if uv's standalone fetch failed
      const probe = spawnSync('python3', ['-c', 'import sys; print(sys.base_prefix)'], {
        encoding: 'utf8'
      })
      if (probe.status !== 0) {
        fail(`cannot resolve python: ${probe.stderr}`)
      }
      pythonRoot = probe.stdout.trim()
    } else {
      const find = spawnSync('uv', ['python', 'find', '3.12'], { encoding: 'utf8' })
      if (find.status !== 0) {
        fail(`uv python find failed: ${find.stderr}`)
      }
      const resolved = find.stdout.trim()
      const probe = spawnSync(resolved, ['-c', 'import sys; print(sys.base_prefix)'], {
        encoding: 'utf8'
      })
      if (probe.status !== 0) {
        fail(`cannot resolve uv python: ${probe.stderr}`)
      }
      pythonRoot = probe.stdout.trim()
    }
  }
  if (platform === 'win32') {
    if (!existsSync(join(pythonRoot, 'python.exe')) || !existsSync(join(pythonRoot, 'Lib'))) {
      fail(`python at ${pythonRoot} is not a full install (python.exe + Lib required)`)
    }
  } else if (
    !existsSync(join(pythonRoot, 'bin', 'python3')) ||
    !existsSync(join(pythonRoot, 'lib'))
  ) {
    fail(`python at ${pythonRoot} is not a full install (bin/python3 + lib required)`)
  }

  // 3) stage copies
  rmSync(outDir, { recursive: true, force: true })
  mkdirSync(join(outDir, 'python'), { recursive: true })
  mkdirSync(join(outDir, 'app'), { recursive: true })
  copyTree(pythonRoot, join(outDir, 'python'), (src, isDir) =>
    keepPythonFile(pythonRoot, src, platform, isDir)
  )
  copyTree(repo, join(outDir, 'app'), (src, isDir) => keepVendoredFile(repo, src, isDir))

  // 4) install the vendored RxyCode package into the runtime's site-packages
  //    (offline: no deps, no build isolation, no index access). The packaged
  //    app then carries `RxyCode.RxyCode1_1_0.*` just like a pip install.
  const pythonExe = join(outDir, 'python', pythonRelExe(platform))
  const appDirStaged = join(outDir, 'app')

  // Diagnose the staged interpreter before invoking pip: a stale symlink or a
  // broken sys.prefix on macOS/Linux manifests as spawnSync status === null,
  // which otherwise gets reported as a bare "pip install failed".
  const probeStaged = spawnSync(pythonExe, ['-c', 'import sys; print(sys.prefix, sys.version)'], {
    cwd: outDir,
    encoding: 'utf8',
    timeout: 30_000
  })
  if (probeStaged.status !== 0) {
    fail(
      `staged python ${pythonExe} failed to run (status ${String(probeStaged.status)}, ` +
        `error ${String(probeStaged.error)}): ${probeStaged.stderr}${probeStaged.stdout}`
    )
  }

  // A standalone (uv) interpreter has no build backend, and a framework
  // python may not carry setuptools either. The rxycode install below uses
  // --no-build-isolation, so ensure setuptools+wheel exist in the staged
  // runtime first (network is available in CI; --no-index is only used for
  // the rxycode install itself).
  const backend = spawnSync(
    pythonExe,
    ['-m', 'pip', 'install', '--break-system-packages', 'setuptools', 'wheel'],
    {
      cwd: outDir,
      env: {
        ...process.env,
        PIP_DISABLE_PIP_VERSION_CHECK: '1',
        PYTHONNOUSERSITE: '1'
      },
      encoding: 'utf8',
      timeout: 120_000
    }
  )
  if (backend.status !== 0) {
    fail(
      `pip install setuptools/wheel into runtime failed (status ${String(backend.status)}, ` +
        `error ${String(backend.error)}): ${backend.stderr}${backend.stdout}`
    )
  }

  // The staged interpreter (esp. a uv standalone python) has an empty
  // site-packages; the runtime dependencies come from requirements.txt. The
  // desktop job already installs them into setup-python, but on mac/linux
  // the runtime uses a *different* interpreter, so install the deps into the
  // staged runtime itself (idempotent, network available in CI).
  const reqPath = join(repo, 'requirements.txt')
  if (existsSync(reqPath)) {
    const deps = spawnSync(
      pythonExe,
      ['-m', 'pip', 'install', '--break-system-packages', '-r', reqPath],
      {
        cwd: outDir,
        env: {
          ...process.env,
          PIP_DISABLE_PIP_VERSION_CHECK: '1',
          PYTHONNOUSERSITE: '1'
        },
        encoding: 'utf8',
        timeout: 600_000
      }
    )
    if (deps.status !== 0) {
      fail(
        `pip install requirements into runtime failed (status ${String(deps.status)}, ` +
          `error ${String(deps.error)}): ${deps.stderr}${deps.stdout}`
      )
    }
  }

  const pip = spawnSync(
    pythonExe,
    [
      '-m',
      'pip',
      'install',
      '--no-deps',
      '--no-build-isolation',
      '--disable-pip-version-check',
      '--break-system-packages',
      repo
    ],
    {
      cwd: outDir,
      env: {
        ...process.env,
        PIP_NO_INDEX: '1',
        PIP_DISABLE_PIP_VERSION_CHECK: '1',
        PYTHONNOUSERSITE: '1'
      },
      encoding: 'utf8',
      timeout: 300_000
    }
  )
  if (pip.status !== 0) {
    fail(
      `pip install rxycode into runtime failed (status ${String(pip.status)}, ` +
        `error ${String(pip.error)}): ${pip.stderr}${pip.stdout}`
    )
  }
  writeRelocatableRxycodeLaunchers(join(outDir, 'python'), platform)

  // pip writes absolute shebangs / Windows launcher paths that point at the
  // CI machine. Rewrite them so the portable zip / AppImage / dmg still
  // find the bundled interpreter after the archive is moved.
  rewriteStagedConsoleScripts(join(outDir, 'python'), platform)

  // 5) manifest + versions
  const pythonVersion = runPython(pythonExe, [
    '-c',
    'import platform; print(platform.python_version())'
  ])
  if (platform === 'win32') {
    const dllName = windowsVersionedDllName(pythonVersion)
    if (dllName === null || !existsSync(join(outDir, 'python', dllName))) {
      fail(
        `Windows runtime is missing ${dllName ?? 'python3XY.dll'} next to python.exe ` +
          `(staged ${pythonVersion}). python3.dll is only a stub; without the versioned ` +
          `DLL the packaged appserver cannot start on machines that do not already have CPython.`
      )
    }
  }
  const protocolVersion = (
    JSON.parse(readFileSync(join(appDirStaged, 'protocol', 'schema.json'), 'utf8')) as {
      protocol_version: string
    }
  ).protocol_version
  writeFileSync(
    join(outDir, 'manifest.json'),
    `${JSON.stringify(
      {
        platform,
        arch,
        pythonVersion,
        rxycodeVersion,
        createdAt: new Date().toISOString()
      },
      null,
      2
    )}\n`
  )

  // 6) verify the staged runtime itself
  runPython(pythonExe, ['-c', 'import appserver; print(appserver.__name__)'], appDirStaged)
  runPython(
    pythonExe,
    [
      '-c',
      'import pydantic, yaml, jsonschema, fastapi, uvicorn, langchain, langchain_openai, langgraph, psutil, tenacity, pybreaker, numpy, httpx, aiosqlite, tiktoken, click, rich, venv; print("deps-ok")'
    ],
    appDirStaged
  )
  const start = spawnSync(pythonExe, ['-m', 'appserver'], {
    cwd: appDirStaged,
    env: {
      ...process.env,
      RXYCODE_APPSERVER_STUB: '1',
      PYTHONUNBUFFERED: '1',
      PYTHONIOENCODING: 'utf-8',
      PYTHONDONTWRITEBYTECODE: '1'
    },
    input: '',
    timeout: 120_000,
    encoding: 'utf8'
  })
  if (start.status !== 0) {
    fail(`stub appserver start failed (status ${String(start.status)}): ${start.stderr}`)
  }
  stripBytecode(appDirStaged)

  const total = dirSize(outDir)
  console.log(
    `RUNTIME_PREPARE_OK out=${outDir} pythonVersion=${pythonVersion} rxycodeVersion=${rxycodeVersion} protocolVersion=${protocolVersion} totalBytes=${total}`
  )
}
