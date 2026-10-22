#!/usr/bin/env node
/**
 * Linux --dir packaging scaffold for mail-core desktop.
 * - Includes vendor/pgsql when present (fetched via scripts/fetch-pg-binaries.sh)
 * - If frontend/dist is missing, creates a temporary stub then deletes only what it created
 *   (never leaves a stub in the real frontend/dist tree, and never deletes pre-existing dist files)
 * - Soft-exits 0 when Electron binary download / pack fails unless KKMAIL_PACK_STRICT=1
 */
const { spawnSync } = require('child_process')
const fs = require('fs')
const path = require('path')

function createStubIfNeeded(frontendDist) {
  const assetsDir = path.join(frontendDist, 'assets')
  const indexPath = path.join(frontendDist, 'index.html')

  const distExisted = fs.existsSync(frontendDist)
  const assetsExisted = fs.existsSync(assetsDir)
  const indexExisted = fs.existsSync(indexPath)

  let createdDist = false
  let createdAssets = false
  let createdIndex = false

  if (!indexExisted) {
    if (!distExisted) {
      fs.mkdirSync(frontendDist, { recursive: true })
      createdDist = true
    }
    if (!assetsExisted) {
      fs.mkdirSync(assetsDir, { recursive: true })
      createdAssets = true
    }
    fs.writeFileSync(
      indexPath,
      '<!doctype html><title>kkmail</title><p>Build frontend with npm run build</p>\n',
    )
    createdIndex = true
    console.warn('frontend/dist missing — created temporary stub for electron-builder')
  }

  const cleanup = () => {
    if (createdIndex && fs.existsSync(indexPath)) {
      try {
        fs.unlinkSync(indexPath)
        createdIndex = false
      } catch (err) {
        console.warn('failed to remove temporary frontend/dist index.html', err)
      }
    }
    if (createdAssets && fs.existsSync(assetsDir)) {
      try {
        if (fs.readdirSync(assetsDir).length === 0) {
          fs.rmdirSync(assetsDir)
          createdAssets = false
        }
      } catch (err) {
        console.warn('failed to remove temporary frontend/dist assets dir', err)
      }
    }
    if (createdDist && fs.existsSync(frontendDist)) {
      try {
        if (fs.readdirSync(frontendDist).length === 0) {
          fs.rmdirSync(frontendDist)
          createdDist = false
        }
      } catch (err) {
        console.warn('failed to remove temporary frontend/dist dir', err)
      }
    }
  }

  return {
    stubCreated: createdIndex,
    createdDist,
    createdAssets,
    createdIndex,
    cleanup,
  }
}

function run() {
  const root = path.join(__dirname, '..')
  let repoRoot = path.resolve(__dirname, '../../..')
  if (!fs.existsSync(path.join(repoRoot, 'AGENTS.md'))) {
    repoRoot = path.resolve(__dirname, '../..')
  }
  const vendorPg = path.join(root, 'vendor', 'pgsql')
  const vendorBin = path.join(vendorPg, 'bin', 'pg_ctl')
  const frontendDist = path.join(repoRoot, 'src', 'frontend', 'dist')

  fs.mkdirSync(path.join(vendorPg, 'bin'), { recursive: true })

  const stubState = createStubIfNeeded(frontendDist)

  const hasPg = fs.existsSync(vendorBin)
  console.log(hasPg
    ? `Including vendor PostgreSQL (${path.dirname(vendorBin)})`
    : 'No vendor/pgsql/bin/pg_ctl — package will run PostgresManager in stub mode')

  const builder = path.join(root, 'node_modules', '.bin', 'electron-builder')
  if (!fs.existsSync(builder)) {
    console.warn('electron-builder not installed — run npm install in desktop/; soft-ok')
    stubState.cleanup()
    process.exit(0)
  }

  let status = 1
  try {
    const r = spawnSync(builder, ['--linux', 'dir'], {
      cwd: root,
      stdio: 'inherit',
      env: { ...process.env, CSC_IDENTITY_AUTO_DISCOVERY: 'false' },
    })
    status = r.status == null ? 1 : r.status
  } finally {
    stubState.cleanup()
  }

  if (status === 0) {
    console.log('pack:linux ok')
    process.exit(0)
  }

  console.warn('electron-builder exited', status)
  // Soft-ok for local scaffold: missing Electron cache / network should warn, not fail
  if (process.env.KKMAIL_PACK_STRICT === '1') {
    process.exit(status || 1)
  }
  console.warn('pack:linux soft-ok (set KKMAIL_PACK_STRICT=1 to fail hard)')
  process.exit(0)
}

if (require.main === module) {
  run()
}

module.exports = { createStubIfNeeded, run }
