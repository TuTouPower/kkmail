const assert = require('assert')
const fs = require('fs')
const os = require('os')
const path = require('path')
const { createStubIfNeeded } = require('./scripts/pack-linux')

const tmpRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'kkmail-pack-linux-test-'))

try {
  // Path 1: Pre-existing assets dir without index.html
  // Only the stub index.html should be created and removed; pre-existing assets must be preserved.
  {
    const distDir = path.join(tmpRoot, 'dist1')
    const assetsDir = path.join(distDir, 'assets')
    fs.mkdirSync(assetsDir, { recursive: true })
    const existingAsset = path.join(assetsDir, 'vendor.js')
    fs.writeFileSync(existingAsset, 'console.log("existing")')

    const stub = createStubIfNeeded(distDir)
    assert.strictEqual(stub.stubCreated, true)
    assert.strictEqual(stub.createdIndex, true)
    assert.strictEqual(stub.createdAssets, false, 'must not mark assets as created if already existed')
    assert.strictEqual(stub.createdDist, false, 'must not mark dist as created if already existed')
    assert.ok(fs.existsSync(path.join(distDir, 'index.html')))
    assert.ok(fs.existsSync(existingAsset))

    stub.cleanup()
    assert.strictEqual(fs.existsSync(path.join(distDir, 'index.html')), false, 'stub index.html must be deleted')
    assert.ok(fs.existsSync(existingAsset), 'pre-existing asset must NOT be deleted')
    assert.ok(fs.existsSync(assetsDir), 'pre-existing assets directory must NOT be deleted')
    assert.ok(fs.existsSync(distDir), 'pre-existing dist directory must NOT be deleted')
  }

  // Path 2: Builder missing path (soft-ok exit path)
  // When builder is missing, cleanup must remove only stub-created files/directories.
  {
    const distDir = path.join(tmpRoot, 'dist2')
    const stub = createStubIfNeeded(distDir)
    assert.strictEqual(stub.stubCreated, true)
    assert.strictEqual(stub.createdIndex, true)
    assert.strictEqual(stub.createdAssets, true)
    assert.strictEqual(stub.createdDist, true)
    assert.ok(fs.existsSync(path.join(distDir, 'index.html')))

    // Simulate builder missing: cleanup called before exit
    stub.cleanup()
    assert.strictEqual(fs.existsSync(distDir), false, 'newly created empty dist tree must be removed')

    // Now test builder missing when dist had other user files
    const distDirWithFiles = path.join(tmpRoot, 'dist2_preserved')
    fs.mkdirSync(distDirWithFiles, { recursive: true })
    const userFile = path.join(distDirWithFiles, 'custom.txt')
    fs.writeFileSync(userFile, 'do not delete')

    const stubPreserve = createStubIfNeeded(distDirWithFiles)
    assert.strictEqual(stubPreserve.createdDist, false)
    stubPreserve.cleanup()
    assert.ok(fs.existsSync(userFile), 'user files must survive builder-missing exit')
    assert.ok(fs.existsSync(distDirWithFiles), 'dist directory with user files must survive')
  }

  // Path 3: Packaging failure path
  // If electron-builder throws or fails, finally block cleans up only stubs without recursive rm of dist.
  {
    const distDir = path.join(tmpRoot, 'dist3')
    const assetsDir = path.join(distDir, 'assets')
    fs.mkdirSync(assetsDir, { recursive: true })
    const mainJs = path.join(assetsDir, 'main.bundle.js')
    const logo = path.join(distDir, 'logo.svg')
    fs.writeFileSync(mainJs, '// bundle')
    fs.writeFileSync(logo, '<svg></svg>')

    const stub = createStubIfNeeded(distDir)
    let packError = null
    try {
      // Simulate build failure
      throw new Error('electron-builder crashed or exited 1')
    } catch (err) {
      packError = err
    } finally {
      stub.cleanup()
    }

    assert.ok(packError != null)
    assert.strictEqual(fs.existsSync(path.join(distDir, 'index.html')), false, 'stub index.html must be cleaned up')
    assert.ok(fs.existsSync(mainJs), 'main.bundle.js must NOT be deleted on packaging failure')
    assert.ok(fs.existsSync(logo), 'logo.svg must NOT be deleted on packaging failure')
    assert.ok(fs.existsSync(assetsDir), 'assetsDir must NOT be deleted on packaging failure')
  }

  console.log('packLinux.test.js: ok')
} finally {
  fs.rmSync(tmpRoot, { recursive: true, force: true })
}
