/**
 * Electron main process.
 * Starts local PostgreSQL + the mail-core sidecar on 127.0.0.1 and opens the React UI.
 * contextIsolation on, nodeIntegration off.
 */
const { app, BrowserWindow, shell, dialog, session, nativeTheme } = require('electron')
const crypto = require('crypto')
const fs = require('fs')
const path = require('path')
const { spawn } = require('child_process')
const { sidecarPath, frontendDistPath, isAllowedExternalUrl, isLocalAppUrl, createExternalWindowHandler } = require('./paths')
const {
  parsePort,
  freePort,
  waitForHealth,
  scrubEnv,
  redactSecrets,
  isChildDead,
  stopChildTree,
  forceKillChildTreeImmediately,
  collectSidecarExtras,
} = require('./startup')
const {
  mergeCspHeaders,
  createPermissionRequestHandler,
  createPermissionCheckHandler,
  denyPermissionRequest,
  denyPermissionCheck,
} = require('./hardening')
const { PostgresManager } = require('./postgresManager')
const { getDesktopLogger } = require('./desktopLog')
const { createMainWindowOptions, windowBackgroundColor } = require('./windowOptions')

const desktopLogger = getDesktopLogger({ app })
desktopLogger.hookConsoleAndProcess()
desktopLogger.info('Starting kkmail desktop', {
  pid: process.pid,
  platform: process.platform,
  arch: process.arch,
  electron: process.versions.electron,
  node: process.versions.node,
})

const PORT = parsePort(process.env.KKMAIL_DESKTOP_PORT)
const HOST = '127.0.0.1'
let backend = null
let backendExit = null
let mainWindow = null
let backendUrl = ''
let appOrigin = ''
let shuttingDown = false
let backendLogStream = null

nativeTheme.on('updated', () => {
  if (mainWindow && !mainWindow.isDestroyed()) {
    mainWindow.setBackgroundColor(windowBackgroundColor(nativeTheme.shouldUseDarkColors))
  }
})

function repoRoot() {
  let cur = __dirname
  while (cur !== path.dirname(cur)) {
    if (fs.existsSync(path.join(cur, 'AGENTS.md'))) return cur
    cur = path.dirname(cur)
  }
  return path.resolve(__dirname, '../..')
}

function backendCommand() {
  const packaged = sidecarPath(process.resourcesPath, process.platform)
  if (packaged && fs.existsSync(packaged)) {
    return { cmd: packaged, args: [], cwd: path.dirname(packaged), packaged: true }
  }
  if (app.isPackaged) {
    throw new Error(`找不到内置后端: ${packaged}`)
  }
  const root = repoRoot()
  const py = process.env.PYTHON || (process.platform === 'win32' ? 'python' : 'python3')
  return { cmd: py, args: ['-m', 'mail_core'], cwd: path.join(root, 'src'), packaged: false }
}

const { RotatingLogStream } = require('./logRotation')

let pg = null

function pipeBackendLogs(child, logPath, secrets) {
  try {
    backendLogStream = new RotatingLogStream(logPath)
  } catch (err) {
    console.warn('[mail-core] cannot open backend log', err && err.message)
    backendLogStream = null
  }
  const write = (chunk) => {
    const text = redactSecrets(chunk.toString('utf8'), secrets)
    if (backendLogStream) {
      try { backendLogStream.write(text) } catch (_) { /* ignore */ }
    }
  }
  if (child.stdout) child.stdout.on('data', write)
  if (child.stderr) child.stderr.on('data', write)
}

