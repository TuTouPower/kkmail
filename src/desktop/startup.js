/** Port / health / child-process helpers for the Electron main process (unit-testable). */
const http = require('http')
const net = require('net')
const { spawn, spawnSync } = require('child_process')

const DEFAULT_PORT = 18765

/**
 * Exact env keys the mail-core / PG children may inherit from the parent.
 * A128: code-execution / library-injection keys (PYTHONPATH, PYTHONHOME,
 * LD_*, DYLD_*) are deliberately NOT inherited — a polluted parent shell
 * could otherwise inject code or libraries into both children. A
 * launcher that genuinely needs one must pass it explicitly via
 * scrubEnv's `extras` argument, where the choice is visible at the
 * call site.
 */
const ENV_ALLOW_EXACT = new Set([
  'PATH',
  'PATHEXT',
  'HOME',
  'USER',
  'USERPROFILE',
  'USERNAME',
  'LOGNAME',
  'TMP',
  'TEMP',
  'TMPDIR',
  'LANG',
  'LANGUAGE',
  'TZ',
  'DISPLAY',
  'SystemRoot',
  'SYSTEMROOT',
  'WINDIR',
  'ComSpec',
  'COMSPEC',
  'APPDATA',
  'LOCALAPPDATA',
  'PROGRAMDATA',
  'ProgramData',
  'ProgramFiles',
  'ProgramFiles(x86)',
  'PROGRAMFILES',
  'PROGRAMFILES(X86)',
  'PYTHONNOUSERSITE',
  'PYTHONUTF8',
  'PYTHONIOENCODING',
  'PYTHON',
  'SSL_CERT_FILE',
  'SSL_CERT_DIR',
  'REQUESTS_CA_BUNDLE',
  'CURL_CA_BUNDLE',
  'HTTP_PROXY',
  'HTTPS_PROXY',
  'NO_PROXY',
  'http_proxy',
  'https_proxy',
  'no_proxy',
  'XDG_DATA_HOME',
  'XDG_CONFIG_HOME',
  'XDG_CACHE_HOME',
  'XDG_RUNTIME_DIR',
])

const ENV_ALLOW_PREFIX = ['LC_']

/**
 * Controlled configuration keys accepted by mail-core sidecar when explicitly passed from desktop.
 * Unrelated/arbitrary secrets in the parent shell must not leak into children.
 */
const SIDECAR_CONFIG_KEYS = new Set([
  'MAIL_CORE_HOST',
  'MAIL_CORE_PORT',
  'MAIL_CORE_DATA_DIR',
  'MAIL_CORE_DATABASE_URL',
  'MAIL_CORE_SECRET_KEY',
  'MAIL_CORE_LOGIN_PASSWORD',
  'MAIL_CORE_LOGIN_PASSWORD_HASH',
  'MAIL_CORE_API_KEYS',
  'MAIL_CORE_BLOB_KEY_V1',
  'MAIL_CORE_BLOB_KEYS',
  'MAIL_CORE_BLOB_ACTIVE_VERSION',
  'MAIL_CORE_BLOB_ROOT',
  'MAIL_CORE_BACKUP_KEY',
  'MAIL_CORE_BACKUP_KEYS',
  'MAIL_CORE_BACKUP_KEY_VERSION',
  'MAIL_CORE_BACKUP_DIR',
  'MAIL_CORE_EMBEDDED_WORKER',
  'MAIL_CORE_SKIP_MIGRATIONS',
  'MAIL_CORE_PROXY_HEADERS',
  'MAIL_CORE_FORWARDED_ALLOW_IPS',
  'MAIL_CORE_DB_POOL_SIZE',
  'MAIL_CORE_DB_MAX_OVERFLOW',
  'MAIL_CORE_DB_POOL_TIMEOUT',
  'MAIL_CORE_DB_POOL_RECYCLE',
  'MAIL_CORE_WORKER_POLL_S',
  'MAIL_CORE_WORKER_MAX_IDLE_S',
  'MAIL_CORE_COOKIE_SECURE',
  'MAIL_CORE_COOKIE_SAMESITE',
  'MAIL_CORE_SESSION_MAX_AGE',
  'MAIL_CORE_LOGIN_MAX_FAILURES',
  'MAIL_CORE_LOGIN_WINDOW_S',
  'MAIL_CORE_LOG_LEVEL',
  'MAIL_CORE_PUBLIC_ORIGIN',
  'MAIL_CORE_ALLOW_LOOPBACK_OAUTH_ORIGIN',
  'MAIL_CORE_ALLOW_PRIVATE_HOSTS',
  'MAIL_CORE_ALLOW_TEST_PROVIDERS',
  'MAIL_CORE_TOTAL_SLOTS',
  'MAIL_CORE_BACKGROUND_START_SLOT',
  'MAIL_CORE_CAPACITY_RETRY_SECONDS',
  'MAIL_CORE_MAX_MIME_BYTES',
  'MAIL_CORE_MAX_ATTACHMENT_BYTES',
  'MAIL_CORE_ARCHIVE_RECENT_DAYS',
  'MAIL_CORE_ARCHIVE_BATCH',
  'MAIL_CORE_CLAIM_BATCH',
  'MAIL_CORE_RECLAIM_INTERVAL_S',
  'MAIL_CORE_INBOX_POLL_INTERVAL_S',
  'MAIL_CORE_SCHEDULE_INTERVAL_S',
  'KKMAIL_SIDECAR',
  'KKMAIL_INSTANCE_TOKEN',
  'KKMAIL_FRONTEND_DIST',
])

