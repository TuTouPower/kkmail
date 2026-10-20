/**
 * Electron main process.
 * Starts local PostgreSQL + the mail-core sidecar on 127.0.0.1 and opens the React UI.
 * contextIsolation on, nodeIntegration off.
 */
const { app, BrowserWindow, shell, dialog, session } = require('electron')
const crypto = require('crypto')
const fs = require('fs')
const path = require('path')
const { spawn } = require('child_process')
const { sidecarPath, frontendDistPath, isAllowedExternalUrl, isLocalAppUrl } = require('./paths')
const { parsePort, freePort, waitForHealth, scrubEnv, redactSecrets, stopChildTree } = require('./startup')
const {
  mergeCspHeaders,
  denyPermissionRequest,
  denyPermissionCheck,
} = require('./hardening')
const { PostgresManager } = require('./postgresManager')

const PORT = parsePort(process.env.OUTLOOK_DESKTOP_PORT)
const HOST = '127.0.0.1'
let backend = null
let backendExit = null
let mainWindow = null
let backendUrl = ''
let appOrigin = ''
let shuttingDown = false
let backendLogStream = null

function repoRoot() {
  return path.resolve(__dirname, '..')
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

function pipeBackendLogs(child, logPath, secrets) {
  try {
    fs.mkdirSync(path.dirname(logPath), { recursive: true })
    backendLogStream = fs.createWriteStream(logPath, { flags: 'a' })
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
  const env = scrubEnv(process.env, {
    MAIL_CORE_HOST: HOST,
    MAIL_CORE_PORT: String(port),
    MAIL_CORE_DATA_DIR: dataRoot,
    MAIL_CORE_DATABASE_URL: databaseUrl,
    KKMAIL_SIDECAR: '1',
    KKMAIL_INSTANCE_TOKEN: instanceToken,
  })
  const dist = target.packaged
    ? frontendDistPath(process.resourcesPath)
    : path.join(repoRoot(), 'frontend', 'dist')
  if (dist) env.KKMAIL_FRONTEND_DIST = dist

  // Own process group on Unix so stopChildTree can SIGTERM/SIGKILL the whole tree.
  const detached = process.platform !== 'win32'
  backend = spawn(target.cmd, [...target.args, '--data-dir', dataRoot, '--instance-token', instanceToken], {
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
  await waitForHealth(`http://${HOST}:${port}/health`, 60000, {
    instanceToken,
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
  mainWindow = new BrowserWindow({
    width: 1280,
    height: 840,
    minWidth: 900,
    minHeight: 600,
    title: 'kkmail',
    backgroundColor: '#171819',
    icon: path.join(__dirname, 'icon.svg'),
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      webviewTag: false,
    },
  })
  mainWindow.on('closed', () => {
    mainWindow = null
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

function stopMailCorePg() {
  if (!pg) return
  try { pg.stop() } catch (err) { console.warn('[mail-core] pg stop', err) }
  // Keep reference so repeat stop() is the same idempotent manager (no throwaway).
}

function stopBackend() {
  if (!backend) return
  const child = backend
  stopChildTree(child, {
    escalateAfterMs: 4000,
    log: (m) => console.warn('[mail-core] stopBackend', m),
  })
}

/** Single-flight shutdown for before-quit + signals + process exit (avoids triple stop races). */
function shutdownAll() {
  if (shuttingDown) return
  shuttingDown = true
  app.isQuitting = true
  stopBackend()
  stopMailCorePg()
  if (backendLogStream) {
    try { backendLogStream.end() } catch (_) { /* ignore */ }
    backendLogStream = null
  }
}

app.on('before-quit', () => {
  shutdownAll()
})

// SIGTERM/SIGINT (logout, `kill`, Ctrl+C) skip before-quit; never leave the backend orphaned.
for (const signal of ['SIGTERM', 'SIGINT', 'SIGHUP']) {
  process.on(signal, () => {
    shutdownAll()
    app.quit()
  })
}
process.on('exit', () => {
  shutdownAll()
})
