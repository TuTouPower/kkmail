const assert = require('assert')
const fs = require('fs')
const path = require('path')
const http = require('http')
const { EventEmitter } = require('events')
const {
  parsePort,
  freePort,
  waitForHealth,
  scrubEnv,
  redactSecrets,
  stopChildTree,
  forceKillChildTreeImmediately,
  ENV_ALLOW_EXACT,
  ENV_ALLOW_PREFIX,
  SIDECAR_CONFIG_KEYS,
  collectSidecarExtras,
  backendExitDisposition,
} = require('./startup')

assert.strictEqual(parsePort(undefined), 18765)
assert.strictEqual(parsePort('8080'), 8080)
assert.throws(() => parsePort('0'), /KKMAIL_DESKTOP_PORT/)
assert.throws(() => parsePort('65536'), /KKMAIL_DESKTOP_PORT/)
assert.throws(() => parsePort('nope'), /KKMAIL_DESKTOP_PORT/)

// parsePort from KKMAIL_DESKTOP_PORT
{
  const portFromEnv = (env) => parsePort(env.KKMAIL_DESKTOP_PORT)
  assert.strictEqual(portFromEnv({ KKMAIL_DESKTOP_PORT: '9000' }), 9000)
  assert.strictEqual(portFromEnv({}), 18765)
}

