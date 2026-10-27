const assert = require('assert')
const fs = require('fs')
const os = require('os')
const path = require('path')
const cp = require('child_process')
const {
  PostgresManager,
  defaultMailDataRoot,
  parsePgPort,
} = require('./postgresManager')

function testDefaultDataRootOutsideInstall() {
  const fakeApp = {
    getPath(name) {
      assert.strictEqual(name, 'userData')
      return path.join(os.tmpdir(), 'kkmail-user-data-test')
    },
  }
  const root = defaultMailDataRoot(fakeApp)
  assert.ok(root.includes('mail-core-data'))
  assert.ok(!root.includes(`${path.sep}Resources${path.sep}`))
  assert.ok(!root.includes('app.asar'))
}

function testFallbackDataRootNotSharedTmp() {
  const root = defaultMailDataRoot(null)
  // Must not be exactly /tmp/.kkmail/... (world-shared); prefer home or per-uid tmp.
  assert.ok(!root.startsWith(`/tmp${path.sep}.kkmail`), `shared /tmp fallback forbidden: ${root}`)
  assert.ok(root.includes('mail-core-data'))
}

function testParsePgPort() {
  assert.strictEqual(parsePgPort(undefined), 54329)
  assert.strictEqual(parsePgPort('5432'), 5432)
  assert.throws(() => parsePgPort('0'), /KKMAIL_PG_PORT/)
  assert.throws(() => parsePgPort('65536'), /KKMAIL_PG_PORT/)
  assert.throws(() => parsePgPort('nope'), /KKMAIL_PG_PORT/)
  assert.throws(() => parsePgPort(1.5), /KKMAIL_PG_PORT/)
}

function testPasswordPersisted0600() {
  const dataRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'kkmail-pg-pw-'))
  const mgr = new PostgresManager({ dataRoot, pgBinDir: path.join(dataRoot, 'missing-bin') })
  const a = mgr.password()
  assert.ok(a && a.length >= 32)
  const file = path.join(dataRoot, 'secrets', 'pg-password')
  assert.ok(fs.existsSync(file))
  const mode = fs.statSync(file).mode & 0o777
  assert.strictEqual(mode, 0o600)
  const mgr2 = new PostgresManager({ dataRoot, pgBinDir: path.join(dataRoot, 'missing-bin') })
  assert.strictEqual(mgr2.password(), a)
  assert.notStrictEqual(a, 'kkmail')
  fs.rmSync(dataRoot, { recursive: true, force: true })
}

function testPasswordOverridePersisted0600() {
  const dataRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'kkmail-pg-pw-override-'))
  const override = 'operator-supplied-pg-password'
  const file = path.join(dataRoot, 'secrets', 'pg-password')
  const originalOverride = process.env.KKMAIL_PG_PASSWORD
  try {
    process.env.KKMAIL_PG_PASSWORD = override
    const mgr = new PostgresManager({ dataRoot, pgBinDir: path.join(dataRoot, 'missing-bin') })
    assert.strictEqual(mgr.password(), override)
    assert.strictEqual(fs.readFileSync(file, 'utf8').trim(), override)
    if (process.platform !== 'win32') assert.strictEqual(fs.statSync(file).mode & 0o777, 0o600)

    delete process.env.KKMAIL_PG_PASSWORD
    const nextLaunch = new PostgresManager({ dataRoot, pgBinDir: path.join(dataRoot, 'missing-bin') })
    assert.strictEqual(nextLaunch.password(), override)
  } finally {
    if (originalOverride === undefined) delete process.env.KKMAIL_PG_PASSWORD
    else process.env.KKMAIL_PG_PASSWORD = originalOverride
    fs.rmSync(dataRoot, { recursive: true, force: true })
  }
}

