const assert = require('assert')
const fs = require('fs')
const os = require('os')
const path = require('path')

const {
  assertSmokeMarkerPersisted,
  writeSmokeMarker,
} = require('./packaged_smoke_db')

const root = fs.mkdtempSync(path.join(os.tmpdir(), 'kkmail-smoke-psql-test-'))
const psqlBin = path.join(root, 'psql')
fs.writeFileSync(psqlBin, '')

const manager = {
  port: 54329,
  user: 'kkmail',
  database: 'kkmail_mail',
  password: () => 'unit-test-password',
}

const calls = []
const responses = [
  { status: 0, stdout: '', stderr: '' },
  { status: 0, stdout: 'persisted_ok\n', stderr: '' },
]
function spawnSync(binary, args, options) {
  calls.push({ binary, args, options })
  return responses.shift()
}

writeSmokeMarker({ psqlBin, manager, spawnSync, env: {} })
assertSmokeMarkerPersisted({ psqlBin, manager, spawnSync, env: {} })

assert.strictEqual(calls.length, 2)
for (const call of calls) {
  assert.strictEqual(call.binary, psqlBin)
  assert.ok(call.args.includes('-U') && call.args[call.args.indexOf('-U') + 1] === manager.user)
  assert.ok(call.args.includes('-d') && call.args[call.args.indexOf('-d') + 1] === manager.database)
  assert.strictEqual(call.options.env.PGPASSWORD, 'unit-test-password')
  assert.ok(call.args.includes('-v') && call.args.includes('ON_ERROR_STOP=1'))
}
assert.match(calls[0].args[calls[0].args.indexOf('-c') + 1], /INSERT INTO kkmail_smoke_marker/)
assert.match(calls[1].args[calls[1].args.indexOf('-c') + 1], /SELECT value FROM kkmail_smoke_marker/)

assert.throws(
  () => assertSmokeMarkerPersisted({ psqlBin: path.join(root, 'missing-psql'), manager, spawnSync, env: {} }),
  /packaged psql binary is missing/i,
)

assert.throws(
  () => assertSmokeMarkerPersisted({
    psqlBin,
    manager,
    env: {},
    spawnSync: () => ({ status: 2, stdout: '', stderr: 'query failed' }),
  }),
  /psql command failed/i,
)

assert.throws(
  () => assertSmokeMarkerPersisted({
    psqlBin,
    manager,
    env: {},
    spawnSync: () => ({ status: 0, stdout: 'missing_marker', stderr: '' }),
  }),
  /persistence marker mismatch/i,
)

fs.rmSync(root, { recursive: true, force: true })
process.stdout.write('packaged_smoke_db.test.js: ok\n')
