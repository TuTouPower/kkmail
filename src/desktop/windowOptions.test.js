'use strict'

const assert = require('assert')
const { createMainWindowOptions, windowBackgroundColor, shouldRemoveApplicationMenu } = require('./windowOptions')

function options(platform) {
  return createMainWindowOptions({
    platform,
    preloadPath: '/app/preload.js',
    iconPath: '/app/icon.svg',
    backgroundColor: windowBackgroundColor(false),
  })
}

const macOptions = options('darwin')
assert.strictEqual(macOptions.show, false)
assert.strictEqual(macOptions.titleBarStyle, 'hidden')
assert.deepStrictEqual(macOptions.trafficLightPosition, { x: 16, y: 13 })
assert.strictEqual(macOptions.webPreferences.contextIsolation, true)
assert.strictEqual(macOptions.webPreferences.sandbox, true)
assert.strictEqual(macOptions.webPreferences.nodeIntegration, false)
assert.strictEqual(macOptions.webPreferences.webviewTag, false)

for (const platform of ['win32', 'linux']) {
  const nativeFrameOptions = options(platform)
  assert.ok(!Object.hasOwn(nativeFrameOptions, 'titleBarStyle'))
  assert.ok(!Object.hasOwn(nativeFrameOptions, 'trafficLightPosition'))
  assert.ok(!Object.hasOwn(nativeFrameOptions, 'titleBarOverlay'))
}

assert.strictEqual(windowBackgroundColor(true), '#16191A')
assert.strictEqual(windowBackgroundColor(false), '#E9EAED')

// A278: packaged (production) builds must drop Electron's default
// application menu (which keeps a DevTools entry); dev keeps it.
assert.strictEqual(shouldRemoveApplicationMenu({ isPackaged: true }), true)
assert.strictEqual(shouldRemoveApplicationMenu({ isPackaged: false }), false)
assert.strictEqual(shouldRemoveApplicationMenu({}), false)
assert.strictEqual(shouldRemoveApplicationMenu(), false)
console.log('desktop window options: ok')