// REPLACED (A21): the previous version of this test asserted that a
// password override wins over an already-persisted password file. That
// is the bug A21 fixes: the override was returned (and used to build
// databaseUrl()/PGPASSWORD) without ever being persisted, while the
// running cluster had been initialized with the persisted password, so
// every connection silently used the wrong password. The override may
// only take effect when it is persisted on first use; once a password
// file exists, the persisted value is authoritative.
function testPasswordOverrideReturnsPersistedValueWhenFileExists() {
  const dataRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'kkmail-pg-pw-existing-'))
  const file = path.join(dataRoot, 'secrets', 'pg-password')
  try {
    const existing = new PostgresManager({ dataRoot, pgBinDir: path.join(dataRoot, 'missing-bin') }).password()
    const override = new PostgresManager({
      dataRoot,
      pgBinDir: path.join(dataRoot, 'missing-bin'),
      password: 'temporary-override',
    })

    assert.strictEqual(override.password(), existing, 'override must not shadow the persisted password')
    assert.strictEqual(fs.readFileSync(file, 'utf8').trim(), existing)
    assert.ok(
      override.databaseUrl().includes(`:${encodeURIComponent(existing)}@`),
      'databaseUrl must be built from the persisted password, not the override',
    )
    assert.strictEqual(
      new PostgresManager({ dataRoot, pgBinDir: path.join(dataRoot, 'missing-bin') }).password(),
      existing,
    )
  } finally {
    fs.rmSync(dataRoot, { recursive: true, force: true })
  }
}

function testPasswordCreationRaceUsesFirstWriterValue() {
  const originalOverride = process.env.KKMAIL_PG_PASSWORD
  delete process.env.KKMAIL_PG_PASSWORD
  try {
    for (const password of [undefined, 'losing-override']) {
      const dataRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'kkmail-pg-pw-race-'))
      const file = path.join(dataRoot, 'secrets', 'pg-password')
      const originalWriteFileSync = fs.writeFileSync
      try {
        const mgr = new PostgresManager({
          dataRoot,
          pgBinDir: path.join(dataRoot, 'missing-bin'),
          password,
        })
        fs.writeFileSync = function simulateConcurrentCreate(filePath, data, options) {
          if (filePath === file && options && options.flag === 'wx') {
            originalWriteFileSync(filePath, 'first-writer-password\n', options)
            const error = new Error('file already exists')
            error.code = 'EEXIST'
            throw error
          }
          return originalWriteFileSync.apply(this, arguments)
        }

        assert.strictEqual(mgr.password(), 'first-writer-password')
        assert.strictEqual(fs.readFileSync(file, 'utf8').trim(), 'first-writer-password')
      } finally {
        fs.writeFileSync = originalWriteFileSync
        fs.rmSync(dataRoot, { recursive: true, force: true })
      }
    }
  } finally {
    if (originalOverride === undefined) delete process.env.KKMAIL_PG_PASSWORD
    else process.env.KKMAIL_PG_PASSWORD = originalOverride
  }
}

function testEnsureDirsWritesMarker() {
  const dataRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'kkmail-pg-'))
  const mgr = new PostgresManager({ dataRoot, pgBinDir: path.join(dataRoot, 'missing-bin') })
  const paths = mgr.ensureDirs()
  assert.ok(fs.existsSync(paths.blobs))
  assert.ok(fs.existsSync(paths.secrets))
  assert.ok(fs.existsSync(paths.backups))
  if (process.platform !== 'win32') {
    assert.strictEqual(fs.statSync(paths.dataRoot).mode & 0o777, 0o700)
    assert.strictEqual(fs.statSync(paths.blobs).mode & 0o777, 0o700)
    assert.strictEqual(fs.statSync(paths.backups).mode & 0o777, 0o700)
    assert.strictEqual(fs.statSync(paths.secrets).mode & 0o777, 0o700)
  }
  assert.ok(fs.existsSync(path.join(paths.dataRoot, 'README-DO-NOT-DELETE.txt')))
  const status = mgr.status()
  assert.strictEqual(status.stub, true)
  const start = mgr.start()
  assert.strictEqual(start.stub, true)
  assert.ok(start.dataRoot)
  fs.rmSync(dataRoot, { recursive: true, force: true })
}

