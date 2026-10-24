const assert = require('assert')
const fs = require('fs')
const os = require('os')
const path = require('path')
const { spawnSync } = require('child_process')
const { canSoftExit, createStubIfNeeded } = require('./scripts/pack-linux')

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

  // Path 4: The CLI fails by default when electron-builder is missing and always cleans its stub.
  // Local soft-ok is explicit and unavailable to npm packaging scripts.
  {
    const fixtureRoot = path.join(tmpRoot, 'cli-missing-builder')
    const scriptPath = createPackFixture(fixtureRoot)

    const strictResult = runPackFixture(scriptPath, {})
    assert.strictEqual(strictResult.status, 1, strictResult.stderr)
    assert.ok(strictResult.stderr.includes('electron-builder not installed'))
    assert.strictEqual(fs.existsSync(path.join(fixtureRoot, 'src', 'frontend', 'dist')), false)

    const softResult = runPackFixture(scriptPath, { KKMAIL_PACK_SOFT: '1' })
    assert.strictEqual(softResult.status, 0, softResult.stderr)
    assert.ok(softResult.stderr.includes('pack:linux soft-ok'))

    const npmSoftResult = runPackFixture(scriptPath, {
      KKMAIL_PACK_SOFT: '1',
      npm_lifecycle_event: 'pack:linux',
    })
    assert.strictEqual(npmSoftResult.status, 1, npmSoftResult.stderr)
    assert.ok(npmSoftResult.stderr.includes('ignored by npm packaging scripts'))
  }

  // Path 5: Builder failures fail by default; explicit local soft-ok cannot mask npm pack failures.
  if (process.platform !== 'win32') {
    const fixtureRoot = path.join(tmpRoot, 'cli-builder-failure')
    const scriptPath = createPackFixture(fixtureRoot, 23)

    const strictResult = runPackFixture(scriptPath, {})
    assert.strictEqual(strictResult.status, 23, strictResult.stderr)

    const softResult = runPackFixture(scriptPath, { KKMAIL_PACK_SOFT: '1' })
    assert.strictEqual(softResult.status, 0, softResult.stderr)

    const npmSoftResult = runPackFixture(scriptPath, {
      KKMAIL_PACK_SOFT: '1',
      npm_lifecycle_event: 'pack:linux:with-pg',
    })
    assert.strictEqual(npmSoftResult.status, 23, npmSoftResult.stderr)

    const successRoot = path.join(tmpRoot, 'cli-builder-success')
    const successScript = createPackFixture(successRoot, 0)
    const successResult = runPackFixture(successScript, {})
    assert.strictEqual(successResult.status, 0, successResult.stdout)
  }

  // npm packaging scripts never opt into soft-ok.
  {
    const scripts = require('./package.json').scripts
    for (const [name, command] of Object.entries(scripts)) {
      if (command.includes('scripts/pack-linux.js')) {
        assert.ok(!command.includes('KKMAIL_PACK_SOFT'), `${name} must not enable KKMAIL_PACK_SOFT`)
      }
    }
    assert.strictEqual(canSoftExit({ KKMAIL_PACK_SOFT: '1', npm_lifecycle_event: 'dist:linux:dir' }), false)
    assert.strictEqual(canSoftExit({ KKMAIL_PACK_SOFT: '1', npm_lifecycle_event: undefined }), true)
  }

  console.log('packLinux.test.js: ok')
} finally {
  fs.rmSync(tmpRoot, { recursive: true, force: true })
}

function createPackFixture(fixtureRoot, builderExitCode) {
  const scriptPath = path.join(fixtureRoot, 'src', 'desktop', 'scripts', 'pack-linux.js')
  const desktopRoot = path.join(fixtureRoot, 'src', 'desktop')
  fs.mkdirSync(path.dirname(scriptPath), { recursive: true })
  fs.writeFileSync(path.join(fixtureRoot, 'AGENTS.md'), '')
  fs.copyFileSync(require.resolve('./scripts/pack-linux'), scriptPath)

  if (builderExitCode !== undefined) {
    const builderPath = path.join(desktopRoot, 'node_modules', '.bin', 'electron-builder')
    fs.mkdirSync(path.dirname(builderPath), { recursive: true })
    fs.writeFileSync(builderPath, `#!/bin/sh\nexit ${builderExitCode}\n`, { mode: 0o755 })
    fs.chmodSync(builderPath, 0o755)
  }

  return scriptPath
}

function runPackFixture(scriptPath, env) {
  return spawnSync(process.execPath, [scriptPath], {
    cwd: path.resolve(scriptPath, '..', '..', '..', '..'),
    encoding: 'utf8',
    env: { ...process.env, ...env },
  })
}
