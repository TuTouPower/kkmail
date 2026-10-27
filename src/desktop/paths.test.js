const assert = require('assert')
const path = require('path')
const { sidecarPath, frontendDistPath, isAllowedExternalUrl, isLocalAppUrl, createExternalWindowHandler } = require('./paths')
const pkg = require('./package.json')

assert.strictEqual(sidecarPath('/r', 'linux'), path.join('/r', 'backend', 'kkmail-backend'))
assert.strictEqual(sidecarPath('/r', 'win32'), path.join('/r', 'backend', 'kkmail-backend.exe'))
assert.strictEqual(sidecarPath('', 'linux'), '')
assert.strictEqual(frontendDistPath('/r'), path.join('/r', 'frontend', 'dist'))

const backendRes = pkg.build.extraResources.find((r) => r.to === 'backend')
assert.ok(backendRes.filter.some((f) => 'kkmail-backend'.startsWith(f.replace('*', ''))), 'extraResources filter must match sidecar name')
assert.ok(pkg.build.files.includes('paths.js'), 'paths.js must be packaged')

assert.ok(isAllowedExternalUrl('https://example.com'))
assert.ok(isAllowedExternalUrl('mailto:a@b.c'))
// REPLACED (A331): loopback http is no longer an allowed *external* URL at
// any port — a mail link to http://127.0.0.1:<arbitrary port>/… must not be
// handed to the system browser (local-service probing/phishing). The old
// positive assertions for the URLs below were replaced wholesale; same-origin
// app http stays reachable in-app via isLocalAppUrl / the window-open
// handler's local branch, which is asserted separately below.
assert.ok(!isAllowedExternalUrl('http://localhost'))
assert.ok(!isAllowedExternalUrl('http://localhost.'))
assert.ok(!isAllowedExternalUrl('http://127.0.0.1'))
assert.ok(!isAllowedExternalUrl('http://127.255.255.254'))
assert.ok(!isAllowedExternalUrl('http://[::1]'))
assert.ok(!isAllowedExternalUrl('http://example.com'))
assert.ok(!isAllowedExternalUrl('http://192.168.1.2'))
assert.ok(!isAllowedExternalUrl('http://[::2]'))
assert.ok(!isAllowedExternalUrl('file:///etc/passwd'))
assert.ok(!isAllowedExternalUrl('javascript:alert(1)'))
assert.ok(!isAllowedExternalUrl('ms-msdt:/id'))
assert.ok(!isAllowedExternalUrl('https://user:pass@evil.example/'))
assert.ok(!isAllowedExternalUrl('http://user@evil.example/'))
assert.ok(!isAllowedExternalUrl('http://user@127.0.0.1/'))
assert.ok(isAllowedExternalUrl('https://example.com/path'))
assert.ok(isLocalAppUrl('http://127.0.0.1:18765/app', 'http://127.0.0.1:18765'))
assert.ok(!isLocalAppUrl('http://evil.test/', 'http://127.0.0.1:18765'))

const openedExternalUrls = []
const windowOpenHandler = createExternalWindowHandler(
  (url) => openedExternalUrls.push(url),
  'http://127.0.0.1:18765',
)
assert.deepStrictEqual(windowOpenHandler({ url: 'http://127.0.0.1:18765/oauth/callback' }), { action: 'allow' })
assert.deepStrictEqual(windowOpenHandler({ url: 'http://user@127.0.0.1:18765/oauth/callback' }), { action: 'deny' })
assert.deepStrictEqual(windowOpenHandler({ url: 'https://example.com' }), { action: 'deny' })
assert.deepStrictEqual(openedExternalUrls, ['https://example.com'])
// A331: loopback http on any non-app port is denied and never opened externally.
assert.deepStrictEqual(windowOpenHandler({ url: 'http://127.0.0.1:9999/phish' }), { action: 'deny' })
assert.deepStrictEqual(windowOpenHandler({ url: 'http://localhost:9999/phish' }), { action: 'deny' })
assert.deepStrictEqual(openedExternalUrls, ['https://example.com'])
assert.ok(!pkg.dependencies || !pkg.dependencies['electron-squirrel-startup'],
  'electron-squirrel-startup unused (nsis target); must not be declared')
console.log('desktop paths: ok')
