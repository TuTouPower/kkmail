const assert = require('assert')
const http = require('http')
const { parsePort, freePort, waitForHealth } = require('./startup')

assert.strictEqual(parsePort(undefined), 18765)
assert.strictEqual(parsePort('8080'), 8080)
assert.throws(() => parsePort('0'), /OUTLOOK_DESKTOP_PORT/)
assert.throws(() => parsePort('65536'), /OUTLOOK_DESKTOP_PORT/)
assert.throws(() => parsePort('nope'), /OUTLOOK_DESKTOP_PORT/)

;(async () => {
  const p = await freePort(0)
  assert.ok(p >= 1 && p <= 65535)

  // Health: reject non-2xx
  const bad = http.createServer((_req, res) => { res.statusCode = 500; res.end('no') })
  await new Promise((r) => bad.listen(0, '127.0.0.1', r))
  const badPort = bad.address().port
  let failed = false
  try {
    await waitForHealth(`http://127.0.0.1:${badPort}/health`, 800, { requestTimeoutMs: 200 })
  } catch (e) {
    failed = true
    assert.match(String(e.message), /timeout|bad status/)
  }
  assert.ok(failed, 'non-2xx health must fail')
  bad.close()

  // Health: accept 204
  const ok = http.createServer((_req, res) => { res.statusCode = 204; res.end() })
  await new Promise((r) => ok.listen(0, '127.0.0.1', r))
  const okPort = ok.address().port
  await waitForHealth(`http://127.0.0.1:${okPort}/health`, 3000, { requestTimeoutMs: 500 })
  ok.close()

  console.log('desktop startup: ok')
})().catch((err) => {
  console.error(err)
  process.exit(1)
})