function testHasBinariesCachesAndTimeout() {
  const dataRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'kkmail-pg-cache-'))
  const mgr = new PostgresManager({
    dataRoot,
    pgBinDir: path.join(dataRoot, 'missing-bin'),
    binProbeTimeoutMs: 100,
  })
  const a = mgr.hasBinaries()
  const b = mgr.hasBinaries()
  assert.strictEqual(a, b, 'hasBinaries must return cached object')
  assert.strictEqual(a.initdb, null)
  assert.strictEqual(a.pg_ctl, null)
  fs.rmSync(dataRoot, { recursive: true, force: true })
}

function testHasBinariesProbesPathOncePerBinary() {
  const dataRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'kkmail-pg-probe-once-'))
  const counts = {}
  const mgr = new PostgresManager({
    dataRoot,
    pgBinDir: path.join(dataRoot, 'missing-bin'),
    spawnSync: (bin) => {
      counts[bin] = (counts[bin] || 0) + 1
      return { error: null, status: 0, stdout: '', stderr: '' }
    },
  })
  try {
    const bins = mgr.hasBinaries()
    assert.deepStrictEqual(bins, {
      initdb: 'initdb',
      pg_ctl: 'pg_ctl',
      postgres: 'postgres',
      createdb: 'createdb',
    })
    assert.deepStrictEqual(
      counts,
      { initdb: 1, pg_ctl: 1, postgres: 1, createdb: 1 },
      'each PATH binary must be probed exactly once, not once via the hint fallback and once via PATH',
    )
  } finally {
    fs.rmSync(dataRoot, { recursive: true, force: true })
  }
}

function testStatusCachesPgCtlProbeWithinTtl() {
  const dataRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'kkmail-pg-status-cache-'))
  const pgData = path.join(dataRoot, 'pgdata')
  fs.mkdirSync(pgData, { recursive: true })
  let statusProbes = 0
  const mgr = new PostgresManager({
    dataRoot,
    pgBinDir: path.join(dataRoot, 'bin'),
    spawnSync: (_cmd, args) => {
      if (args[0] === 'status') statusProbes++
      return { error: null, status: 0, stdout: 'server is running', stderr: '' }
    },
  })
  mgr._binsCache = {
    initdb: '/fake/bin/initdb',
    pg_ctl: '/fake/bin/pg_ctl',
    postgres: '/fake/bin/postgres',
    createdb: '/fake/bin/createdb',
  }
  try {
    const a = mgr.status()
    const b = mgr.status()
    assert.strictEqual(a.running, true)
    assert.strictEqual(b.running, true)
    assert.strictEqual(statusProbes, 1, 'consecutive status() calls within the TTL must not re-spawn pg_ctl status')
  } finally {
    fs.rmSync(dataRoot, { recursive: true, force: true })
  }
}

function testStartAlreadyRunningProbesStatusOnce() {
  const dataRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'kkmail-pg-start-status-once-'))
  const pgData = path.join(dataRoot, 'pgdata')
  const secrets = path.join(dataRoot, 'secrets')
  fs.mkdirSync(pgData, { recursive: true })
  fs.mkdirSync(secrets, { recursive: true })
  fs.writeFileSync(path.join(pgData, 'PG_VERSION'), '16\n')
  fs.writeFileSync(path.join(pgData, 'postgresql.conf'), "listen_addresses = '127.0.0.1'\nport = 55445\n")
  fs.writeFileSync(path.join(pgData, 'postmaster.pid'), `12345\n${pgData}\n0\n55445\n/tmp\n127.0.0.1\n`)
  fs.writeFileSync(path.join(secrets, 'db-created'), 'created\n')

  let statusProbes = 0
  const mgr = new PostgresManager({
    dataRoot,
    pgBinDir: path.join(dataRoot, 'bin'),
    port: 55445,
    spawnSync: (_cmd, args) => {
      if (args[0] === 'status') statusProbes++
      return { error: null, status: 0, stdout: 'server is running', stderr: '' }
    },
  })
  mgr._binsCache = {
    initdb: '/fake/bin/initdb',
    pg_ctl: '/fake/bin/pg_ctl',
    postgres: '/fake/bin/postgres',
    createdb: '/fake/bin/createdb',
  }
  try {
    const result = mgr.start()
    assert.strictEqual(result.ok, true, result.reason)
    assert.strictEqual(result.alreadyRunning, true)
    assert.strictEqual(statusProbes, 1, 'start() on an already-running cluster must reuse its entry status probe')
  } finally {
    fs.rmSync(dataRoot, { recursive: true, force: true })
  }
}