/**
 * Pick only audited sidecar config keys from parentEnv and merge with launcher baseExtras.
 */
function collectSidecarExtras(parentEnv, baseExtras = {}) {
  const out = { ...baseExtras }
  const src = parentEnv || {}
  for (const key of SIDECAR_CONFIG_KEYS) {
    if (src[key] !== undefined && out[key] === undefined) {
      out[key] = src[key]
    }
  }
  return out
}

/**
 * Build a child env from an allowlist of parent keys, then apply extras (overwrite).
 * Prevents leaking parent secrets (tokens, CI creds, shell history vars) into mail-core.
 */
function scrubEnv(parentEnv, extras = {}) {
  const out = {}
  const src = parentEnv || {}
  for (const key of Object.keys(src)) {
    if (ENV_ALLOW_EXACT.has(key) || ENV_ALLOW_PREFIX.some((p) => key.startsWith(p))) {
      const v = src[key]
      if (v != null) out[key] = v
    }
  }
  for (const [k, v] of Object.entries(extras || {})) {
    if (v == null) delete out[k]
    else out[k] = v
  }
  return out
}

/** Redact known secrets and URL userinfo from log lines. */
function redactSecrets(text, secrets = []) {
  let out = String(text == null ? '' : text)
  for (const secret of secrets) {
    if (!secret || String(secret).length < 4) continue
    const s = String(secret)
    out = out.split(s).join('[REDACTED]')
  }
  out = out.replace(/postgresql(\+[\w]+)?:\/\/[^\s"'<>]+/gi, 'postgresql://[REDACTED]')
  out = out.replace(/:\/\/[^/\s]*:[^@/\s]+@/g, '://[REDACTED]@')
  return out
}

function parsePort(raw, fallback = DEFAULT_PORT) {
  const n = Number(raw == null || raw === '' ? fallback : raw)
  if (!Number.isInteger(n) || n < 1 || n > 65535) {
    throw new Error(`KKMAIL_DESKTOP_PORT 无效（需要 1–65535 的整数）: ${raw}`)
  }
  return n
}

function tryListen(port, host = '127.0.0.1') {
  return new Promise((resolve) => {
    const srv = net.createServer()
    srv.once('error', () => resolve(null))
    srv.once('listening', () => {
      const { port: bound } = srv.address()
      srv.close(() => resolve(bound))
    })
    srv.listen(port, host)
  })
}

/**
 * Pick a port that is free *right now*.
 *
 * A301 — TOCTOU warning: this is a probe, NOT a reservation. tryListen
 * closes its server before returning, and the caller (main.js) only
 * spawns the backend — which is what actually binds the port — after
 * PostgreSQL has started. In that window any other local process can
 * take the port. Accepted residual race; the failure shapes are:
 *   - the backend cannot bind and exits: startBackend surfaces the
 *     child's exit via waitForHealth's shouldStop (后端已退出), not a
 *     freePort error;
 *   - another service takes the port and accepts connections:
 *     waitForHealth polls the wrong service until it rejects with
 *     "backend timeout" / a bad-status error.
 * Eliminating the race requires the backend to bind port 0 and report
 * the assigned port back to the launcher (a backend protocol change);
 * until that exists, treat the two failure shapes above as the
 * port-raced signature and retry the launch.
 */
async function freePort(preferred, host = '127.0.0.1') {
  const exact = await tryListen(preferred, host)
  if (exact) return exact
  const any = await tryListen(0, host)
  if (any) return any
  throw new Error(`无法绑定本地端口（首选 ${preferred}，系统分配也失败）`)
}

/**
 * Poll until /health returns 2xx/3xx. Each attempt has its own request timeout.
 */
function waitForHealth(url, timeoutMs = 30000, opts = {}) {
  const requestTimeoutMs = opts.requestTimeoutMs ?? 5000
  const isOkStatus = (code) => typeof code === 'number' && code >= 200 && code < 400
  const started = Date.now()
  const shouldStop = opts.shouldStop || (() => null)

  return new Promise((resolve, reject) => {
    // A356: once the promise settles (success, timeout, or shouldStop),
    // no retry may fire again. A deadline timer settles the timeout at
    // timeoutMs itself; every settle clears any pending retry tick, and
    // tick/callbacks check `settled` before issuing another request.
    let settled = false
    let retryTimer = null
    let deadlineTimer = null
    const settle = (fn, value) => {
      if (settled) return
      settled = true
      if (retryTimer) { clearTimeout(retryTimer); retryTimer = null }
      if (deadlineTimer) { clearTimeout(deadlineTimer); deadlineTimer = null }
      fn(value)
    }
    const succeed = () => settle(resolve, true)
    const fail = (err) => settle(reject, err)
    const scheduleRetry = () => {
      if (settled) return
      retryTimer = setTimeout(() => { retryTimer = null; tick() }, 300)
    }
    deadlineTimer = setTimeout(() => {
      deadlineTimer = null
      fail(new Error('backend timeout'))
    }, Math.max(0, timeoutMs))

    const tick = () => {
      if (settled) return
      const stopErr = shouldStop()
      if (stopErr) {
        fail(stopErr)
        return
      }
      if (Date.now() - started > timeoutMs) {
        fail(new Error('backend timeout'))
        return
      }
      // A386 (option B): the instance token travels only through the
      // private startup channel (the sidecar's spawn environment). It is
      // never sent in an HTTP request header nor expected back in a
      // response header; health is a plain status check, and the child
      // process handle (shouldStop / exit events) is what binds this
      // probe to the sidecar we spawned.
      const req = http.get(url, (res) => {
        res.resume()
        if (settled) return
        if (isOkStatus(res.statusCode)) {
          succeed()
          return
        }
        if (Date.now() - started > timeoutMs) {
          fail(new Error(`backend health bad status ${res.statusCode}`))
        } else {
          scheduleRetry()
        }
      })
      req.setTimeout(requestTimeoutMs, () => {
        req.destroy(new Error('health request timeout'))
      })
      req.on('error', () => {
        if (settled) return
        if (Date.now() - started > timeoutMs) fail(new Error('backend timeout'))
        else scheduleRetry()
      })
    }
    tick()
  })
}

/**
 * A153: what main.js should do when the backend child exits unexpectedly.
 * The crash path must not be bound to a window existing: on macOS the app
 * outlives its windows, and a dead backend with no quit leaves a zombie
 * whose `activate` reopen can only show a window that never connects.
 * The error dialog needs a live window to anchor to; quitting does not.
 */
function backendExitDisposition({ isQuitting = false, hasWindow = false } = {}) {
  if (isQuitting) return { quit: false, showDialog: false }
  return { quit: true, showDialog: Boolean(hasWindow) }
}

function isChildDead(child) {
  if (!child) return true
  if (child.exitCode !== null && child.exitCode !== undefined) return true
  if (child.signalCode !== null && child.signalCode !== undefined) return true
  if (child._kkmailExited) return true
  return false
}

/**
 * SIGTERM the child (process group on Unix when detached), then SIGKILL / taskkill /T after escalateAfterMs.
 * Idempotent: safe to call repeatedly; only the first call schedules escalation.
 */
function stopChildTree(child, opts = {}) {
  const escalateAfterMs = opts.escalateAfterMs ?? 4000
  const log = opts.log || (() => {})
  if (isChildDead(child)) {
    return { ok: true, alreadyDead: true }
  }
  if (typeof child.once === 'function') {
    child.once('exit', () => { child._kkmailExited = true })
    child.once('close', () => { child._kkmailExited = true })
  }
  if (child._kkmailStopping) return { ok: true, alreadyStopping: true }
  child._kkmailStopping = true
  const pid = child.pid
  const softKill = () => {
    try {
      if (process.platform === 'win32') {
        child.kill()
      } else if (pid) {
        try {
          process.kill(-pid, 'SIGTERM')
        } catch (_) {
          child.kill('SIGTERM')
        }
      }
    } catch (err) {
      log(`soft kill failed: ${err && err.message ? err.message : err}`)
    }
  }
  const hardKill = () => {
    if (isChildDead(child)) return
    try {
      if (process.platform === 'win32' && pid) {
        spawn('taskkill', ['/pid', String(pid), '/T', '/F'], { stdio: 'ignore', windowsHide: true })
      } else if (pid) {
        try {
          process.kill(-pid, 'SIGKILL')
        } catch (_) {
          try { child.kill('SIGKILL') } catch (__) { /* gone */ }
        }
      }
    } catch (err) {
      log(`hard kill failed: ${err && err.message ? err.message : err}`)
    }
  }
  softKill()
  const timer = setTimeout(hardKill, escalateAfterMs)
  if (typeof timer.unref === 'function') timer.unref()
  if (typeof child.once === 'function') {
    child.once('exit', () => clearTimeout(timer))
    child.once('close', () => clearTimeout(timer))
  }
  return { ok: true, pid, escalateAfterMs }
}

/** Synchronously force-stop a child tree when the process is already exiting. */
function forceKillChildTreeImmediately(child, options = {}) {
  if (isChildDead(child)) return { ok: true, alreadyDead: true }
  const pid = child && child.pid
  if (!pid) return { ok: false, reason: 'missing-pid' }
  const platform = options.platform || process.platform
  const killProcess = options.killProcess || process.kill
  const runSync = options.runSync || spawnSync

  if (platform === 'win32') {
    try {
      const result = runSync('taskkill', ['/pid', String(pid), '/T', '/F'], {
        stdio: 'ignore',
        windowsHide: true,
      })
      if (!result.error && result.status === 0) return { ok: true, pid }
    } catch (_) {
      // Fall through to the direct child kill.
    }
    try {
      child.kill()
      return { ok: true, pid, direct: true }
    } catch (error) {
      return { ok: false, pid, error }
    }
  }

  try {
    killProcess(-pid, 'SIGKILL')
    return { ok: true, pid }
  } catch (_) {
    try {
      child.kill('SIGKILL')
      return { ok: true, pid, direct: true }
    } catch (error) {
      return { ok: false, pid, error }
    }
  }
}

module.exports = {
  DEFAULT_PORT,
  ENV_ALLOW_EXACT,
  ENV_ALLOW_PREFIX,
  SIDECAR_CONFIG_KEYS,
  collectSidecarExtras,
  parsePort,
  tryListen,
  freePort,
  waitForHealth,
  scrubEnv,
  redactSecrets,
  isChildDead,
  backendExitDisposition,
  stopChildTree,
  forceKillChildTreeImmediately,
}
