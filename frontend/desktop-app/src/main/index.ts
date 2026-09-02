import { app, shell, BrowserWindow, dialog, ipcMain } from 'electron'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { pathToFileURL } from 'node:url'
import { electronApp, optimizer, is } from '@electron-toolkit/utils'
import { autoUpdater } from 'electron-updater'
import icon from '../../resources/icon.png?asset'
import { ProtocolClient } from '@rxycode/protocol-client'
import { AppServerManager, type AppserverExitInfo } from './appserver'
import { createUpdateManager, type UpdateManager, type UpdateStatusSnapshot } from './auto-update'
import {
  createCrashReportManager,
  type CrashDiagnosticContext,
  type CrashReportManager,
  type CrashReportSummary
} from './crash-report'
import { isSafeExternalUrl } from './external-url'
import { registerAllowedHandle } from './ipc-allowlist'
import { isAllowedNavigation } from './navigation'
import { pickWorkspaceDirectory } from './workspace-dialog'
import { revealDirectory } from './workspace-reveal'
import { shouldDisableLinuxSandbox } from './linuxStartup'
import { shouldQuitSecondInstance } from './window-policy'
import { webPreferencesSafe } from './web-preferences'
import {
  getSharedSupervisor,
  ProcessSupervisor,
  type ProcessLifecycleEvent
} from './supervisor'

const SMOKE = process.env.RXYCODE_DESKTOP_SMOKE === '1'
const KEEPALIVE = process.env.RXYCODE_DESKTOP_KEEPALIVE === '1'
const UPDATE_SMOKE = process.env.RXYCODE_DESKTOP_UPDATE_SMOKE === '1'
const CRASH_SIM = process.env.RXYCODE_DESKTOP_CRASH_SIM
const USER_DATA_OVERRIDE = process.env.RXYCODE_DESKTOP_USER_DATA
const APP_ID = 'com.rxycode.desktop'
const APP_INDEX_URL = pathToFileURL(join(__dirname, '../renderer/index.html')).href

if (USER_DATA_OVERRIDE !== undefined && USER_DATA_OVERRIDE !== '') {
  app.setPath('userData', USER_DATA_OVERRIDE)
  app.setPath('cache', join(USER_DATA_OVERRIDE, 'cache'))
}

const gotDesktopLock = app.requestSingleInstanceLock()
if (shouldQuitSecondInstance(gotDesktopLock)) {
  app.quit()
}

// Headless/VM environments (e.g. remote desktop) have no usable GPU and
// Electron aborts on startup with "GPU process isn't usable".
app.commandLine.appendSwitch('disable-gpu')
// Chromium --no-sandbox is AppImage-only and opt-in. BrowserWindow sandbox
// (webPreferences.sandbox=true) stays on for H3 acceptance.
if (
  shouldDisableLinuxSandbox(process.platform, app.isPackaged) &&
  process.env.RXYCODE_LINUX_NO_SANDBOX === '1'
) {
  app.commandLine.appendSwitch('no-sandbox')
}

let mainWindow: BrowserWindow | null = null
let manager: AppServerManager | null = null
let updateManager: UpdateManager | null = null
let crashManager: CrashReportManager | null = null
let lastAppserverExit: AppserverExitInfo | null = null
let lastCrashSummary: CrashReportSummary | null = null

function windowSizeFromEnv(): { width: number; height: number } {
  const rawWidth = process.env.RXYCODE_DESKTOP_WIDTH
  const rawHeight = process.env.RXYCODE_DESKTOP_HEIGHT
  const width = rawWidth !== undefined && rawWidth.trim() !== '' ? Number(rawWidth) : NaN
  const height = rawHeight !== undefined && rawHeight.trim() !== '' ? Number(rawHeight) : NaN
  return {
    width: Number.isFinite(width) ? width : 1280,
    height: Number.isFinite(height) ? height : 800
  }
}

function getManager(): AppServerManager {
  if (manager === null) {
    manager = new AppServerManager({
      cwd: process.cwd(),
      stub: process.env.RXYCODE_APPSERVER_STUB === '1',
      fakeAppserver: process.env.RXYCODE_DESKTOP_FAKE_APPSERVER === '1'
    })
    manager.on('status', (status: string) => broadcast('appserver:status', status))
    manager.on('log', (line: string) => broadcast('appserver:log', line))
    manager.on('line', (line: string) => broadcast('appserver:line', line))
    manager.on('exit', (exit: AppserverExitInfo) => {
      lastAppserverExit = { code: exit.code, signal: exit.signal }
    })
  }
  return manager
}

