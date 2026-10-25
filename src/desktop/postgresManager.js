/**
 * Local PostgreSQL child-process lifecycle for mail-core (architecture §4.3).
 *
 * Data directory MUST live under the OS app-data path (outside the install /
 * Electron resources dir). Uninstall must not delete this directory by default.
 *
 * When no postgres/initdb/pg_ctl binaries are present, methods return
 * { ok: false, stub: true, reason }; main.js treats that as a fatal startup error.
 */

const fs = require('fs')
const os = require('os')
const path = require('path')
const crypto = require('crypto')
const cp = require('child_process')
const { scrubEnv } = require('./startup')

const DEFAULT_PORT = 54329
const BIN_PROBE_TIMEOUT_MS = 5000
const MANAGED_CONFIG_BEGIN = '# BEGIN kkmail managed PostgreSQL settings'
const MANAGED_CONFIG_END = '# END kkmail managed PostgreSQL settings'

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

/**
 * Prefer Electron userData; else ~/.kkmail; never a shared world-writable /tmp/.kkmail.
 * Last resort: per-uid directory under os.tmpdir().
 */
function defaultMailDataRoot(app) {
  if (app && typeof app.getPath === 'function') {
    return path.join(app.getPath('userData'), 'mail-core-data')
  }
  let home = ''
  try {
    home = os.homedir() || ''
  } catch (_) {
    home = ''
  }
  if (home && home !== '/' && !home.startsWith(`${path.sep}tmp`) && home !== os.tmpdir()) {
    return path.join(home, '.kkmail', 'mail-core-data')
  }
  const xdg = process.env.XDG_DATA_HOME
  if (xdg) return path.join(xdg, 'kkmail', 'mail-core-data')
  const uid = typeof process.getuid === 'function' ? String(process.getuid()) : 'user'
  return path.join(os.tmpdir(), `kkmail-${uid}`, 'mail-core-data')
}

function resolveBin(name, hintDir) {
  if (hintDir) {
    const candidate = path.join(hintDir, process.platform === 'win32' ? `${name}.exe` : name)
    if (fs.existsSync(candidate)) return candidate
  }
  // PATH lookup via `which`-like: rely on spawnSync later; return name for PATH.
  return name
}

function parsePgPort(raw, fallback = DEFAULT_PORT) {
  const n = Number(raw == null || raw === '' ? fallback : raw)
  if (!Number.isInteger(n) || n < 1 || n > 65535) {
    throw new Error(`KKMAIL_PG_PORT 无效（需要 1–65535 的整数）: ${raw}`)
  }
  return n
}

function reconcilePostgresConfig(confPath, port) {
  let config
  try {
    config = fs.readFileSync(confPath, 'utf8')
  } catch (err) {
    return { ok: false, reason: `Could not read postgresql.conf: ${err.message}` }
  }

  const block = `${MANAGED_CONFIG_BEGIN}\nlisten_addresses = '127.0.0.1'\nport = ${port}\n${MANAGED_CONFIG_END}`
  if (config.trimEnd().endsWith(block)) return { ok: true, changed: false }

  let base = config
  while (true) {
    const begin = base.indexOf(MANAGED_CONFIG_BEGIN)
    const end = begin === -1 ? -1 : base.indexOf(MANAGED_CONFIG_END, begin)
    if (begin === -1) {
      if (base.includes(MANAGED_CONFIG_END)) {
        return { ok: false, reason: 'postgresql.conf has an unmatched kkmail managed settings marker' }
      }
      break
    }
    if (end === -1) {
      return { ok: false, reason: 'postgresql.conf has an incomplete kkmail managed settings block' }
    }
    base = base.slice(0, begin) + base.slice(end + MANAGED_CONFIG_END.length)
  }

  const updated = `${base.replace(/\s*$/, '')}\n\n${block}\n`
  const tempPath = `${confPath}.kkmail-${process.pid}-${crypto.randomBytes(6).toString('hex')}.tmp`
  let fd = null
  try {
    const mode = fs.statSync(confPath).mode & 0o777
    fd = fs.openSync(tempPath, 'wx', mode)
    fs.writeFileSync(fd, updated, 'utf8')
    fs.fsyncSync(fd)
    fs.closeSync(fd)
    fd = null
    fs.chmodSync(tempPath, mode)
    fs.renameSync(tempPath, confPath)
  } catch (err) {
    return { ok: false, reason: `Could not update postgresql.conf: ${err.message}` }
  } finally {
    if (fd !== null) {
      try { fs.closeSync(fd) } catch (_) { /* ignore */ }
    }
    try { fs.unlinkSync(tempPath) } catch (_) { /* already renamed or absent */ }
  }
  return { ok: true, changed: true }
}

