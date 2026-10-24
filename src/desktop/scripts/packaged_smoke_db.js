const fs = require('fs')
const cp = require('child_process')

const MARKER_KEY = 'test_key'
const MARKER_VALUE = 'persisted_ok'

function runPsql({ psqlBin, manager, sql, spawnSync = cp.spawnSync, env = process.env }) {
  if (!fs.existsSync(psqlBin)) {
    throw new Error(`Packaged psql binary is missing: ${psqlBin}`)
  }

  const result = spawnSync(
    psqlBin,
    [
      '-X',
      '-w',
      '-v',
      'ON_ERROR_STOP=1',
      '-h',
      '127.0.0.1',
      '-p',
      String(manager.port),
      '-U',
      manager.user,
      '-d',
      manager.database,
      '-t',
      '-A',
      '-c',
      sql,
    ],
    {
      encoding: 'utf8',
      env: { ...env, PGPASSWORD: manager.password() },
    },
  )

  if (result?.error || result?.status !== 0) {
    const status = result?.status == null ? 'spawn error' : `exit ${result.status}`
    const detail = result?.stderr || result?.error?.message || ''
    throw new Error(`Packaged psql command failed (${status})${detail ? `: ${detail}` : ''}`)
  }

  return String(result.stdout || '').trim()
}

function writeSmokeMarker(options) {
  return runPsql({
    ...options,
    sql: [
      'CREATE TABLE IF NOT EXISTS kkmail_smoke_marker (key text PRIMARY KEY, value text NOT NULL)',
      `INSERT INTO kkmail_smoke_marker (key, value) VALUES ('${MARKER_KEY}', '${MARKER_VALUE}') ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value`,
    ].join('; '),
  })
}

function assertSmokeMarkerPersisted(options) {
  const value = runPsql({
    ...options,
    sql: `SELECT value FROM kkmail_smoke_marker WHERE key = '${MARKER_KEY}'`,
  })
  if (value !== MARKER_VALUE) {
    throw new Error(`Packaged PostgreSQL persistence marker mismatch: expected ${MARKER_VALUE}, got ${value || '(empty)'}`)
  }
  return value
}

module.exports = { assertSmokeMarkerPersisted, runPsql, writeSmokeMarker }