function getSupervisor() {
  return getSharedSupervisor(() => {
    const next = new ProcessSupervisor(getManager())
    next.on('lifecycle', (event: ProcessLifecycleEvent) => {
      broadcast('appserver:lifecycle', event)
    })
    return next
  })
}

function getUpdateManager(): UpdateManager {
  if (updateManager === null) {
    const feedUrl = process.env.RXYCODE_UPDATE_FEED_URL ?? null
    // Dev mode reads dev-app-update.yml (kept out of packaged files);
    // packaged builds read the electron-builder generated app-update.yml.
    autoUpdater.forceDevUpdateConfig = !app.isPackaged
    // Full downloads: deterministic and avoids blockmap/range requirements
    // on the generic feed (Phase4-D7 decision, verified by feed smoke).
    autoUpdater.disableDifferentialDownload = true
    updateManager = createUpdateManager({
      updater: autoUpdater,
      currentVersion: app.getVersion(),
      feedUrl,
      isEnabled: () => app.isPackaged || feedUrl !== null
    })
    updateManager.on('status', (snapshot: UpdateStatusSnapshot) =>
      broadcast('update:status', snapshot)
    )
  }
  return updateManager
}

function crashContext(): CrashDiagnosticContext {
  let protocolVersion: string | null = null
  try {
    const schema = JSON.parse(
      readFileSync(join(getManager().repoRootDir, 'protocol', 'schema.json'), 'utf8')
    ) as { protocol_version?: unknown }
    protocolVersion = typeof schema.protocol_version === 'string' ? schema.protocol_version : null
  } catch {
    protocolVersion = null
  }
  return {
    app: {
      version: app.getVersion(),
      electron: process.versions.electron ?? 'unknown',
      chrome: process.versions.chrome ?? 'unknown',
      node: process.versions.node ?? 'unknown',
      platform: process.platform,
      arch: process.arch
    },
    protocol: {
      protocolVersion,
      appserverStatus: manager?.status ?? 'stopped',
      appserverExit: lastAppserverExit,
      protocolViolations: manager?.protocolViolations.length ?? 0,
      appserverPid: manager?.pid ?? null
    },
    logSummary: manager?.logs ?? []
  }
}

function getCrashManager(): CrashReportManager {
  if (crashManager === null) {
    crashManager = createCrashReportManager({
      userDataDir: app.getPath('userData'),
      context: crashContext,
      uploadUrl: process.env.RXYCODE_CRASH_REPORT_URL ?? null,
      onCrash: shutdownAppserver
    })
    crashManager.on('captured', (summary: CrashReportSummary) => {
      lastCrashSummary = summary
      // The renderer that crashed is gone; broadcasting to it would only
      // produce frame-disposed noise from Electron.
      if (summary.source !== 'render-process-gone') {
        broadcast('crash-report:captured', summary)
      }
    })
  }
  return crashManager
}

/**
 * Idempotent DC5 backstop: safe on normal exit, on repeated triggers and
 * with a null manager (never constructs one just to kill it).
 */
function shutdownAppserver(): void {
  try {
    manager?.kill()
  } catch (error) {
    console.error('crash shutdown appserver failed (ignored)', error)
  }
}

function broadcast(channel: string, payload: unknown): void {
  for (const window of BrowserWindow.getAllWindows()) {
    const webContents = window.webContents
    if (webContents.isDestroyed()) continue
    try {
      webContents.send(channel, payload)
    } catch {
      // Renderer may already be gone (crash capture path); nothing to do.
    }
  }
}

function createWindow(): void {
  const { width, height } = windowSizeFromEnv()
  mainWindow = new BrowserWindow({
    width,
    height,
    minWidth: 880,
    minHeight: 600,
    show: false,
    autoHideMenuBar: true,
    ...(process.platform === 'linux' ? { icon } : {}),
    webPreferences: webPreferencesSafe({
      preload: join(__dirname, '../preload/index.js')
    })
  })

  mainWindow.on('ready-to-show', () => {
    if (!KEEPALIVE) mainWindow?.show()
  })

  mainWindow.on('closed', () => {
    mainWindow = null
    getSupervisor().closeWindow()
  })
  getSupervisor().openWindow()

  mainWindow.webContents.setWindowOpenHandler((details) => {
    if (isSafeExternalUrl(details.url)) {
      void dialog
        .showMessageBox({
          type: 'question',
          buttons: ['打开', '取消'],
          defaultId: 1,
          cancelId: 1,
          title: '打开外部链接',
          message: '是否在浏览器中打开此链接？',
          detail: details.url
        })
        .then(({ response }) => {
          if (response === 0) void shell.openExternal(details.url)
        })
    }
    return { action: 'deny' }
  })

  mainWindow.webContents.on('will-navigate', (event, url) => {
    const devUrl = process.env['ELECTRON_RENDERER_URL']
    const allowed = isAllowedNavigation(url, {
      appIndexUrl: APP_INDEX_URL,
      devUrl,
      isDev: is.dev
    })
    if (!allowed) event.preventDefault()
  })

  if (is.dev && process.env['ELECTRON_RENDERER_URL']) {
    mainWindow.loadURL(process.env['ELECTRON_RENDERER_URL'])
  } else {
    mainWindow.loadFile(join(__dirname, '../renderer/index.html'))
  }

  if (CRASH_SIM === 'render-gone') {
    // Crash-smoke hook: forcefully crash the real renderer so the main
    // process can capture a genuine render-process-gone diagnostic (DC5).
    mainWindow.webContents.once('did-finish-load', () => {
      setTimeout(() => {
        mainWindow?.webContents.forcefullyCrashRenderer()
      }, 1500)
    })
  }
}

