/**
 * Local PostgreSQL child-process lifecycle for mail-core (architecture §4.3).
 *
 * Data directory MUST live under the OS app-data path (outside the install /
 * Electron resources dir). Uninstall must not delete this directory by default.
 *
 * When no postgres/initdb/pg_ctl binaries are present, methods return
 * { ok: false, stub: true, reason } so the shell can still boot Flask-only.
 */

const fs = require('fs')
const path = require('path')
const { spawn, spawnSync } = require('child_process')

const DEFAULT_PORT = 54329

/** Official PG binaries: packaged resources/pgsql/bin, else desktop/vendor/pgsql/bin. */
function defaultVendorBinDir() {
  try {
    const { app } = require('electron')
    if (app && app.isPackaged) {
      const packaged = path.join(process.resourcesPath, 'pgsql', 'bin')
      if (fs.existsSync(path.join(packaged, 'pg_ctl')) || fs.existsSync(path.join(packaged, 'pg_ctl.exe'))) {
        return packaged
      }
    }
  } catch (_) {
    /* not running under electron */
  }
  if (process.resourcesPath) {
    const packaged = path.join(process.resourcesPath, 'pgsql', 'bin')
    if (fs.existsSync(path.join(packaged, 'pg_ctl')) || fs.existsSync(path.join(packaged, 'pg_ctl.exe'))) {
      return packaged
    }
  }
  return path.join(__dirname, 'vendor', 'pgsql', 'bin')
}

function defaultMailDataRoot(app) {
  // Electron app.getPath('userData') is already outside the install directory.
  const base = app && typeof app.getPath === 'function'
    ? app.getPath('userData')
    : path.join(process.env.HOME || process.env.USERPROFILE || '/tmp', '.kkmail')
  return path.join(base, 'mail-core-data')
}

function resolveBin(name, hintDir) {
  if (hintDir) {
    const candidate = path.join(hintDir, process.platform === 'win32' ? `${name}.exe` : name)
    if (fs.existsSync(candidate)) return candidate
  }
  // PATH lookup via `which`-like: rely on spawnSync later; return name for PATH.
  return name
}

function PostgresManager(options = {}) {
  this.app = options.app || null
  this.dataRoot = options.dataRoot || defaultMailDataRoot(this.app)
  this.pgBinDir = options.pgBinDir || process.env.KKMAIL_PG_BIN || defaultVendorBinDir()
  this.port = Number(options.port || process.env.KKMAIL_PG_PORT || DEFAULT_PORT)
  this.user = options.user || 'kkmail'
  this.database = options.database || 'kkmail_mail'
  this.password = options.password || process.env.KKMAIL_PG_PASSWORD || 'kkmail'
  this._child = null
  this._log = options.log || console
}

PostgresManager.prototype.paths = function paths() {
  return {
    dataRoot: this.dataRoot,
    pgData: path.join(this.dataRoot, 'pgdata'),
    blobs: path.join(this.dataRoot, 'blobs'),
    backups: path.join(this.dataRoot, 'backups'),
    logFile: path.join(this.dataRoot, 'postgres.log'),
  }
}

PostgresManager.prototype.ensureDirs = function ensureDirs() {
  const p = this.paths()
  for (const dir of [p.dataRoot, p.blobs, p.backups]) {
    fs.mkdirSync(dir, { recursive: true })
  }
  // Marker so uninstall docs can find the durable data root.
  const marker = path.join(p.dataRoot, 'README-DO-NOT-DELETE.txt')
  if (!fs.existsSync(marker)) {
    fs.writeFileSync(
      marker,
      [
        'kkmail mail-core local data',
        'This directory is outside the application install path.',
        'Uninstalling kkmail must NOT delete this folder by default.',
        `Created: ${new Date().toISOString()}`,
        '',
      ].join('\n'),
      'utf8',
    )
  }
  return p
}

PostgresManager.prototype.hasBinaries = function hasBinaries() {
  const check = (bin) => {
    if (!bin) return false
    if (path.isAbsolute(bin) || bin.includes(path.sep)) return fs.existsSync(bin)
    const r = spawnSync(bin, ['--version'], { encoding: 'utf8' })
    return r.status === 0
  }
  const pick = (name) => {
    const fromHint = resolveBin(name, this.pgBinDir)
    if (check(fromHint) && (path.isAbsolute(fromHint) || fromHint.includes(path.sep))) return fromHint
    // Fall back to PATH (dev machines with system postgres)
    if (check(name)) return name
    return null
  }
  return {
    initdb: pick('initdb'),
    pg_ctl: pick('pg_ctl'),
    postgres: pick('postgres'),
  }
}

