/** Port / health / child-process helpers for the Electron main process (unit-testable). */
const http = require('http')
const net = require('net')
const { spawn } = require('child_process')

const DEFAULT_PORT = 18765

/** Exact env keys the mail-core / PG children may inherit from the parent. */
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
  'PYTHONPATH',
  'PYTHONHOME',
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
  'LD_LIBRARY_PATH',
  'DYLD_LIBRARY_PATH',
  'DYLD_FALLBACK_LIBRARY_PATH',
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
  const expectedToken = opts.instanceToken

  return new Promise((resolve, reject) => {
    const tick = () => {
      const stopErr = shouldStop()
      if (stopErr) {
        reject(stopErr)
        return
      }
      const headers = expectedToken ? { 'X-Instance-Token': expectedToken } : {}
      const req = http.get(url, { headers }, (res) => {
        res.resume()
        const tokenMatch = !expectedToken || res.headers['x-instance-token'] === expectedToken
        if (isOkStatus(res.statusCode) && tokenMatch) {
          resolve(true)
          return
        }
        if (Date.now() - started > timeoutMs) {
          const detail = !tokenMatch ? 'instance token mismatch' : `bad status ${res.statusCode}`
          reject(new Error(`backend health ${detail}`))
        } else {
          setTimeout(tick, 300)
        }
      })
      req.setTimeout(requestTimeoutMs, () => {
        req.destroy(new Error('health request timeout'))
      })
      req.on('error', () => {
        if (Date.now() - started > timeoutMs) reject(new Error('backend timeout'))
        else setTimeout(tick, 300)
      })
    }
    tick()
  })
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
  stopChildTree,
}