app.on('render-process-gone', (_event, webContents, details) => {
  if (mainWindow !== null && webContents !== mainWindow.webContents) return
  getCrashManager().capture('render-process-gone', {
    reason: details.reason,
    exitCode: details.exitCode
  })
  console.log(`CRASH_SOURCE render-process-gone`)
  console.log(`CRASH_REASON ${details.reason}`)
  console.log(`CRASH_REPORT_FILE ${lastCrashSummary?.path ?? 'n/a'}`)
  shutdownAppserver()
  if (CRASH_SIM !== undefined) {
    setTimeout(() => app.exit(0), 300)
  }
})

app.on('child-process-gone', (_event, details) => {
  getCrashManager().capture('child-process-gone', {
    type: details.type,
    reason: details.reason,
    exitCode: details.exitCode
  })
  shutdownAppserver()
})

process.on('uncaughtException', (error) => {
  getCrashManager().capture('uncaught-exception', { message: error.message })
  shutdownAppserver()
})

process.on('unhandledRejection', (reason) => {
  getCrashManager().capture('unhandled-rejection', {
    message: reason instanceof Error ? reason.message : String(reason)
  })
  shutdownAppserver()
})

async function runSmoke(): Promise<number> {
  process.env.RXYCODE_APPSERVER_STUB = '1'
  const packageJson = JSON.parse(readFileSync(join(__dirname, '../../package.json'), 'utf8')) as {
    version: string
  }
  const appserver = getManager()
  const schema = JSON.parse(
    readFileSync(join(appserver.repoRootDir, 'protocol', 'schema.json'), 'utf8')
  ) as { protocol_version: string }

  appserver.start()
  console.log(`SMOKE_RUNTIME ${appserver.runtimeLabel}`)
  const client = new ProtocolClient((line) => appserver.sendLine(line))
  const onLine = (line: string): void => {
    void client.handleLine(line)
  }
  appserver.on('line', onLine)
  try {
    const result = await client.requestWithTimeout<{
      protocol_version: string
      server_name: string
      capabilities: Record<string, unknown>
    }>(
      'initialize',
      {
        client_name: 'rxycode-desktop',
        client_version: packageJson.version,
        protocol_version: schema.protocol_version,
        capabilities: {}
      },
      15_000
    )

    console.log(`SMOKE_CHILD_PID ${appserver.pid ?? 'n/a'}`)
    console.log(`SMOKE_RESULT ${JSON.stringify(result)}`)
    console.log(`SMOKE_VIOLATIONS ${appserver.protocolViolations.length}`)
    for (const violation of appserver.protocolViolations) {
      console.error(`SMOKE_VIOLATION ${violation}`)
    }
  } finally {
    client.rejectAllPending(new Error('smoke teardown'))
    appserver.off('line', onLine)
    if (!KEEPALIVE) await appserver.stop()
  }
  if (KEEPALIVE) {
    console.log('SMOKE_READY')
  } else {
    console.log('SMOKE_DONE')
  }
  return 0
}

/**
 * Update feed smoke (Phase4-D7): driven by RXYCODE_DESKTOP_UPDATE_SMOKE=1
 * against a local generic feed (RXYCODE_UPDATE_FEED_URL). Checks, downloads
 * and reports markers without ever installing or restarting the app.
 */