PostgresManager.prototype.status = function status() {
  const p = this.paths()
  const bins = this.hasBinaries()
  const stub = !(bins.initdb && bins.pg_ctl)
  let running = false
  if (!stub && bins.pg_ctl && fs.existsSync(p.pgData)) {
    const r = spawnSync(bins.pg_ctl, ['status', '-D', p.pgData], { encoding: 'utf8' })
    running = r.status === 0
  } else if (this._child && !this._child.killed) {
    running = true
  }
  return {
    ok: true,
    stub,
    running,
    dataRoot: p.dataRoot,
    pgData: p.pgData,
    port: this.port,
    binaries: {
      initdb: Boolean(bins.initdb),
      pg_ctl: Boolean(bins.pg_ctl),
      postgres: Boolean(bins.postgres),
    },
    connectionUrl: `postgresql+psycopg://${this.user}:***@127.0.0.1:${this.port}/${this.database}`,
  }
}

PostgresManager.prototype.initIfNeeded = function initIfNeeded() {
  const p = this.ensureDirs()
  const bins = this.hasBinaries()
  if (!bins.initdb || !bins.pg_ctl) {
    return { ok: false, stub: true, reason: 'PostgreSQL binaries not found (set KKMAIL_PG_BIN)' }
  }
  if (fs.existsSync(path.join(p.pgData, 'PG_VERSION'))) {
    return { ok: true, initialized: false, pgData: p.pgData }
  }
  fs.mkdirSync(p.pgData, { recursive: true })
  const pwFile = path.join(this.dataRoot, '.pgpass-init')
  fs.writeFileSync(pwFile, this.password, { encoding: 'utf8', mode: 0o600 })
  const r = spawnSync(
    bins.initdb,
    ['-D', p.pgData, '-U', this.user, '--pwfile', pwFile, '-A', 'password', '--locale=C', '--encoding=UTF8'],
    { encoding: 'utf8' },
  )
  try { fs.unlinkSync(pwFile) } catch (_) { /* ignore */ }
  if (r.status !== 0) {
    return { ok: false, stub: false, reason: r.stderr || r.stdout || 'initdb failed' }
  }
  // Listen on loopback only
  const conf = path.join(p.pgData, 'postgresql.conf')
  fs.appendFileSync(conf, `\nlisten_addresses = '127.0.0.1'\nport = ${this.port}\n`)
  return { ok: true, initialized: true, pgData: p.pgData }
}

PostgresManager.prototype.start = function start() {
  const st = this.status()
  if (st.stub) {
    this.ensureDirs()
    return {
      ok: false,
      stub: true,
      reason: 'PostgreSQL binaries not bundled yet — data dir prepared, start skipped',
      dataRoot: this.paths().dataRoot,
    }
  }
  if (st.running) return { ok: true, alreadyRunning: true, ...this.status() }
  const init = this.initIfNeeded()
  if (!init.ok) return init
  const bins = this.hasBinaries()
  const p = this.paths()
  const r = spawnSync(
    bins.pg_ctl,
    ['start', '-D', p.pgData, '-l', p.logFile, '-w'],
    { encoding: 'utf8', env: { ...process.env, PGPORT: String(this.port) } },
  )
  if (r.status !== 0) {
    return { ok: false, reason: r.stderr || r.stdout || 'pg_ctl start failed' }
  }
  return { ok: true, started: true, ...this.status() }
}

PostgresManager.prototype.stop = function stop() {
  const bins = this.hasBinaries()
  const p = this.paths()
  if (!bins.pg_ctl || !fs.existsSync(p.pgData)) {
    if (this._child) {
      this._child.kill('SIGTERM')
      this._child = null
    }
    return { ok: true, stub: !bins.pg_ctl, stopped: true }
  }
  const r = spawnSync(bins.pg_ctl, ['stop', '-D', p.pgData, '-m', 'fast', '-w'], { encoding: 'utf8' })
  return { ok: r.status === 0, stopped: true, detail: r.stderr || r.stdout }
}

module.exports = {
  DEFAULT_PORT,
  PostgresManager,
  defaultMailDataRoot,
  defaultVendorBinDir,
  resolveBin,
}
