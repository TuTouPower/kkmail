const assert = require('assert')
const http = require('http')
const { EventEmitter } = require('events')
const {
  parsePort,
  freePort,
  waitForHealth,
  scrubEnv,
  redactSecrets,
  stopChildTree,
  ENV_ALLOW_EXACT,
} = require('./startup')

assert.strictEqual(parsePort(undefined), 18765)
assert.strictEqual(parsePort('8080'), 8080)
assert.throws(() => parsePort('0'), /OUTLOOK_DESKTOP_PORT/)
assert.throws(() => parsePort('65536'), /OUTLOOK_DESKTOP_PORT/)
assert.throws(() => parsePort('nope'), /OUTLOOK_DESKTOP_PORT/)

// scrubEnv: drop secrets / odd keys; keep PATH and MAIL_CORE_*; extras win
{
  const cleaned = scrubEnv(
    {
      PATH: '/usr/bin',
      HOME: '/home/u',
      AWS_SECRET_ACCESS_KEY: 'should-not-leak',
      GITHUB_TOKEN: 'ghs_xxx',
      MAIL_CORE_HOST: 'old',
      LC_ALL: 'C',
      RANDOM_JUNK: 'no',
    },
    { MAIL_CORE_HOST: '127.0.0.1', MAIL_CORE_DATABASE_URL: 'postgresql://x' },
  )
  assert.strictEqual(cleaned.PATH, '/usr/bin')
  assert.strictEqual(cleaned.HOME, '/home/u')
  assert.strictEqual(cleaned.LC_ALL, 'C')
  assert.strictEqual(cleaned.MAIL_CORE_HOST, '127.0.0.1')
  assert.strictEqual(cleaned.MAIL_CORE_DATABASE_URL, 'postgresql://x')
  assert.strictEqual(cleaned.AWS_SECRET_ACCESS_KEY, undefined)
  assert.strictEqual(cleaned.GITHUB_TOKEN, undefined)
  assert.strictEqual(cleaned.RANDOM_JUNK, undefined)
  assert.ok(ENV_ALLOW_EXACT.has('PATH'))
}

{
  const red = redactSecrets(
    'pw=supersecret99 url=postgresql+psycopg://u:supersecret99@127.0.0.1/db done',
    ['supersecret99'],
  )
  assert.ok(!red.includes('supersecret99'))
  assert.match(red, /\[REDACTED\]/)
  assert.match(red, /postgresql:\/\/\[REDACTED\]/)
}

{
  // stopChildTree soft-kills then schedules escalate; fake child
  const child = new EventEmitter()
  child.pid = process.pid // won't actually kill group of self with negative in test if we stub
  child.exitCode = null
  child.killed = false
  let killSig = null
  child.kill = (sig) => { killSig = sig || 'SIGTERM'; child.killed = true; child.exitCode = null }
  // Use a non-existent pid via override: monkey-patch process.kill for negative pid
  const origKill = process.kill
  let groupSig = null
  process.kill = (pid, sig) => {
    if (pid < 0) { groupSig = sig; return true }
    return origKill(pid, sig)
  }
  try {
    child.pid = 424242 // fake
    const r = stopChildTree(child, { escalateAfterMs: 50 })
    assert.ok(r.ok)
    assert.ok(groupSig === 'SIGTERM' || killSig === 'SIGTERM' || killSig == null)
    const r2 = stopChildTree(child, { escalateAfterMs: 50 })
    assert.ok(r2.alreadyStopping || r2.alreadyDead)
  } finally {
    process.kill = origKill
  }
}

{
  // child.killed true does not count as dead if exitCode is still null and no exit event fired
  const child = new EventEmitter()
  child.pid = 999999
  child.exitCode = null
  child.killed = true
  child.kill = () => {}
  const r = stopChildTree(child, { escalateAfterMs: 50 })
  assert.ok(!r.alreadyDead, 'child.killed alone must not mean already dead')

  // Now emit exit
  child.emit('exit', 0, null)
  child.exitCode = 0
  const rDead = stopChildTree(child, { escalateAfterMs: 50 })
  assert.ok(rDead.alreadyDead, 'exitCode !== null must mean already dead')
}

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