function testStopIdempotentNoThrowaway() {
  const dataRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'kkmail-pg-stop-'))
  const mgr = new PostgresManager({ dataRoot, pgBinDir: path.join(dataRoot, 'missing-bin') })
  const s1 = mgr.stop()
  assert.ok(s1.stopped || s1.ok)
  const s2 = mgr.stop()
  assert.strictEqual(s2.alreadyStopped, true)
  fs.rmSync(dataRoot, { recursive: true, force: true })
}

function testStartReconcilesManagedPortAfterInitialization() {
  const dataRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'kkmail-pg-port-reconcile-'))
  const pgData = path.join(dataRoot, 'pgdata')
  const secrets = path.join(dataRoot, 'secrets')
  fs.mkdirSync(pgData, { recursive: true })
  fs.mkdirSync(secrets, { recursive: true })
  fs.writeFileSync(path.join(pgData, 'PG_VERSION'), '16\n')
  const confPath = path.join(pgData, 'postgresql.conf')
  fs.writeFileSync(confPath, "# existing config\nlisten_addresses = '127.0.0.1'\nport = 54329\n")
  fs.writeFileSync(path.join(secrets, 'db-created'), 'created\n')

  let observedPortAtStart = null
  const mgr = new PostgresManager({
    dataRoot,
    pgBinDir: path.join(dataRoot, 'bin'),
    port: 55445,
    spawnSync: (_cmd, args) => {
      if (args[0] === 'status') return { error: null, status: 1, stdout: '', stderr: '' }
      if (args[0] === 'start') {
        const conf = fs.readFileSync(confPath, 'utf8')
        const matches = [...conf.matchAll(/^port\s*=\s*(\d+)/gm)]
        observedPortAtStart = Number(matches.at(-1)?.[1])
        return { error: null, status: 0, stdout: '', stderr: '' }
      }
      return { error: null, status: 0, stdout: '', stderr: '' }
    },
  })
  mgr._binsCache = {
    initdb: '/fake/bin/initdb',
    pg_ctl: '/fake/bin/pg_ctl',
    postgres: '/fake/bin/postgres',
    createdb: '/fake/bin/createdb',
  }

  try {
    const result = mgr.start()
    assert.strictEqual(result.ok, true, result.reason)
    assert.strictEqual(observedPortAtStart, 55445, 'config must be reconciled before pg_ctl starts')
    const conf = fs.readFileSync(confPath, 'utf8')
    assert.match(conf, /listen_addresses = '127\.0\.0\.1'/)
    assert.match(conf, /port = 55445/)
    assert.strictEqual((conf.match(/BEGIN kkmail managed PostgreSQL settings/g) || []).length, 1)
  } finally {
    fs.rmSync(dataRoot, { recursive: true, force: true })
  }
}

function testStartRejectsRunningClusterOnDifferentPort() {
  const dataRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'kkmail-pg-port-running-'))
  const pgData = path.join(dataRoot, 'pgdata')
  fs.mkdirSync(pgData, { recursive: true })
  fs.writeFileSync(path.join(pgData, 'PG_VERSION'), '16\n')
  fs.writeFileSync(path.join(pgData, 'postgresql.conf'), "listen_addresses = '127.0.0.1'\nport = 54329\n")
  fs.writeFileSync(path.join(pgData, 'postmaster.pid'), `12345\n${pgData}\n0\n54329\n/tmp\n127.0.0.1\n`)

  let databaseConnectionAttempted = false
  const mgr = new PostgresManager({
    dataRoot,
    pgBinDir: path.join(dataRoot, 'bin'),
    port: 55445,
    spawnSync: (_cmd, args) => {
      if (args[0] === 'status') return { error: null, status: 0, stdout: 'server is running', stderr: '' }
      databaseConnectionAttempted = true
      return { error: null, status: 0, stdout: '', stderr: '' }
    },
  })
  mgr._binsCache = {
    initdb: '/fake/bin/initdb',
    pg_ctl: '/fake/bin/pg_ctl',
    postgres: '/fake/bin/postgres',
    createdb: '/fake/bin/createdb',
  }

  try {
    const result = mgr.start()
    assert.strictEqual(result.ok, false)
    assert.match(result.reason, /configured_port=55445.*actual_port=54329/)
    assert.strictEqual(databaseConnectionAttempted, false, 'must not connect to a different service on the configured port')
  } finally {
    fs.rmSync(dataRoot, { recursive: true, force: true })
  }
}