async function runUpdateSmoke(): Promise<number> {
  const update = getUpdateManager()
  const checked = await update.check()
  console.log(`UPDATE_STATUS ${JSON.stringify(checked)}`)
  if (checked.status !== 'available') {
    throw new Error(
      `update smoke expected available, got ${checked.status}: ${checked.error ?? ''}`
    )
  }
  const downloaded = await update.download()
  console.log(`UPDATE_STATUS ${JSON.stringify(downloaded)}`)
  if (downloaded.status !== 'downloaded') {
    throw new Error(
      `update smoke expected downloaded, got ${downloaded.status}: ${downloaded.error ?? ''}`
    )
  }
  console.log('UPDATE_SMOKE_OK')
  return 0
}

app.on('second-instance', () => {
  if (mainWindow !== null) {
    if (mainWindow.isMinimized()) mainWindow.restore()
    mainWindow.show()
    mainWindow.focus()
    return
  }
  createWindow()
})

app.whenReady().then(() => {
  electronApp.setAppUserModelId(APP_ID)

  app.on('browser-window-created', (_, window) => {
    optimizer.watchWindowShortcuts(window)
  })

  registerAllowedHandle(ipcMain, 'appserver:get-status', () => getManager().status)
  registerAllowedHandle(ipcMain, 'appserver:start', () => {
    getSupervisor().start()
    return getManager().status
  })
  registerAllowedHandle(ipcMain, 'appserver:stop', async () => {
    await getSupervisor().stop()
    return getManager().status
  })
  registerAllowedHandle(ipcMain, 'appserver:send-line', (_event, line: unknown) => {
    getManager().sendLine(String(line))
  })
  registerAllowedHandle(ipcMain, 'workspace:pick-directory', () => pickWorkspaceDirectory(dialog))
  registerAllowedHandle(ipcMain, 'workspace:reveal', (_event, cwd: unknown) => revealDirectory(shell, String(cwd)))
  registerAllowedHandle(ipcMain, 'update:get-status', () => getUpdateManager().snapshot())
  registerAllowedHandle(ipcMain, 'update:check', async () => {
    await getUpdateManager().check()
    return getUpdateManager().snapshot()
  })
  registerAllowedHandle(ipcMain, 'update:download', async () => {
    await getUpdateManager().download()
    return getUpdateManager().snapshot()
  })
  registerAllowedHandle(ipcMain, 'update:install', () => {
    getUpdateManager().install()
  })
  registerAllowedHandle(ipcMain, 'crash-report:get-consent', () => getCrashManager().getConsent())
  registerAllowedHandle(ipcMain, 'crash-report:set-consent', (_event, enabled: unknown) => {
    getCrashManager().setConsent(enabled === true)
  })
  registerAllowedHandle(ipcMain, 'crash-report:list', () => getCrashManager().listReports())
  registerAllowedHandle(ipcMain, 'appserver:get-info', () => {
    const manager = getManager()
    const schema = JSON.parse(
      readFileSync(join(manager.repoRootDir, 'protocol', 'schema.json'), 'utf8')
    ) as { protocol_version: string }
    const packageJson = JSON.parse(readFileSync(join(__dirname, '../../package.json'), 'utf8')) as {
      version: string
    }
    return {
      repoRoot: manager.repoRootDir,
      protocolVersion: schema.protocol_version,
      appVersion: packageJson.version,
      appserverPid: manager.pid,
      appserverStatus: manager.status,
      appserverStartedAt: manager.startedAt,
      appserverLastExit: manager.lastExit,
      systemLocale: app.getLocale(),
      homeDir: app.getPath('home')
    }
  })

  if (SMOKE) {
    runSmoke()
      .then((code) => {
        if (KEEPALIVE) {
          createWindow()
        } else {
          app.exit(code)
        }
      })
      .catch((error) => {
        console.error(`SMOKE_FAILED ${String(error)}`)
        app.exit(1)
      })
    return
  }

  if (UPDATE_SMOKE) {
    runUpdateSmoke()
      .then((code) => app.exit(code))
      .catch((error) => {
        console.error(`UPDATE_SMOKE_FAILED ${String(error)}`)
        app.exit(1)
      })
    return
  }

  if (CRASH_SIM !== undefined) {
    // Crash-smoke mode: real renderer crash against a real (stub) appserver.
    process.env.RXYCODE_APPSERVER_STUB = '1'
    createWindow()
    const appserver = getManager()
    appserver.on('status', (status: string) => {
      if (status === 'running' && appserver.pid !== null) {
        console.log(`SMOKE_CHILD_PID ${appserver.pid}`)
      }
    })
    appserver.start()
    return
  }

  createWindow()
  getManager().start()

  app.on('activate', function () {
    if (BrowserWindow.getAllWindows().length === 0) createWindow()
  })
})

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') {
    app.quit()
  }
})

app.on('will-quit', () => {
  getManager().kill()
})