function runningPostmasterSettings(pgData) {
  try {
    const lines = fs.readFileSync(path.join(pgData, 'postmaster.pid'), 'utf8').split(/\r?\n/)
    const port = Number(lines[3])
    return {
      port: Number.isInteger(port) && port >= 1 && port <= 65535 ? port : null,
      listenAddresses: lines[5] ? lines[5].trim() : null,
    }
  } catch (_) {
    return null
  }
}

function PostgresManager(options = {}) {
  this.app = options.app || null
  this.dataRoot = options.dataRoot || defaultMailDataRoot(this.app)
  this.pgBinDir = options.pgBinDir || process.env.KKMAIL_PG_BIN || defaultVendorBinDir()
  this.port = parsePgPort(options.port != null ? options.port : process.env.KKMAIL_PG_PORT, DEFAULT_PORT)
  this.user = options.user || 'kkmail'
  this.database = options.database || 'kkmail_mail'
  this._passwordOverride = options.password || process.env.KKMAIL_PG_PASSWORD || ''
  this._child = null
  this._log = options.log || console
  this._binsCache = null
  this._stopped = false
  this._binProbeTimeoutMs = options.binProbeTimeoutMs != null ? options.binProbeTimeoutMs : BIN_PROBE_TIMEOUT_MS
  this._spawnSync = options.spawnSync || cp.spawnSync
}

/** Per-install PG password persisted (0600); an override is saved only on first use. */
PostgresManager.prototype.password = function password() {
  const file = path.join(this.dataRoot, 'secrets', 'pg-password')
  if (this._passwordOverride) {
    fs.mkdirSync(path.dirname(file), { recursive: true, mode: 0o700 })
    try {
      fs.writeFileSync(file, this._passwordOverride + '\n', { encoding: 'utf8', mode: 0o600, flag: 'wx' })
    } catch (err) {
      if (err.code !== 'EEXIST') throw err
    }
    return this._passwordOverride
  }
  try {
    const v = fs.readFileSync(file, 'utf8').trim()
    if (v) return v
  } catch (_) { /* create below */ }
  fs.mkdirSync(path.dirname(file), { recursive: true, mode: 0o700 })
  const v = crypto.randomBytes(24).toString('hex')
  fs.writeFileSync(file, v + '\n', { encoding: 'utf8', mode: 0o600 })
  return v
}

PostgresManager.prototype.databaseUrl = function databaseUrl() {
  const pw = encodeURIComponent(this.password())
  return `postgresql+psycopg://${this.user}:${pw}@127.0.0.1:${this.port}/${this.database}`
}

PostgresManager.prototype.paths = function paths() {
  return {
    dataRoot: this.dataRoot,
    pgData: path.join(this.dataRoot, 'pgdata'),
    blobs: path.join(this.dataRoot, 'blobs'),
    backups: path.join(this.dataRoot, 'backups'),
    logFile: path.join(this.dataRoot, 'postgres.log'),
    secrets: path.join(this.dataRoot, 'secrets'),
  }
}

