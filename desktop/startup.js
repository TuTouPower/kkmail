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

const ENV_ALLOW_PREFIX = ['LC_', 'MAIL_CORE_', 'KKMAIL_']

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
    throw new Error(`OUTLOOK_DESKTOP_PORT 无效（需要 1–65535 的整数）: ${raw}`)
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

  return new Promise((resolve, reject) => {
    const tick = () => {
      const stopErr = shouldStop()
      if (stopErr) {
        reject(stopErr)
        return
      }
      const req = http.get(url, (res) => {
        res.resume()
        if (isOkStatus(res.statusCode)) {
          resolve(true)
          return
        }
        if (Date.now() - started > timeoutMs) {
          reject(new Error(`backend health bad status ${res.statusCode}`))
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

/**
 * SIGTERM the child (process group on Unix when detached), then SIGKILL / taskkill /T after escalateAfterMs.
 * Idempotent: safe to call repeatedly; only the first call schedules escalation.
 */
function stopChildTree(child, opts = {}) {
  const escalateAfterMs = opts.escalateAfterMs ?? 4000
  const log = opts.log || (() => {})
  if (!child || child.exitCode !== null || child.killed) {
    return { ok: true, alreadyDead: true }
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
    if (child.exitCode !== null || child.killed) return
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
  child.once('exit', () => clearTimeout(timer))
  return { ok: true, pid, escalateAfterMs }
}

module.exports = {
  DEFAULT_PORT,
  ENV_ALLOW_EXACT,
  ENV_ALLOW_PREFIX,
  parsePort,
  tryListen,
  freePort,
  waitForHealth,
  scrubEnv,
  redactSecrets,
  stopChildTree,
}