function testStartRejectsRunningClusterOnNonLoopbackAddress() {
  const dataRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'kkmail-pg-listen-running-'))
  const pgData = path.join(dataRoot, 'pgdata')
  fs.mkdirSync(pgData, { recursive: true })
  fs.writeFileSync(path.join(pgData, 'PG_VERSION'), '16\n')
  fs.writeFileSync(path.join(pgData, 'postgresql.conf'), "listen_addresses = '*'\nport = 55445\n")
  fs.writeFileSync(path.join(pgData, 'postmaster.pid'), `12345\n${pgData}\n0\n55445\n/tmp\n0.0.0.0\n`)

  let databaseConnectionAttempted = false
  const mgr = new PostgresManager({
    dataRoot,
    pgBinDir: path.join(dataRoot, 'bin'),
    port: 55445,
    spawnSync: (_cmd, args) => {
      if (args[0] === 'status') return { error: null, status: 0, stdout: 'server is running', stderr: '' }
      databaseConnectionAttempted = true
      return { error: null, status: 0, stdout: '', stderr: '' }
    },
  })
  mgr._binsCache = {
    initdb: '/fake/bin/initdb',
    pg_ctl: '/fake/bin/pg_ctl',
    postgres: '/fake/bin/postgres',
    createdb: '/fake/bin/createdb',
  }

  try {
    const result = mgr.start()
    assert.strictEqual(result.ok, false)
    assert.match(result.reason, /configured_listen_addresses=127\.0\.0\.1.*actual_listen_addresses=0\.0\.0\.0/)
    assert.strictEqual(databaseConnectionAttempted, false, 'must not connect while the running server is bound beyond loopback')
  } finally {
    fs.rmSync(dataRoot, { recursive: true, force: true })
  }
}

function testInitPwfileCleanupLegacy() {
  const dataRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'kkmail-pg-pwfile-'))
  const mgr = new PostgresManager({ dataRoot, pgBinDir: path.join(dataRoot, 'missing-bin') })
  mgr.ensureDirs()
  const legacy = path.join(dataRoot, '.pgpass-init')
  const modern = path.join(dataRoot, 'secrets', 'pg-pwfile-init')
  fs.writeFileSync(legacy, 'leftover', { mode: 0o600 })
  fs.writeFileSync(modern, 'leftover', { mode: 0o600 })
  mgr._cleanupInitPwfile()
  assert.ok(!fs.existsSync(legacy))
  assert.ok(!fs.existsSync(modern))
  fs.rmSync(dataRoot, { recursive: true, force: true })
}

function testInvalidPortRejectedAtConstruct() {
  assert.throws(
    () => new PostgresManager({ dataRoot: '/tmp/x', port: 'abc' }),
    /KKMAIL_PG_PORT/,
  )
}