PostgresManager.prototype.ensureDirs = function ensureDirs() {
  const p = this.paths()
  for (const dir of [p.dataRoot, p.blobs, p.backups, p.secrets]) {
    fs.mkdirSync(dir, { recursive: true, mode: 0o700 })
    try { fs.chmodSync(dir, 0o700) } catch (_) {}
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

/** Drop a leftover initdb pwfile from a crashed previous run. */
PostgresManager.prototype._cleanupInitPwfile = function _cleanupInitPwfile() {
  const pwFile = path.join(this.dataRoot, 'secrets', 'pg-pwfile-init')
  const legacy = path.join(this.dataRoot, '.pgpass-init')
  for (const f of [pwFile, legacy]) {
    try { fs.unlinkSync(f) } catch (_) { /* absent */ }
  }
}

PostgresManager.prototype.hasBinaries = function hasBinaries() {
  if (this._binsCache) return this._binsCache
  const timeout = this._binProbeTimeoutMs
  const check = (bin) => {
    if (!bin) return false
    if (path.isAbsolute(bin) || bin.includes(path.sep)) return fs.existsSync(bin)
    const r = (this._spawnSync || cp.spawnSync)(bin, ['--version'], { encoding: 'utf8', env: scrubEnv(process.env), timeout })
    return !r.error && r.status === 0
  }
  const pick = (name) => {
    const fromHint = resolveBin(name, this.pgBinDir)
    if (check(fromHint) && (path.isAbsolute(fromHint) || fromHint.includes(path.sep))) return fromHint
    // Fall back to PATH (dev machines with system postgres)
    if (check(name)) return name
    return null
  }
  this._binsCache = {
    initdb: pick('initdb'),
    pg_ctl: pick('pg_ctl'),
    postgres: pick('postgres'),
    createdb: pick('createdb'),
  }
  return this._binsCache
}

PostgresManager.prototype.status = function status() {
  const p = this.paths()
  const bins = this.hasBinaries()
  const stub = !(bins.initdb && bins.pg_ctl)
  let running = false
  if (!stub && bins.pg_ctl && fs.existsSync(p.pgData)) {
    const r = (this._spawnSync || cp.spawnSync)(bins.pg_ctl, ['status', '-D', p.pgData], {
      encoding: 'utf8',
      env: scrubEnv(process.env),
      timeout: this._binProbeTimeoutMs,
    })
    running = !r.error && r.status === 0
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
  this._cleanupInitPwfile()
  const bins = this.hasBinaries()
  if (!bins.initdb || !bins.pg_ctl) {
    return { ok: false, stub: true, reason: 'PostgreSQL binaries not found (set KKMAIL_PG_BIN)' }
  }
  if (fs.existsSync(path.join(p.pgData, 'PG_VERSION'))) {
    return { ok: true, initialized: false, pgData: p.pgData }
  }
  fs.mkdirSync(p.pgData, { recursive: true, mode: 0o700 })
  try { fs.chmodSync(p.pgData, 0o700) } catch (_) {}
  const pwFile = path.join(p.secrets, 'pg-pwfile-init')
  let r
  try {
    fs.writeFileSync(pwFile, this.password(), { encoding: 'utf8', mode: 0o600 })
    r = (this._spawnSync || cp.spawnSync)(
      bins.initdb,
      ['-D', p.pgData, '-U', this.user, '--pwfile', pwFile, '-A', 'scram-sha-256', '--locale=C', '--encoding=UTF8'],
      { encoding: 'utf8', env: scrubEnv(process.env), timeout: 120000 },
    )
  } finally {
    try { fs.unlinkSync(pwFile) } catch (_) { /* ignore */ }
  }
  if (!r || r.error || r.status !== 0) {
    return { ok: false, stub: false, reason: (r && (r.stderr || r.stdout)) || (r && r.error && r.error.message) || 'initdb failed' }
  }
  // Listen on loopback only; port already validated by parsePgPort.
  const conf = path.join(p.pgData, 'postgresql.conf')
  const configured = reconcilePostgresConfig(conf, this.port)
  if (!configured.ok) return configured
  return { ok: true, initialized: true, pgData: p.pgData }
}

PostgresManager.prototype.start = function start() {
  this._stopped = false
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
  if (st.running) {
    const actual = runningPostmasterSettings(this.paths().pgData)
    if (actual?.port !== this.port || actual?.listenAddresses !== '127.0.0.1') {
      return {
        ok: false,
        reason: `PostgreSQL settings mismatch: configured_port=${this.port}, actual_port=${actual?.port ?? 'unknown'}, configured_listen_addresses=127.0.0.1, actual_listen_addresses=${actual?.listenAddresses ?? 'unknown'}. Stop the running cluster before changing KKMAIL_PG_PORT or listen_addresses.`,
      }
    }
    const configured = reconcilePostgresConfig(path.join(this.paths().pgData, 'postgresql.conf'), this.port)
    if (!configured.ok) return configured
    const bins = this.hasBinaries()
    const created = this.ensureDatabase(bins)
    if (!created.ok) return created
    return { ok: true, alreadyRunning: true, ...this.status() }
  }
  const init = this.initIfNeeded()
  if (!init.ok) return init
  const bins = this.hasBinaries()
  const p = this.paths()
  const configured = reconcilePostgresConfig(path.join(p.pgData, 'postgresql.conf'), this.port)
  if (!configured.ok) return configured
  try {
    const { rotateLogFile } = require('./logRotation')
    rotateLogFile(p.logFile)
  } catch (_) {}
  const r = (this._spawnSync || cp.spawnSync)(
    bins.pg_ctl,
    ['start', '-D', p.pgData, '-l', p.logFile, '-w'],
    { encoding: 'utf8', env: scrubEnv(process.env, { PGPORT: String(this.port) }), timeout: 60000 },
  )
  if (r.error || r.status !== 0) {
    return { ok: false, reason: (r.stderr || r.stdout) || (r.error && r.error.message) || 'pg_ctl start failed' }
  }
  const created = this.ensureDatabase(bins)
  if (!created.ok) return created
  return { ok: true, started: true, ...this.status() }
}

/** Create the application database once (initdb only creates `postgres`). */
PostgresManager.prototype.ensureDatabase = function ensureDatabase(bins) {
  const marker = path.join(this.dataRoot, 'secrets', 'db-created')
  if (fs.existsSync(marker)) return { ok: true }
  if (!bins.createdb) return { ok: false, reason: 'createdb binary not found next to pg_ctl' }
  const r = (this._spawnSync || cp.spawnSync)(
    bins.createdb,
    ['-h', '127.0.0.1', '-p', String(this.port), '-U', this.user, this.database],
    { encoding: 'utf8', env: scrubEnv(process.env, { PGPASSWORD: this.password() }), timeout: 30000 },
  )
  const out = `${r.stderr || ''}${r.stdout || ''}`
  if ((r.error || r.status !== 0) && !/already exists/.test(out)) {
    return { ok: false, reason: out || (r.error && r.error.message) || 'createdb failed' }
  }
  fs.writeFileSync(marker, new Date().toISOString() + '\n', { mode: 0o600 })
  return { ok: true }
}

/**
 * Stop the cluster. Idempotent on success: repeat calls after success are no-ops.
 * On failure: returns stopped: false, does not mark _stopped, and retains references for retry.
 */
PostgresManager.prototype.stop = function stop() {
  if (this._stopped) return { ok: true, stopped: true, alreadyStopped: true }
  const bins = this.hasBinaries()
  const p = this.paths()
  if (!bins.pg_ctl || !fs.existsSync(p.pgData)) {
    if (this._child) {
      try { this._child.kill('SIGTERM') } catch (_) { /* ignore */ }
      this._child = null
    }
    this._stopped = true
    return { ok: true, stub: !bins.pg_ctl, stopped: true }
  }
  const r = (this._spawnSync || cp.spawnSync)(bins.pg_ctl, ['stop', '-D', p.pgData, '-m', 'fast', '-w'], {
    encoding: 'utf8',
    env: scrubEnv(process.env),
    timeout: 30000,
  })
  const success = !r.error && r.status === 0
  if (success) {
    this._stopped = true
    if (this._child) {
      this._child = null
    }
    return { ok: true, stopped: true, detail: (r.stderr || r.stdout) || null }
  }
  return {
    ok: false,
    stopped: false,
    detail: (r.stderr || r.stdout) || (r.error && r.error.message) || 'pg_ctl stop failed',
  }
}

module.exports = {
  DEFAULT_PORT,
  BIN_PROBE_TIMEOUT_MS,
  PostgresManager,
  defaultMailDataRoot,
  defaultVendorBinDir,
  resolveBin,
  parsePgPort,
}
