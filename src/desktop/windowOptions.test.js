'use strict'

const assert = require('assert')
const { createMainWindowOptions, windowBackgroundColor } = require('./windowOptions')

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

assert.strictEqual(windowBackgroundColor(true), '#171819')
assert.strictEqual(windowBackgroundColor(false), '#E9EAED')
console.log('desktop window options: ok')
