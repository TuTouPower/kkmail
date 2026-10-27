'use strict'

const assert = require('assert')
const fs = require('fs')
const os = require('os')
const path = require('path')

const smokeSource = fs.readFileSync(path.join(__dirname, 'packaged-smoke.js'), 'utf8')

// A195: the PG port must come from the declared DEFAULT_PORT constant
// exported by postgresManager, never from an assignment to an undeclared
// variable (which silently creates an implicit global in sloppy mode).
assert.ok(
  !/(?<![\w$.])DEFAULT_PORT\s*=(?![=>])/.test(smokeSource),
  'packaged-smoke.js must not assign to undeclared DEFAULT_PORT (implicit global)',
)
const { DEFAULT_PORT } = require('../postgresManager')
assert.strictEqual(DEFAULT_PORT, 54329)
assert.ok(
  /require\('\.\.\/postgresManager'\)/.test(smokeSource) && smokeSource.includes('DEFAULT_PORT'),
  'packaged-smoke.js must reference the imported DEFAULT_PORT',
)

// A95: on any failure after the temp data root exists, the smoke run must
// still stop both PG managers and remove the temp directory. That cleanup
// lives in an exported finally-block helper so it is testable here.
const smoke = require('./packaged-smoke')
assert.strictEqual(
  typeof smoke.cleanupSmokeResources,
  'function',
  'packaged-smoke.js must export cleanupSmokeResources for its finally block',
)
{
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'kkmail-smoke-cleanup-test-'))
  const stopped = []
  const mgrOk = { stop: () => { stopped.push('ok'); return { ok: true } } }
  const mgrThrows = { stop: () => { stopped.push('throws'); throw new Error('stop boom') } }
  smoke.cleanupSmokeResources([mgrOk, mgrThrows, null], root)
  assert.deepStrictEqual(
    stopped,
    ['ok', 'throws'],
    'cleanup must attempt every manager even when one stop throws',
  )
  assert.ok(!fs.existsSync(root), 'cleanup must remove the temp data root')
}

console.log('packaged smoke: ok')
