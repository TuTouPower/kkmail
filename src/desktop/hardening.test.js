const assert = require('assert')
const {
  appContentSecurityPolicy,
  mergeCspHeaders,
  isAllowedPermission,
  createPermissionRequestHandler,
  createPermissionCheckHandler,
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

// t025 AC-003: Permission boundary tests
const appOrigin = 'http://127.0.0.1:15433'

// 1. Trusted top-level clipboard sanitized write: allowed
assert.strictEqual(
  isAllowedPermission('clipboard-sanitized-write', `${appOrigin}/`, true, appOrigin),
  true,
  'Trusted top-level clipboard write must be allowed'
)

// 2. Subframe (mail iframe): must be denied
assert.strictEqual(
  isAllowedPermission('clipboard-sanitized-write', `${appOrigin}/mail_frame`, false, appOrigin),
  false,
  'Subframe / iframe clipboard write must be denied'
)

// 3. Untrusted origin: must be denied
assert.strictEqual(
  isAllowedPermission('clipboard-sanitized-write', 'https://malicious.example.com/', true, appOrigin),
  false,
  'Untrusted origin clipboard write must be denied'
)

// 4. Reading clipboard: must be denied
assert.strictEqual(
  isAllowedPermission('clipboard-read', `${appOrigin}/`, true, appOrigin),
  false,
  'Clipboard read must be denied'
)

// 5. Media, notifications, geolocation: must be denied
assert.strictEqual(isAllowedPermission('media', `${appOrigin}/`, true, appOrigin), false)
assert.strictEqual(isAllowedPermission('notifications', `${appOrigin}/`, true, appOrigin), false)
assert.strictEqual(isAllowedPermission('geolocation', `${appOrigin}/`, true, appOrigin), false)

// 6. Handlers with dynamic trusted origin getter
const reqHandler = createPermissionRequestHandler(() => appOrigin)
const checkHandler = createPermissionCheckHandler(() => appOrigin)

let reqAllowed = false
reqHandler(null, 'clipboard-sanitized-write', (ok) => { reqAllowed = ok }, {
  requestingUrl: `${appOrigin}/inbox`,
  isMainFrame: true,
})
assert.strictEqual(reqAllowed, true, 'Handler must allow top-level appOrigin clipboard-sanitized-write')

let reqDeniedIframe = true
reqHandler(null, 'clipboard-sanitized-write', (ok) => { reqDeniedIframe = ok }, {
  requestingUrl: `${appOrigin}/inbox`,
  isMainFrame: false,
})
assert.strictEqual(reqDeniedIframe, false, 'Handler must deny iframe clipboard-sanitized-write')

let reqDeniedRead = true
reqHandler(null, 'clipboard-read', (ok) => { reqDeniedRead = ok }, {
  requestingUrl: `${appOrigin}/inbox`,
  isMainFrame: true,
})
assert.strictEqual(reqDeniedRead, false, 'Handler must deny clipboard-read')

assert.strictEqual(
  checkHandler(null, 'clipboard-sanitized-write', appOrigin, { isMainFrame: true }),
  true
)
assert.strictEqual(
  checkHandler(null, 'clipboard-sanitized-write', appOrigin, { isMainFrame: false }),
  false
)
assert.strictEqual(
  checkHandler(null, 'clipboard-read', appOrigin, { isMainFrame: true }),
  false
)

assert.ok(pkg.build.files.includes('hardening.js'), 'hardening.js must be packaged')
console.log('desktop hardening: ok')
