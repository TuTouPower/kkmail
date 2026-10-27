const assert = require('assert')
const path = require('path')
const { sidecarPath, frontendDistPath, isAllowedExternalUrl, isLocalAppUrl, createExternalWindowHandler, createNavigationGuardHandler, attachContentGuards } = require('./paths')
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
// A127: every webContents (main window AND window.open popups) must get the
// same window-open handler + navigation guards, resolved against the app
// origin at event time (getter), not a snapshot taken at window creation.
assert.strictEqual(typeof attachContentGuards, 'function', 'paths.js must export attachContentGuards')
assert.strictEqual(typeof createNavigationGuardHandler, 'function', 'paths.js must export createNavigationGuardHandler')
{
  let liveOrigin = 'http://127.0.0.1:18765'
  const navOpened = []
  const listeners = {}
  const fakeContents = {
    windowOpenHandler: null,
    on(event, fn) { (listeners[event] = listeners[event] || []).push(fn) },
    setWindowOpenHandler(fn) { this.windowOpenHandler = fn },
    emit(event, ...args) { for (const fn of listeners[event] || []) fn(...args) },
  }
  attachContentGuards(fakeContents, (url) => navOpened.push(url), () => liveOrigin)
  assert.strictEqual(typeof fakeContents.windowOpenHandler, 'function')
  assert.strictEqual((listeners['will-navigate'] || []).length, 1)
  assert.strictEqual((listeners['will-redirect'] || []).length, 1)

  // Popup window-open: same-origin allowed, https handed out, loopback denied.
  assert.deepStrictEqual(fakeContents.windowOpenHandler({ url: 'http://127.0.0.1:18765/oauth' }), { action: 'allow' })
  assert.deepStrictEqual(fakeContents.windowOpenHandler({ url: 'https://example.com' }), { action: 'deny' })
  assert.deepStrictEqual(navOpened, ['https://example.com'])

  // Navigation guard on the popup: local stays, external https is prevented
  // and handed to the system browser, other-port loopback is just blocked.
  const navEvent = () => ({ prevented: false, preventDefault() { this.prevented = true } })
  let ev = navEvent(); fakeContents.emit('will-navigate', ev, 'http://127.0.0.1:18765/inbox')
  assert.strictEqual(ev.prevented, false)
  ev = navEvent(); fakeContents.emit('will-navigate', ev, 'https://example.com/page')
  assert.strictEqual(ev.prevented, true)
  ev = navEvent(); fakeContents.emit('will-redirect', ev, 'http://127.0.0.1:9999/phish')
  assert.strictEqual(ev.prevented, true)
  assert.deepStrictEqual(navOpened, ['https://example.com', 'https://example.com/page'])

  // Origin is read at event time: after a restart on a new port, the new
  // origin is local and the old one no longer is.
  liveOrigin = 'http://127.0.0.1:22222'
  assert.deepStrictEqual(fakeContents.windowOpenHandler({ url: 'http://127.0.0.1:22222/app' }), { action: 'allow' })
  ev = navEvent(); fakeContents.emit('will-navigate', ev, 'http://127.0.0.1:18765/inbox')
  assert.strictEqual(ev.prevented, true)
}

assert.ok(!pkg.dependencies || !pkg.dependencies['electron-squirrel-startup'],
  'electron-squirrel-startup unused (nsis target); must not be declared')
console.log('desktop paths: ok')
