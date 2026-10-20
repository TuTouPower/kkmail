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
console.log('postgresManager.test.js: ok')
