/**
 * Electron main process.
 * Starts the existing Flask backend on 127.0.0.1 and opens the React UI.
 * contextIsolation on, nodeIntegration off.
 */
const { app, BrowserWindow, shell } = require('electron')
const path = require('path')
const { spawn } = require('child_process')
const http = require('http')
const net = require('net')

const PORT = Number(process.env.OUTLOOK_DESKTOP_PORT || 18765)
const HOST = '127.0.0.1'
let backend = null
let mainWindow = null

function repoRoot() {
  // desktop/ -> repo root in dev; resources path when packaged later
  return path.resolve(__dirname, '..')
}

function freePort(preferred) {
  return new Promise((resolve) => {
    const srv = net.createServer()
    srv.once('error', () => resolve(preferred + 1))
    srv.once('listening', () => {
      const { port } = srv.address()
      srv.close(() => resolve(port))
    })
    srv.listen(preferred, HOST)
  })
}

function waitForHealth(url, timeoutMs = 20000) {
  const started = Date.now()
  return new Promise((resolve, reject) => {
    const tick = () => {
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
  const packaged = path.join(process.resourcesPath || '', 'backend', 'outlookemail-backend')
  if (process.resourcesPath && require('fs').existsSync(packaged)) {
    return { cmd: packaged, args: [], cwd: path.dirname(packaged) }
  }
  const root = repoRoot()
  const py = process.env.PYTHON || (process.platform === 'win32' ? 'python' : 'python3')
  return { cmd: py, args: [path.join(root, 'web_outlook_app.py')], cwd: root }
}

async function startBackend() {
  const port = await freePort(PORT)
  const root = repoRoot()
  const env = {
    ...process.env,
    SECRET_KEY: process.env.SECRET_KEY || 'desktop-local-secret-change-me',
    LOGIN_PASSWORD: process.env.LOGIN_PASSWORD || 'admin123',
    PORT: String(port),
    HOST: HOST,
  }
  const target = backendCommand()
  backend = spawn(target.cmd, target.args, {
    cwd: target.cwd || root,
    env,
    stdio: 'inherit',
  })
  backend.on('exit', (code) => {
    if (code && code !== 0) console.error('backend exited', code)
  })
  await waitForHealth(`http://${HOST}:${port}/login`)
  return `http://${HOST}:${port}/`
}

function createWindow(url) {
  mainWindow = new BrowserWindow({
    width: 1280,
    height: 840,
    minWidth: 900,
    minHeight: 600,
    title: 'Mail',
    backgroundColor: '#171819',
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  })
  mainWindow.loadURL(url)
  mainWindow.webContents.setWindowOpenHandler(({ url: target }) => {
    shell.openExternal(target)
    return { action: 'deny' }
  })
}

app.whenReady().then(async () => {
  try {
    const url = await startBackend()
    createWindow(url)
  } catch (err) {
    console.error(err)
    const { dialog } = require('electron')
    dialog.showErrorBox('OutlookEmail 无法启动', String(err && err.message ? err.message : err))
    app.quit()
  }
})

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit()
})

app.on('before-quit', () => {
  if (backend && !backend.killed) {
    backend.kill('SIGTERM')
  }
})