function testStopFailureAndRetry() {
  const dataRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'kkmail-pg-stop-retry-'))
  const pgData = path.join(dataRoot, 'pgdata')
  fs.mkdirSync(pgData, { recursive: true })

  let spawnCount = 0
  const mockSpawnSync = (cmd, args, opts) => {
    if (args && args[0] === 'stop') {
      spawnCount++
      if (spawnCount === 1) {
        // First stop attempt fails
        return { error: null, status: 1, stderr: 'pg_ctl: server does not shut down', stdout: '' }
      }
      // Second stop attempt succeeds
      return { error: null, status: 0, stderr: '', stdout: 'server stopped' }
    }
    return { error: null, status: 0, stdout: '', stderr: '' }
  }

  const mgr = new PostgresManager({
    dataRoot,
    pgBinDir: path.join(dataRoot, 'bin'),
    spawnSync: mockSpawnSync,
  })
  // Stub binaries cache so pg_ctl is present
  mgr._binsCache = {
    initdb: '/fake/bin/initdb',
    pg_ctl: '/fake/bin/pg_ctl',
    postgres: '/fake/bin/postgres',
    createdb: '/fake/bin/createdb',
  }
  const fakeChild = { killed: false, kill: () => {} }
  mgr._child = fakeChild

  try {
    // 1. First attempt fails: stopped=false, _stopped=false, child retained
    const r1 = mgr.stop()
    assert.strictEqual(r1.ok, false)
    assert.strictEqual(r1.stopped, false)
    assert.strictEqual(mgr._stopped, false)
    assert.strictEqual(mgr._child, fakeChild, 'child reference must be retained on stop failure')
    assert.match(r1.detail, /server does not shut down/)

    // 2. Retry succeeds: stopped=true, _stopped=true, child cleaned up
    const r2 = mgr.stop()
    assert.strictEqual(r2.ok, true)
    assert.strictEqual(r2.stopped, true)
    assert.strictEqual(mgr._stopped, true)
    assert.strictEqual(mgr._child, null)

    // 3. Repeat after success: alreadyStopped=true, no additional spawn
    const r3 = mgr.stop()
    assert.strictEqual(r3.alreadyStopped, true)
    assert.strictEqual(spawnCount, 2, 'spawnSync must not be called after alreadyStopped')
  } finally {
    fs.rmSync(dataRoot, { recursive: true, force: true })
  }
}

testDefaultDataRootOutsideInstall()
testFallbackDataRootNotSharedTmp()
testParsePgPort()
testEnsureDirsWritesMarker()
testPasswordPersisted0600()
testPasswordOverridePersisted0600()
testPasswordOverrideReturnsPersistedValueWhenFileExists()
testPasswordCreationRaceUsesFirstWriterValue()
testHasBinariesCachesAndTimeout()
testHasBinariesProbesPathOncePerBinary()
testStatusCachesPgCtlProbeWithinTtl()
testStartAlreadyRunningProbesStatusOnce()
testStopIdempotentNoThrowaway()
testStopFailureAndRetry()
testInitPwfileCleanupLegacy()
testInvalidPortRejectedAtConstruct()
testStartReconcilesManagedPortAfterInitialization()
testStartRejectsRunningClusterOnDifferentPort()
testStartRejectsRunningClusterOnNonLoopbackAddress()
console.log('postgresManager.test.js: ok')

function testVendorBinDirDefault() {
  const { defaultVendorBinDir } = require('./postgresManager')
  const d = defaultVendorBinDir()
  assert.ok(d.includes(`${path.sep}vendor${path.sep}pgsql${path.sep}bin`))
}

async function testRealBinarySmokeOrSkip() {
  const { freePort } = require('./startup')
  const dataRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'kkmail-pg-real-'))
  const vendorBin = path.join(__dirname, 'vendor', 'pgsql', 'bin')
  const port = await freePort(0)
  const mgr = new PostgresManager({
    dataRoot,
    pgBinDir: fs.existsSync(path.join(vendorBin, 'pg_ctl')) ? vendorBin : path.join(dataRoot, 'no-bin'),
    port,
  })
  const st = mgr.status()
  if (st.stub) {
    console.log('postgresManager.test.js: skip real start/stop (no PG binaries in vendor or PATH)')
    fs.rmSync(dataRoot, { recursive: true, force: true })
    return
  }
  const started = mgr.start()
  assert.ok(started.ok, started.reason || JSON.stringify(started))
  const stopped = mgr.stop()
  assert.ok(stopped.ok || stopped.stopped)
  const stopped2 = mgr.stop()
  assert.strictEqual(stopped2.alreadyStopped, true)
  fs.rmSync(dataRoot, { recursive: true, force: true })
  console.log('postgresManager.test.js: real start/stop smoke ok')
}

testVendorBinDirDefault()
testRealBinarySmokeOrSkip().catch((err) => {
  console.error(err)
  process.exit(1)
})