async function startBackend() {
  // mail-core requires PostgreSQL; the cluster lives under userData (outside the install dir).
  pg = new PostgresManager({ app })
  const pgResult = pg.start()
  if (!pgResult.ok) {
    throw new Error(`PostgreSQL 启动失败: ${pgResult.reason || 'unknown'}`)
  }
  const dataRoot = pg.paths().dataRoot
  const port = await freePort(PORT, HOST)
  if (port == null) throw new Error('无法分配本地端口给 mail-core')
  const target = backendCommand()
  const databaseUrl = pg.databaseUrl()
  const instanceToken = crypto.randomBytes(24).toString('hex')
  const baseExtras = {
    MAIL_CORE_HOST: HOST,
    MAIL_CORE_PORT: String(port),
    MAIL_CORE_DATA_DIR: dataRoot,
    MAIL_CORE_DATABASE_URL: databaseUrl,
    KKMAIL_SIDECAR: '1',
    KKMAIL_INSTANCE_TOKEN: instanceToken,
  }
  const dist = target.packaged
    ? frontendDistPath(process.resourcesPath)
    : path.join(repoRoot(), 'src', 'frontend', 'dist')
  if (dist) baseExtras.KKMAIL_FRONTEND_DIST = dist

  const sidecarExtras = collectSidecarExtras(process.env, baseExtras)
  const env = scrubEnv(process.env, sidecarExtras)

  // Own process group on Unix so stopChildTree can SIGTERM/SIGKILL the whole tree.
  const detached = process.platform !== 'win32'
  backend = spawn(target.cmd, [...target.args, '--data-dir', dataRoot], {
    cwd: target.cwd,
    env,
    stdio: ['ignore', 'pipe', 'pipe'],
    detached,
  })
  pipeBackendLogs(backend, path.join(dataRoot, 'mail-core.log'), [pg.password(), databaseUrl])
  backend.on('error', (err) => {
    backendExit = new Error(`后端启动失败: ${err.message}`)
  })
  backend.on('exit', (code, signal) => {
    if (!backendExit) backendExit = new Error(`后端已退出 (code=${code}, signal=${signal})`)
    if (mainWindow && !app.isQuitting) {
      dialog.showErrorBox('kkmail 后端已退出', String(backendExit.message))
      app.quit()
    }
  })
  // A386: instanceToken reaches the sidecar only via the spawn
  // environment above (private startup channel); /health is probed
  // without any token header exchange.
  await waitForHealth(`http://${HOST}:${port}/health`, 60000, {
    shouldStop: () => backendExit,
  })
  showInitialPasswordOnce(dataRoot)
  return `http://${HOST}:${port}/`
}

/** First run: mail-core generated a random login password; show it until the user changes it. */
function showInitialPasswordOnce(dataRoot) {
  const file = path.join(dataRoot, 'initial-password.txt')
  let pw = ''
  try { pw = fs.readFileSync(file, 'utf8').trim() } catch (_) { return }
  if (!pw) return
  dialog.showMessageBoxSync({
    type: 'info',
    title: 'kkmail 初始登录密码',
    message: `初始登录密码：${pw}`,
    detail: '请登录后在「设置 → 修改密码」中更换。更换后此提示不再出现。',
  })
}

function createWindow(url) {
  appOrigin = new URL(url).origin
  mainWindow = new BrowserWindow(createMainWindowOptions({
    platform: process.platform,
    preloadPath: path.join(__dirname, 'preload.js'),
    iconPath: path.join(__dirname, 'icon.svg'),
    backgroundColor: windowBackgroundColor(nativeTheme.shouldUseDarkColors),
  }))
  mainWindow.on('closed', () => {
    mainWindow = null
  })
  mainWindow.once('ready-to-show', () => {
    if (mainWindow && !mainWindow.isDestroyed()) mainWindow.show()
  })
  mainWindow.loadURL(url)
  mainWindow.webContents.setWindowOpenHandler(createExternalWindowHandler(target => shell.openExternal(target), appOrigin))
  const handleExternalNavigation = (event, target) => {
    if (isLocalAppUrl(target, appOrigin)) return
    event.preventDefault()
    if (isAllowedExternalUrl(target)) shell.openExternal(target)
  }
  mainWindow.webContents.on('will-navigate', handleExternalNavigation)
  mainWindow.webContents.on('will-redirect', handleExternalNavigation)
}

function applySessionHardening() {
  const ses = session.defaultSession
  ses.setPermissionRequestHandler(createPermissionRequestHandler(() => appOrigin))
  ses.setPermissionCheckHandler(createPermissionCheckHandler(() => appOrigin))
  ses.webRequest.onHeadersReceived((details, callback) => {
    callback({ responseHeaders: mergeCspHeaders(details.responseHeaders) })
  })
}

// Deny <webview> tags entirely (unused; attacker-injected tags must not attach).
app.on('web-contents-created', (_event, contents) => {
  contents.on('will-attach-webview', (event) => {
    event.preventDefault()
  })
})

