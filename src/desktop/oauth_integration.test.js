'use strict'

// Invoked by the owned PostgreSQL suite with a real API and compiled SPA.
const assert = require('assert')
const path = require('path')
const fs = require('fs')

if (!process.env.KKMAIL_OAUTH_TEST_ORIGIN || !process.env.KKMAIL_OAUTH_TEST_PASSWORD) {
  process.stdout.write('SKIP Electron OAuth integration: set KKMAIL_OAUTH_TEST_ORIGIN and KKMAIL_OAUTH_TEST_PASSWORD\n')
  process.exit(0)
}

if (!process.versions.electron) {
  const child = require('child_process').spawn(process.execPath, [
    path.join(__dirname, 'node_modules/electron/cli.js'), __filename,
  ], { stdio: 'inherit', env: process.env })
  child.on('exit', code => process.exit(code || 0))
  return
}

const { app, BrowserWindow } = require('electron')
const { createMainWindowOptions } = require('./windowOptions')
const { createExternalWindowHandler } = require('./paths')
const root = path.resolve(__dirname, '../..')
const profile = fs.mkdtempSync(path.join(root, '.scratch/oauth_electron_'))
app.setPath('userData', profile)
app.commandLine.appendSwitch('disable-gpu')

let win
async function evaluate(code) {
  return win.webContents.executeJavaScript(code, true)
}
async function waitFor(code) {
  const deadline = Date.now() + 15000
  while (Date.now() < deadline) {
    if (await evaluate(code)) return
    await new Promise(resolve => setTimeout(resolve, 50))
  }
  throw new Error(`Timed out: ${code}`)
}
async function click(text) {
  await evaluate(`Array.from(document.querySelectorAll('button')).find(b => b.textContent === ${JSON.stringify(text)}).click()`)
}
async function setValue(selector, value) {
  await evaluate(`(() => {
    const node = document.querySelector(${JSON.stringify(selector)});
    const proto = node.tagName === 'SELECT' ? HTMLSelectElement.prototype : HTMLInputElement.prototype;
    Object.getOwnPropertyDescriptor(proto, 'value').set.call(node, ${JSON.stringify(value)});
    node.dispatchEvent(new Event(node.tagName === 'SELECT' ? 'change' : 'input', { bubbles: true }));
  })()`)
}

app.whenReady().then(async () => {
  try {
    const origin = process.env.KKMAIL_OAUTH_TEST_ORIGIN
    assert.ok(origin && new URL(origin).hostname === '127.0.0.1')
    win = new BrowserWindow(createMainWindowOptions({
      platform: process.platform, preloadPath: path.join(__dirname, 'preload.js'),
      backgroundColor: '#ffffff',
    }))
    const label = 'Microsoft'
    const email = 'electron@outlook.com'
    let authorizationUrl
    win.webContents.setWindowOpenHandler(createExternalWindowHandler(url => { authorizationUrl = url }))
    await win.loadURL(origin)
    win.show()
    await waitFor("Boolean(document.querySelector('#login-password'))")
    await setValue('#login-password', process.env.KKMAIL_OAUTH_TEST_PASSWORD)
    await click('登录')
    await waitFor("Boolean(document.querySelector('button[data-ui=\"SB11\"]'))")
    await evaluate("document.querySelector('button[data-ui=\"SB11\"]').click()")
    await waitFor("Array.from(document.querySelectorAll('button')).some(b => b.textContent === '添加账户')")
    await click('添加账户')
    await setValue('#account-vendor', 'microsoft')
    await waitFor("Boolean(document.querySelector('#account-redirect-uri')?.value.startsWith('http://'))")
    const redirect = await evaluate("document.querySelector('#account-redirect-uri').value")
    assert.strictEqual(new URL(redirect).port, new URL(origin).port)
    assert.strictEqual(new URL(redirect).hostname, 'localhost')
    await setValue('#account-client-id', 'electron-test-client')
    await click(`使用 ${label} 登录`)
    const deadline = Date.now() + 5000
    while (!authorizationUrl && Date.now() < deadline) await new Promise(resolve => setTimeout(resolve, 20))
    assert.ok(authorizationUrl)
    assert.strictEqual(new URL(authorizationUrl).hostname, 'login.microsoftonline.com')
    assert.strictEqual(await evaluate("document.body.textContent.includes('浏览器拦截了授权窗口')"), false)
    // Node fetch has no Electron cookies, matching the separate system browser.
    const state = new URL(authorizationUrl).searchParams.get('state')
    const response = await fetch(`${redirect}?state=${encodeURIComponent(state)}&code=electron-code`)
    assert.strictEqual(response.status, 200)
    assert.match(await response.text(), /授权已完成/)
    win.blur()
    win.focus()
    await waitFor(`document.body.textContent.includes(${JSON.stringify(`已完成 ${label} 授权：${email}`)})`)
    await click('添加')
    await waitFor(`!document.querySelector('#account-email') && document.body.textContent.includes(${JSON.stringify(email)})`)
    process.stdout.write('Electron OAuth: real SPA, external handler, cookie-free callback, focus and save passed\n')
    app.exit(0)
  } catch (error) {
    process.stderr.write(`${error.stack}\n`)
    app.exit(1)
  }
})
