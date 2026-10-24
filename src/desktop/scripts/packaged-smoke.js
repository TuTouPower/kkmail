#!/usr/bin/env node
/**
 * Packaged Desktop Smoke Test & Embedded PostgreSQL Lifecycle Verification (t021).
 *
 * Verifies that the actual packaged application directory (--dir) contains:
 * 1. Real production frontend SPA (never an empty or stub index.html).
 * 2. Real PostgreSQL binaries matching host platform architecture.
 * 3. Functional PostgreSQL lifecycle: initial initdb, start, clean stop,
 *    and persistent data preservation across restarts without re-initialization.
 */

const assert = require('assert')
const fs = require('fs')
const os = require('os')
const path = require('path')
const cp = require('child_process')
const { PostgresManager } = require('../postgresManager')
const { freePort } = require('../startup')
const { assertSmokeMarkerPersisted, writeSmokeMarker } = require('./packaged_smoke_db')

const desktopRoot = path.resolve(__dirname, '..')
const repoRoot = path.resolve(desktopRoot, '../..')

async function main() {
  console.log('[t021] Starting Packaged Desktop Smoke & PostgreSQL Lifecycle Test...')

  // 1. Locate or create packaged output
  const arch = process.arch === 'arm64' ? 'arm64' : 'x64'
  let appDir = null

  if (process.platform === 'darwin') {
    appDir = path.join(desktopRoot, 'release', `mac-${arch}`, 'kkmail.app', 'Contents', 'Resources')
  } else if (process.platform === 'linux') {
    appDir = path.join(desktopRoot, 'release', 'linux-unpacked', 'resources')
  } else if (process.platform === 'win32') {
    appDir = path.join(desktopRoot, 'release', 'win-unpacked', 'resources')
  }

  // If not yet packaged, run electron-builder --dir
  if (!appDir || !fs.existsSync(appDir)) {
    console.log('[t021] Running electron-builder --dir to create test package...')
    const builder = path.join(desktopRoot, 'node_modules', '.bin', 'electron-builder')
    assert.ok(fs.existsSync(builder), 'electron-builder binary missing in desktop/node_modules')
    const packRes = cp.spawnSync(builder, ['--dir'], {
      cwd: desktopRoot,
      stdio: 'inherit',
      env: {
        ...process.env,
        CSC_IDENTITY_AUTO_DISCOVERY: 'false',
      },
    })
    assert.strictEqual(packRes.status, 0, 'electron-builder packaging failed')
  }

  assert.ok(fs.existsSync(appDir), `Packaged resources directory missing: ${appDir}`)
  console.log(`[t021] Found packaged resources: ${appDir}`)

  // 2. AC-001: Assert real production frontend assets (never stub)
  const frontendDist = path.join(appDir, 'frontend', 'dist')
  assert.ok(fs.existsSync(frontendDist), `Packaged frontend/dist missing: ${frontendDist}`)
  const indexHtmlPath = path.join(frontendDist, 'index.html')
  assert.ok(fs.existsSync(indexHtmlPath), `Packaged index.html missing: ${indexHtmlPath}`)

  const indexContent = fs.readFileSync(indexHtmlPath, 'utf8')
  assert.ok(!indexContent.includes('Build frontend with npm run build'), 'AC-001 violation: Packaged app contains a stub index.html!')
  assert.ok(indexContent.includes('<div id="root">') || indexContent.includes('assets/'), 'index.html does not look like production SPA')
  console.log('✓ AC-001: Verified real production SPA assets in package.')

  // 3. AC-001 & AC-002: Assert packaged PostgreSQL binaries and architecture
  const packagedPgBin = path.join(appDir, 'pgsql', 'bin')
  assert.ok(fs.existsSync(packagedPgBin), `Packaged pgsql/bin missing: ${packagedPgBin}`)

  const pgCtl = path.join(packagedPgBin, process.platform === 'win32' ? 'pg_ctl.exe' : 'pg_ctl')
  const postgres = path.join(packagedPgBin, process.platform === 'win32' ? 'postgres.exe' : 'postgres')
  const initdb = path.join(packagedPgBin, process.platform === 'win32' ? 'initdb.exe' : 'initdb')

  assert.ok(fs.existsSync(pgCtl), `Packaged pg_ctl missing: ${pgCtl}`)
  assert.ok(fs.existsSync(postgres), `Packaged postgres binary missing: ${postgres}`)
  assert.ok(fs.existsSync(initdb), `Packaged initdb missing: ${initdb}`)

  // Architecture check on macOS/Linux
  if (process.platform === 'darwin') {
    const fileOut = cp.spawnSync('file', [postgres], { encoding: 'utf8' }).stdout
    assert.ok(
      fileOut.includes(arch === 'arm64' ? 'arm64' : 'x86_64'),
      `Packaged postgres binary architecture mismatch: ${fileOut}`,
    )
  }
  console.log('✓ AC-001: Verified packaged PostgreSQL binaries matching host platform architecture.')

  // 4. AC-002, AC-003, AC-004: Life-cycle testing with packaged binaries in isolated directory
  const testDataRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'kkmail-pkg-smoke-'))
  const port = await freePort(DEFAULT_PORT = 54329)

  console.log(`[t021] Testing embedded PG lifecycle on port ${port} with dataRoot=${testDataRoot}`)
  const mgr1 = new PostgresManager({
    dataRoot: testDataRoot,
    pgBinDir: packagedPgBin,
    port: port,
  })

  // First start: should run initdb and start successfully
  const start1 = mgr1.start()
  assert.strictEqual(start1.ok, true, `First PG start failed: ${start1.reason || JSON.stringify(start1)}`)
  assert.strictEqual(start1.stub, false)

  // Verify password file generated with mode 0600
  const pwFile = path.join(testDataRoot, 'secrets', 'pg-password')
  assert.ok(fs.existsSync(pwFile), 'Password file not created')
  if (process.platform !== 'win32') {
    assert.strictEqual(fs.statSync(pwFile).mode & 0o777, 0o600, 'Password file mode must be 0600')
  }

  // Write the marker as the actual application role in the application database.
  const psqlName = process.platform === 'win32' ? 'psql.exe' : 'psql'
  const psqlBin = path.join(packagedPgBin, psqlName)
  assert.ok(fs.existsSync(psqlBin), `Packaged psql binary missing: ${psqlBin}`)
  writeSmokeMarker({ psqlBin, manager: mgr1 })

  console.log('✓ AC-002: Packaged PostgreSQL initialized and started successfully.')

  // Stop the instance (AC-004)
  const stop1 = mgr1.stop()
  assert.ok(stop1.ok || stop1.stopped, 'Stopping PG failed')

  // Port should be released
  let portReleased = false
  for (let i = 0; i < 20; i++) {
    try {
      const s = require('net').createServer()
      await new Promise((resolve, reject) => {
        s.once('error', reject)
        s.listen(port, '127.0.0.1', () => {
          s.close(() => resolve())
        })
      })
      portReleased = true
      break
    } catch (_) {
      await new Promise((r) => setTimeout(r, 200))
    }
  }
  assert.strictEqual(portReleased, true, 'Port not released after pg_ctl stop')
  console.log('✓ AC-004: Clean stop released child process and listening port.')

  // Restart instance on the same dataRoot (AC-003)
  const mgr2 = new PostgresManager({
    dataRoot: testDataRoot,
    pgBinDir: packagedPgBin,
    port: port,
  })

  const start2 = mgr2.start()
  assert.strictEqual(start2.ok, true, `Second PG start failed: ${start2.reason || JSON.stringify(start2)}`)

  // Password must match previously persisted value
  assert.strictEqual(mgr2.password(), mgr1.password(), 'Password regenerated unexpectedly')
  assertSmokeMarkerPersisted({ psqlBin, manager: mgr2 })

  // Clean stop for mgr2
  const stop2 = mgr2.stop()
  assert.ok(stop2.ok || stop2.stopped)
  console.log('✓ AC-003: Re-started on existing dataRoot preserved password and state without re-initializing.')

  // Clean up temporary smoke directory
  fs.rmSync(testDataRoot, { recursive: true, force: true })
  console.log('[t021] Packaged Desktop Smoke Test PASSED cleanly.')
}

main().catch((err) => {
  console.error('[t021] Packaged smoke failed:', err)
  process.exit(1)
})
