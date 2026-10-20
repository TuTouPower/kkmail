/**
 * Electron main process.
 * Starts local PostgreSQL + the mail-core sidecar on 127.0.0.1 and opens the React UI.
 * contextIsolation on, nodeIntegration off.
 */
const { app, BrowserWindow, shell, dialog, session } = require('electron')
const fs = require('fs')
const path = require('path')
const { spawn } = require('child_process')
const http = require('http')
const net = require('net')
const { sidecarPath, frontendDistPath, isAllowedExternalUrl, isLocalAppUrl } = require('./paths')
const {
  mergeCspHeaders,
  denyPermissionRequest,
  denyPermissionCheck,
} = require('./hardening')
const { PostgresManager } = require('./postgresManager')

const PORT = Number(process.env.OUTLOOK_DESKTOP_PORT || 18765)
const HOST = '127.0.0.1'
let backend = null
let backendExit = null
let mainWindow = null
let appOrigin = ''

function repoRoot() {
  return path.resolve(__dirname, '..')
}

function tryListen(port) {
  return new Promise((resolve) => {
    const srv = net.createServer()
    srv.once('error', () => resolve(null))
    srv.once('listening', () => {
      const { port: bound } = srv.address()
      srv.close(() => resolve(bound))
    })
    srv.listen(port, HOST)
  })
}

async function freePort(preferred) {
  const exact = await tryListen(preferred)
  if (exact) return exact
  // Let the OS pick any free port instead of guessing preferred + 1.
  return tryListen(0)
}

function waitForHealth(url, timeoutMs = 30000) {
  const started = Date.now()
  return new Promise((resolve, reject) => {
    const tick = () => {
      if (backendExit) {
        reject(backendExit)
        return
      }
      const req = http.get(url, (res) => {
        res.resume()
        resolve(true)
      })
      req.on('error', () => {
        if (Date.now() - started > timeoutMs) reject(new Error('backend timeout'))
        else setTimeout(tick, 300)
      })
    }
    tick()
  })
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
  return { cmd: py, args: ['-m', 'mail_core'], cwd: root, packaged: false }
}

let pg = null

async function startBackend() {
  // mail-core requires PostgreSQL; the cluster lives under userData (outside the install dir).
  pg = new PostgresManager({ app })
  const pgResult = pg.start()
  if (!pgResult.ok) {
    throw new Error(`PostgreSQL 启动失败: ${pgResult.reason || 'unknown'}`)
  }
  const dataRoot = pg.paths().dataRoot
  const port = await freePort(PORT)
  const target = backendCommand()
  const env = {
    ...process.env,
    // Secrets are generated per install by mail-core (MAIL_CORE_DATA_DIR/secrets, 0600).
    MAIL_CORE_HOST: HOST,
    MAIL_CORE_PORT: String(port),
    MAIL_CORE_DATA_DIR: dataRoot,
    MAIL_CORE_DATABASE_URL: pg.databaseUrl(),
    KKMAIL_SIDECAR: '1',
  }
  const dist = target.packaged
    ? frontendDistPath(process.resourcesPath)
    : path.join(repoRoot(), 'frontend', 'dist')
  if (dist) env.KKMAIL_FRONTEND_DIST = dist

  backend = spawn(target.cmd, [...target.args, '--data-dir', dataRoot], { cwd: target.cwd, env, stdio: 'inherit' })
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
  await waitForHealth(`http://${HOST}:${port}/health`, 60000)
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
  mainWindow = new BrowserWindow({
    width: 1280,
    height: 840,
    minWidth: 900,
    minHeight: 600,
    title: 'kkmail',
    backgroundColor: '#171819',
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      webviewTag: false,
    },
  })
  mainWindow.loadURL(url)
  mainWindow.webContents.setWindowOpenHandler(({ url: target }) => {
    if (isAllowedExternalUrl(target)) shell.openExternal(target)
    return { action: 'deny' }
  })
  mainWindow.webContents.on('will-navigate', (event, target) => {
    if (isLocalAppUrl(target, appOrigin)) return
    event.preventDefault()
    if (isAllowedExternalUrl(target)) shell.openExternal(target)
  })
}

function applySessionHardening() {
  const ses = session.defaultSession
  ses.setPermissionRequestHandler(denyPermissionRequest)
  ses.setPermissionCheckHandler(denyPermissionCheck)
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

app.whenReady().then(async () => {
  try {
    applySessionHardening()
    const url = await startBackend()
    createWindow(url)
  } catch (err) {
    console.error(err)
    dialog.showErrorBox('kkmail 无法启动', String(err && err.message ? err.message : err))
    app.quit()
  }
})

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit()
})

function stopMailCorePg() {
  if (!pg) return
  try { pg.stop() } catch (err) { console.warn('[mail-core] pg stop', err) }
  pg = null
}
function stopBackend() {
  if (backend && backend.exitCode === null && !backend.killed) {
    backend.kill()
  }
}

app.on('before-quit', () => {
  app.isQuitting = true
  stopBackend()
  stopMailCorePg()
})

// SIGTERM/SIGINT (logout, `kill`, Ctrl+C) skip before-quit; never leave the backend orphaned.
for (const signal of ['SIGTERM', 'SIGINT', 'SIGHUP']) {
  process.on(signal, () => {
    app.isQuitting = true
    stopMailCorePg()
    stopBackend()
    app.quit()
  })
}
process.on('exit', () => {
  stopBackend()
  stopMailCorePg()
})
