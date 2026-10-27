'use strict'

const assert = require('assert')
const fs = require('fs')
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

console.log('packaged smoke: ok')