const gotTheLock = app.requestSingleInstanceLock()

if (!gotTheLock) {
  app.quit()
} else {
  app.on('second-instance', () => {
    if (mainWindow) {
      if (mainWindow.isMinimized()) mainWindow.restore()
      mainWindow.show()
      mainWindow.focus()
    }
  })

  app.whenReady().then(async () => {
    try {
      applySessionHardening()
      backendUrl = await startBackend()
      createWindow(backendUrl)
    } catch (err) {
      console.error(err)
      dialog.showErrorBox('kkmail 无法启动', String(err && err.message ? err.message : err))
      app.quit()
    }
  })

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0 && backendUrl) {
      createWindow(backendUrl)
    }
  })

  app.on('window-all-closed', () => {
    if (process.platform !== 'darwin') app.quit()
  })
}

function stopMailCorePg() {
  if (!pg) return
  try {
    const res = pg.stop()
    if (!res || !res.ok) {
      console.warn('[mail-core] pg stop failed:', (res && res.detail) || res)
    }
  } catch (err) {
    console.warn('[mail-core] pg stop exception', err)
  }
  // Keep reference so repeat stop() is the same idempotent manager (no throwaway).
}

function stopBackend() {
  if (!backend || isChildDead(backend)) return Promise.resolve()
  const child = backend
  return new Promise((resolve) => {
    let timer = null
    const cleanup = () => {
      if (timer) clearTimeout(timer)
      child.removeListener('exit', onExit)
      child.removeListener('close', onClose)
    }
    const onClose = () => {
      cleanup()
      resolve()
    }
    const onExit = () => {
      const stdioClosed = (!child.stdout || child.stdout.destroyed) &&
                          (!child.stderr || child.stderr.destroyed)
      if (stdioClosed) {
        cleanup()
        resolve()
      }
      // Otherwise wait for close so stdio pipes are completely flushed
    }
    child.once('exit', onExit)
    child.once('close', onClose)
    timer = setTimeout(() => {
      cleanup()
      resolve()
    }, 6000)
    if (typeof timer.unref === 'function') timer.unref()

    stopChildTree(child, {
      escalateAfterMs: 4000,
      log: (m) => console.warn('[mail-core] stopBackend', m),
    })
  })
}

let shutdownPromise = null
let shutdownFinished = false

/** Single-flight shutdown for before-quit + signals + process exit (avoids triple stop races). */
async function shutdownAll() {
  if (shutdownPromise) return shutdownPromise
  shuttingDown = true
  app.isQuitting = true
  shutdownPromise = (async () => {
    const shutdownTimeout = new Promise((resolve) => setTimeout(resolve, 10000))
    const runShutdown = async () => {
      try {
        await stopBackend()
      } catch (err) {
        console.warn('[mail-core] stopBackend error', err)
      }
      stopMailCorePg()
        if (backendLogStream) {
          try {
            await backendLogStream.end()
          } catch (err) {
            console.warn('[mail-core] backend log stream drain/end error', err)
          }
          backendLogStream = null
        }
        try {
          await desktopLogger.end()
        } catch (_) {}
      }
    await Promise.race([runShutdown(), shutdownTimeout])
  })()
  return shutdownPromise
}

app.on('before-quit', (event) => {
  if (shutdownFinished) return
  event.preventDefault()
  shutdownAll().finally(() => {
    shutdownFinished = true
    app.quit()
  })
})

// SIGTERM/SIGINT (logout, `kill`, Ctrl+C) skip before-quit; never leave the backend orphaned.
for (const signal of ['SIGTERM', 'SIGINT', 'SIGHUP']) {
  process.on(signal, () => {
    shutdownAll().finally(() => {
      shutdownFinished = true
      app.quit()
    })
  })
}
process.on('exit', () => {
  if (!shutdownFinished) {
    if (backend && !isChildDead(backend)) {
      try { stopChildTree(backend, { escalateAfterMs: 0 }) } catch (_) {}
      try { forceKillChildTreeImmediately(backend) } catch (_) {}
    }
    stopMailCorePg()
    if (backendLogStream) {
      try { backendLogStream.end() } catch (_) {}
      backendLogStream = null
    }
  }
})