// scrubEnv: drop secrets / odd keys; only system and LC_* allowed by default; extras required for app vars
{
  const cleaned = scrubEnv(
    {
      PATH: '/usr/bin',
      HOME: '/home/u',
      AWS_SECRET_ACCESS_KEY: 'should-not-leak',
      GITHUB_TOKEN: 'ghs_xxx',
      MAIL_CORE_HOST: 'old',
      MAIL_CORE_LEAK_SECRET: 'leaked-secret',
      KKMAIL_PARENT_SECRET: 'parent-secret',
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
  assert.strictEqual(cleaned.MAIL_CORE_LEAK_SECRET, undefined, 'unrelated MAIL_CORE_ keys must not leak via prefix')
  assert.strictEqual(cleaned.KKMAIL_PARENT_SECRET, undefined, 'unrelated KKMAIL_ keys must not leak via prefix')
  assert.strictEqual(cleaned.AWS_SECRET_ACCESS_KEY, undefined)
  assert.strictEqual(cleaned.GITHUB_TOKEN, undefined)
  assert.strictEqual(cleaned.RANDOM_JUNK, undefined)
  assert.ok(ENV_ALLOW_EXACT.has('PATH'))
  assert.deepStrictEqual(ENV_ALLOW_PREFIX, ['LC_'])
}

// freePort (A301): the TOCTOU race between probing a port free and the
// backend actually binding it is an accepted residual risk (eliminating
// it needs a backend bind-0/report-back protocol change). Guard that
// the race, its window, and its failure shapes stay documented at
// freePort so nobody mistakes the probe for a reservation.
{
  const src = fs.readFileSync(path.join(__dirname, 'startup.js'), 'utf8')
  const fnIdx = src.indexOf('async function freePort')
  assert.ok(fnIdx > 0)
  const docBlock = src.slice(Math.max(0, fnIdx - 2500), fnIdx)
  assert.match(docBlock, /TOCTOU/, 'freePort must carry a TOCTOU warning')
  assert.match(docBlock, /后端已退出/, 'the doc must name the backend-exit failure shape')
  assert.match(docBlock, /backend timeout/, 'the doc must name the health-timeout failure shape')
  assert.match(docBlock, /bind.*0|port 0/, 'the doc must name the bind-0 report-back fix direction')
}

// scrubEnv (A128): code-execution / library-injection variables must not
// be inherited from the parent environment — they would let a polluted
// parent shell inject code/libraries into the PG and mail-core children,
// contradicting scrubEnv's stated purpose. A launcher that genuinely
// needs one must pass it explicitly via extras.
{
  const cleaned = scrubEnv({
    PATH: '/usr/bin',
    PYTHONPATH: '/tmp/evil-python',
    PYTHONHOME: '/tmp/evil-python-home',
    LD_LIBRARY_PATH: '/tmp/evil-libs',
    LD_PRELOAD: '/tmp/evil.so',
    DYLD_LIBRARY_PATH: '/tmp/evil-dyld',
    DYLD_FALLBACK_LIBRARY_PATH: '/tmp/evil-dyld-fallback',
    DYLD_INSERT_LIBRARIES: '/tmp/evil.dylib',
  })
  assert.strictEqual(cleaned.PATH, '/usr/bin')
  for (const key of [
    'PYTHONPATH',
    'PYTHONHOME',
    'LD_LIBRARY_PATH',
    'LD_PRELOAD',
    'DYLD_LIBRARY_PATH',
    'DYLD_FALLBACK_LIBRARY_PATH',
    'DYLD_INSERT_LIBRARIES',
  ]) {
    assert.strictEqual(cleaned[key], undefined, `${key} must not be inherited via the allowlist`)
    assert.ok(!ENV_ALLOW_EXACT.has(key), `${key} must not be in ENV_ALLOW_EXACT`)
  }
  const withExtras = scrubEnv(
    { PATH: '/usr/bin', LD_LIBRARY_PATH: '/tmp/parent-libs' },
    { LD_LIBRARY_PATH: '/bundled/pgsql/lib' },
  )
  assert.strictEqual(withExtras.LD_LIBRARY_PATH, '/bundled/pgsql/lib', 'explicit launcher extras remain the sanctioned injection path')
}

// collectSidecarExtras: only audited sidecar config keys pass through; launcher baseExtras win
{
  const parentEnv = {
    MAIL_CORE_HOST: '192.168.1.100', // launcher baseExtras will override this
    MAIL_CORE_PUBLIC_ORIGIN: 'https://mail.example.test',
    MAIL_CORE_ALLOW_LOOPBACK_OAUTH_ORIGIN: '1',
    MAIL_CORE_LOG_LEVEL: 'DEBUG',     // audited key: should pass through
    MAIL_CORE_SECRET_KEY: 'custom-secret', // audited key: should pass through
    MAIL_CORE_RANDOM_UNAUDITED: 'forbidden', // not audited: must be dropped
    KKMAIL_SECRET_TOKEN: 'forbidden-token',   // not audited: must be dropped
    AWS_KEY: 'forbidden-aws',
  }
  const baseExtras = {
    MAIL_CORE_HOST: '127.0.0.1',
    MAIL_CORE_PORT: '18765',
    KKMAIL_SIDECAR: '1',
    KKMAIL_INSTANCE_TOKEN: 'instance-token-from-child-env',
  }
  const sidecarExtras = collectSidecarExtras(parentEnv, baseExtras)
  assert.strictEqual(sidecarExtras.MAIL_CORE_HOST, '127.0.0.1', 'baseExtras must win')
  assert.strictEqual(sidecarExtras.MAIL_CORE_PORT, '18765')
  assert.strictEqual(sidecarExtras.KKMAIL_SIDECAR, '1')
  assert.strictEqual(sidecarExtras.KKMAIL_INSTANCE_TOKEN, 'instance-token-from-child-env')
  assert.strictEqual(sidecarExtras.MAIL_CORE_PUBLIC_ORIGIN, 'https://mail.example.test')
  assert.strictEqual(sidecarExtras.MAIL_CORE_ALLOW_LOOPBACK_OAUTH_ORIGIN, '1')
  assert.ok(SIDECAR_CONFIG_KEYS.has('MAIL_CORE_PUBLIC_ORIGIN'))
  assert.ok(SIDECAR_CONFIG_KEYS.has('MAIL_CORE_ALLOW_LOOPBACK_OAUTH_ORIGIN'))
  assert.strictEqual(sidecarExtras.MAIL_CORE_LOG_LEVEL, 'DEBUG')
  assert.strictEqual(sidecarExtras.MAIL_CORE_SECRET_KEY, 'custom-secret')
  assert.strictEqual(sidecarExtras.MAIL_CORE_RANDOM_UNAUDITED, undefined)
  assert.strictEqual(sidecarExtras.KKMAIL_SECRET_TOKEN, undefined)
  assert.strictEqual(sidecarExtras.AWS_KEY, undefined)

  const finalEnv = scrubEnv(parentEnv, sidecarExtras)
  assert.strictEqual(finalEnv.MAIL_CORE_HOST, '127.0.0.1')
  assert.strictEqual(finalEnv.KKMAIL_INSTANCE_TOKEN, 'instance-token-from-child-env')
  assert.strictEqual(finalEnv.MAIL_CORE_LOG_LEVEL, 'DEBUG')
  assert.strictEqual(finalEnv.MAIL_CORE_SECRET_KEY, 'custom-secret')
  assert.strictEqual(finalEnv.MAIL_CORE_RANDOM_UNAUDITED, undefined)
  assert.strictEqual(finalEnv.KKMAIL_SECRET_TOKEN, undefined)
  assert.strictEqual(finalEnv.AWS_KEY, undefined)
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
  // The process-exit fallback must force-kill synchronously after the soft shutdown attempt.
  const signals = []
  const child = { pid: 424242, exitCode: null, signalCode: null, kill: (signal) => signals.push(['child', signal]) }
  const result = forceKillChildTreeImmediately(child, {
    platform: 'linux',
    killProcess: (pid, signal) => signals.push([pid, signal]),
  })
  assert.ok(result.ok)
  assert.deepStrictEqual(signals, [[-424242, 'SIGKILL']])

  let taskkill = null
  const windowsResult = forceKillChildTreeImmediately(child, {
    platform: 'win32',
    runSync: (...args) => { taskkill = args; return { status: 0 } },
  })
  assert.ok(windowsResult.ok)
  assert.deepStrictEqual(taskkill, [
    'taskkill', ['/pid', '424242', '/T', '/F'], { stdio: 'ignore', windowsHide: true },
  ])
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

// A153: a backend exit must quit the app even when no window exists
// (macOS window-all-closed keeps the app alive; binding the crash path to
// mainWindow turned it into a zombie with a dead backendUrl). The error
// dialog is only shown when a window exists to anchor it.
assert.strictEqual(typeof backendExitDisposition, 'function', 'startup.js must export backendExitDisposition')
assert.deepStrictEqual(backendExitDisposition({ isQuitting: false, hasWindow: true }), { quit: true, showDialog: true })
assert.deepStrictEqual(backendExitDisposition({ isQuitting: false, hasWindow: false }), { quit: true, showDialog: false })
assert.deepStrictEqual(backendExitDisposition({ isQuitting: true, hasWindow: true }), { quit: false, showDialog: false })
assert.deepStrictEqual(backendExitDisposition({ isQuitting: true, hasWindow: false }), { quit: false, showDialog: false })
assert.deepStrictEqual(backendExitDisposition({}), { quit: true, showDialog: false })

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

  // Health: A386 — no instance-token header exchange in either
  // direction. The probe must succeed against a plain 200 that echoes
  // nothing, and the request itself must not carry X-Instance-Token
  // (the token only travels via the sidecar's spawn environment).
  let sawInstanceTokenHeader = false
  const plainServer = http.createServer((req, res) => {
    if (req.headers['x-instance-token'] !== undefined) sawInstanceTokenHeader = true
    res.statusCode = 200
    res.end()
  })
  await new Promise((r) => plainServer.listen(0, '127.0.0.1', r))
  const plainPort = plainServer.address().port
  await waitForHealth(`http://127.0.0.1:${plainPort}/health`, 3000, {
    requestTimeoutMs: 500,
  })
  assert.strictEqual(sawInstanceTokenHeader, false, 'health probe must not send X-Instance-Token')
  plainServer.close()

  console.log('desktop startup: ok')
})().catch((err) => {
  console.error(err)
  process.exit(1)
})
