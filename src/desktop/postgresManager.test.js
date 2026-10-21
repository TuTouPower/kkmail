const assert = require('assert')
const fs = require('fs')
const os = require('os')
const path = require('path')
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

function testStopIdempotentNoThrowaway() {
  const dataRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'kkmail-pg-stop-'))
  const mgr = new PostgresManager({ dataRoot, pgBinDir: path.join(dataRoot, 'missing-bin') })
  const s1 = mgr.stop()
  assert.ok(s1.stopped || s1.ok)
  const s2 = mgr.stop()
  assert.strictEqual(s2.alreadyStopped, true)
  fs.rmSync(dataRoot, { recursive: true, force: true })
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

testDefaultDataRootOutsideInstall()
testFallbackDataRootNotSharedTmp()
testParsePgPort()
testEnsureDirsWritesMarker()
testPasswordPersisted0600()
testHasBinariesCachesAndTimeout()
testStopIdempotentNoThrowaway()
testInitPwfileCleanupLegacy()
testInvalidPortRejectedAtConstruct()
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
