const assert = require('assert')
const fs = require('fs')
const os = require('os')
const path = require('path')
const { PostgresManager, defaultMailDataRoot } = require('./postgresManager')

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
  assert.ok(fs.existsSync(path.join(paths.dataRoot, 'README-DO-NOT-DELETE.txt')))
  const status = mgr.status()
  assert.strictEqual(status.stub, true)
  const start = mgr.start()
  assert.strictEqual(start.stub, true)
  assert.ok(start.dataRoot)
  // cleanup
  fs.rmSync(dataRoot, { recursive: true, force: true })
}

testDefaultDataRootOutsideInstall()
testEnsureDirsWritesMarker()
testPasswordPersisted0600()
console.log('postgresManager.test.js: ok')

function testVendorBinDirDefault() {
  const { defaultVendorBinDir } = require('./postgresManager')
  const d = defaultVendorBinDir()
  assert.ok(d.includes(`${path.sep}vendor${path.sep}pgsql${path.sep}bin`))
}

function testRealBinarySmokeOrSkip() {
  const dataRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'kkmail-pg-real-'))
  const vendorBin = path.join(__dirname, 'vendor', 'pgsql', 'bin')
  const mgr = new PostgresManager({
    dataRoot,
    pgBinDir: fs.existsSync(path.join(vendorBin, 'pg_ctl')) ? vendorBin : path.join(dataRoot, 'no-bin'),
    port: 55432,
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
  fs.rmSync(dataRoot, { recursive: true, force: true })
  console.log('postgresManager.test.js: real start/stop smoke ok')
}

testVendorBinDirDefault()
testRealBinarySmokeOrSkip()
