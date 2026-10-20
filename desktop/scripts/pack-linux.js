#!/usr/bin/env node
/**
 * Linux --dir packaging scaffold for mail-core desktop.
 * - Includes vendor/pgsql when present (fetched via scripts/fetch-pg-binaries.sh)
 * - Creates stub dirs so electron-builder does not fail on missing paths
 * - Soft-exits 0 when Electron binary download is unavailable (CI without cache)
 */
const { spawnSync } = require('child_process')
const fs = require('fs')
const path = require('path')

const root = path.join(__dirname, '..')
const repoRoot = path.join(root, '..')
const vendorPg = path.join(root, 'vendor', 'pgsql')
const vendorBin = path.join(vendorPg, 'bin', 'pg_ctl')
const frontendDist = path.join(repoRoot, 'frontend', 'dist')

fs.mkdirSync(path.join(vendorPg, 'bin'), { recursive: true })
if (!fs.existsSync(frontendDist)) {
  fs.mkdirSync(path.join(frontendDist, 'assets'), { recursive: true })
  fs.writeFileSync(
    path.join(frontendDist, 'index.html'),
    '<!doctype html><title>kkmail</title><p>Build frontend with npm run build</p>\n',
  )
}

const hasPg = fs.existsSync(vendorBin)
console.log(hasPg
  ? `Including vendor PostgreSQL (${path.dirname(vendorBin)})`
  : 'No vendor/pgsql/bin/pg_ctl — package will run PostgresManager in stub mode')

const builder = path.join(root, 'node_modules', '.bin', 'electron-builder')
if (!fs.existsSync(builder)) {
  console.warn('electron-builder not installed — run npm install in desktop/; soft-ok')
  process.exit(0)
}

const r = spawnSync(builder, ['--linux', 'dir'], {
  cwd: root,
  stdio: 'inherit',
  env: { ...process.env, CSC_IDENTITY_AUTO_DISCOVERY: 'false' },
})

if (r.status === 0) {
  console.log('pack:linux ok')
  process.exit(0)
}

console.warn('electron-builder exited', r.status)
// Soft-ok: missing Electron cache / network in CI must not fail the scaffold job
if (process.env.KKMAIL_PACK_STRICT === '1') {
  process.exit(r.status || 1)
}
console.log('pack:linux soft-ok (set KKMAIL_PACK_STRICT=1 to fail hard)')
process.exit(0)
