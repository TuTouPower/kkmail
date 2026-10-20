/** Port / health helpers for the Electron main process (pure enough to unit-test). */
const http = require('http')
const net = require('net')

const DEFAULT_PORT = 18765

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

module.exports = {
  DEFAULT_PORT,
  parsePort,
  tryListen,
  freePort,
  waitForHealth,
}
