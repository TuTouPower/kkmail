const assert = require('assert')
const {
  appContentSecurityPolicy,
  mergeCspHeaders,
  denyPermissionRequest,
  denyPermissionCheck,
} = require('./hardening')
const pkg = require('./package.json')

const csp = appContentSecurityPolicy()
assert.ok(csp.includes("default-src 'self'"))
assert.ok(csp.includes("script-src 'self'"))
assert.ok(csp.includes("object-src 'none'"))
assert.ok(csp.includes("connect-src 'self'"))
assert.ok(!csp.includes('*'), 'CSP must not allow wildcard sources')

const merged = mergeCspHeaders({
  'Content-Type': ['text/html'],
  'content-security-policy': ["default-src *"],
})
assert.deepStrictEqual(merged['Content-Type'], ['text/html'])
assert.deepStrictEqual(merged['Content-Security-Policy'], [csp])
assert.strictEqual(merged['content-security-policy'], undefined)

let allowed = true
denyPermissionRequest(null, 'media', (ok) => { allowed = ok })
assert.strictEqual(allowed, false)
assert.strictEqual(denyPermissionCheck(), false)

assert.ok(pkg.build.files.includes('hardening.js'), 'hardening.js must be packaged')
console.log('desktop hardening: ok')
