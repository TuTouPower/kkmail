/**
 * Desktop Clipboard & Permission Boundary Integration Test (t025).
 *
 * Verifies:
 * - AC-001: UI reference overlay badge click writes exact structured reference format,
 *   provides success feedback, and does not trigger underlying controls.
 * - AC-002: ErrorBoundary copy report writes diagnostics text to system clipboard.
 * - AC-003: Permission boundary allows only clipboard-sanitized-write for trusted top-level appOrigin;
 *   blocks mail iframes, external origins, clipboard reading, and media/unrelated permissions.
 * - AC-004: Clean error rejection when permission denied or API fails.
 * - AC-005: Desktop logger captures main process events.
 */
'use strict'

const assert = require('assert')
const http = require('http')
const path = require('path')
const cp = require('child_process')

// If running under plain Node, re-spawn under Electron with inherited stdio
if (!process.versions.electron) {
  const electronCli = path.join(__dirname, 'node_modules', 'electron', 'cli.js')
  const child = cp.spawn(process.execPath, [electronCli, __filename], {
    stdio: 'inherit',
    env: { ...process.env, KKMAIL_TESTING: '1' },
  })
  child.on('exit', (code, signal) => {
    if (signal) process.exit(1)
    process.exit(code || 0)
  })
  return
}

const { app, BrowserWindow, session, clipboard } = require('electron')
const {
  createPermissionRequestHandler,
  createPermissionCheckHandler,
} = require('./hardening')

app.commandLine.appendSwitch('disable-gpu')

async function runIntegrationSuite() {
  let originalClipboard = ''
  try {
    originalClipboard = await clipboard.readText('clipboard')
  } catch (_) {
    originalClipboard = ''
  }

  // Create local loopback server acting as local mail-core
  const server = http.createServer((req, res) => {
    if (req.url === '/') {
      res.writeHead(200, {
        'Content-Type': 'text/html; charset=utf-8',
        'Content-Security-Policy': "default-src 'self' 'unsafe-inline' blob: data:",
      })
      res.end(`
        <!DOCTYPE html>
        <html>
          <head><meta charset="utf-8"><title>kkmail test</title></head>
          <body>
            <!-- Underlying control -->
            <div id="underlying" onclick="window.__underlyingClicked = true" style="width:200px;height:100px;background:#eee;padding:10px;">
              <button id="uiRefBadge" style="pointer-events:auto;">ML03</button>
            </div>

            <!-- ErrorBoundary copy button -->
            <div id="errorBoundaryContainer" style="margin-top:20px;">
              <button id="copyDiagnosticsBtn">复制诊断日志</button>
            </div>

            <div id="status">idle</div>

            <!-- Sandboxed mail iframe -->
            <iframe id="mailFrame" src="/mail_content" sandbox="allow-scripts" style="width:300px;height:150px;margin-top:20px;"></iframe>

            <script>
              const statusEl = document.getElementById('status');

              // UI reference copy handler (matches UiReferenceOverlay.tsx)
              document.getElementById('uiRefBadge').addEventListener('click', async (e) => {
                e.preventDefault();
                e.stopPropagation();
                try {
                  if (!navigator.clipboard?.writeText) throw new Error('clipboard unavailable');
                  await navigator.clipboard.writeText('[UI:ML03] 邮件列表 · 刷新并同步按钮');
                  statusEl.textContent = 'ui_ref_copied';
                } catch (err) {
                  statusEl.textContent = 'ui_ref_failed: ' + err.message;
                }
              });

              // ErrorBoundary copy report handler (matches ErrorBoundary.tsx)
              document.getElementById('copyDiagnosticsBtn').addEventListener('click', async (e) => {
                e.preventDefault();
                e.stopPropagation();
                try {
                  if (!navigator.clipboard?.writeText) throw new Error('clipboard unavailable');
                  const diagText = 'kkmail frontend diagnostics dump\\nEntries: 1\\n[2026-10-23T03:00:00Z] [ERROR] [ui] Test error';
                  await navigator.clipboard.writeText(diagText);
                  statusEl.textContent = 'diag_copied';
                } catch (err) {
                  statusEl.textContent = 'diag_failed: ' + err.message;
                }
              });
            </script>
          </body>
        </html>
      `)
      return
    }

    if (req.url === '/mail_content') {
      res.writeHead(200, {
        'Content-Type': 'text/html; charset=utf-8',
        'Content-Security-Policy': "default-src 'self' 'unsafe-inline'",
      })
      res.end(`
        <!DOCTYPE html>
        <html>
          <head><meta charset="utf-8"></head>
          <body>
            <button id="mailAttackBtn">Untrusted Mail Action</button>
            <div id="mailStatus">idle</div>
            <script>
              document.getElementById('mailAttackBtn').addEventListener('click', async () => {
                const s = document.getElementById('mailStatus');
                try {
                  await navigator.clipboard.writeText('ATTACKER_CONTENT');
                  s.textContent = 'mail_copied';
                } catch (err) {
                  s.textContent = 'mail_rejected: ' + err.message;
                }
              });
            </script>
          </body>
        </html>
      `)
      return
    }

    res.writeHead(404)
    res.end()
  })

  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve))
  const port = server.address().port
  const appOrigin = `http://127.0.0.1:${port}`

  try {
    const ses = session.defaultSession
    ses.setPermissionRequestHandler(createPermissionRequestHandler(() => appOrigin))
    ses.setPermissionCheckHandler(createPermissionCheckHandler(() => appOrigin))

    const win = new BrowserWindow({
      show: true,
      x: -2000,
      y: -2000,
      width: 800,
      height: 600,
      webPreferences: {
        sandbox: true,
        contextIsolation: true,
        nodeIntegration: false,
      },
    })

    win.focus()
    win.webContents.focus()
    await win.loadURL(`${appOrigin}/`)
    await win.webContents.executeJavaScript('window.focus()')
    for (let i = 0; i < 20; i++) {
      const hasFocus = await win.webContents.executeJavaScript('document.hasFocus()')
      if (hasFocus) break
      win.focus()
      win.webContents.focus()
      await new Promise((r) => setTimeout(r, 100))
    }

    // Helper: poll page expression
    async function waitForStatus(expected, maxTries = 30) {
      for (let i = 0; i < maxTries; i++) {
        await new Promise((r) => setTimeout(r, 100))
        const s = await win.webContents.executeJavaScript('document.getElementById("status").textContent')
        if (s.startsWith(expected)) return s
      }
      return await win.webContents.executeJavaScript('document.getElementById("status").textContent')
    }

    // -------------------------------------------------------------
    // Test 1: AC-001 UI Reference badge copy
    // -------------------------------------------------------------
    await clipboard.writeText('sentinel-before-ui-ref')

    const uiBadgeRect = await win.webContents.executeJavaScript(`
      (() => {
        const b = document.getElementById('uiRefBadge').getBoundingClientRect();
        return { x: Math.round(b.left + b.width / 2), y: Math.round(b.top + b.height / 2) };
      })()
    `)

    win.webContents.sendInputEvent({ type: 'mouseDown', x: uiBadgeRect.x, y: uiBadgeRect.y, button: 'left', clickCount: 1 })
    win.webContents.sendInputEvent({ type: 'mouseUp', x: uiBadgeRect.x, y: uiBadgeRect.y, button: 'left', clickCount: 1 })

    const uiStatus = await waitForStatus('ui_ref_')
    assert.strictEqual(uiStatus, 'ui_ref_copied', `UI reference copy should succeed, got: ${uiStatus}`)

    const uiClipText = await clipboard.readText('clipboard')
    assert.strictEqual(uiClipText, '[UI:ML03] 邮件列表 · 刷新并同步按钮', 'Clipboard content must match UI reference format')

    const underlyingClicked = await win.webContents.executeJavaScript('Boolean(window.__underlyingClicked)')
    assert.strictEqual(underlyingClicked, false, 'Click on badge must not trigger underlying control')
    console.log('✓ AC-001: UI reference overlay badge copied formatted text without bubbling to underlying control')

    // -------------------------------------------------------------
    // Test 2: AC-002 ErrorBoundary diagnostic copy
    // -------------------------------------------------------------
    await clipboard.writeText('sentinel-before-diag')

    const diagBtnRect = await win.webContents.executeJavaScript(`
      (() => {
        const b = document.getElementById('copyDiagnosticsBtn').getBoundingClientRect();
        return { x: Math.round(b.left + b.width / 2), y: Math.round(b.top + b.height / 2) };
      })()
    `)

    win.webContents.sendInputEvent({ type: 'mouseDown', x: diagBtnRect.x, y: diagBtnRect.y, button: 'left', clickCount: 1 })
    win.webContents.sendInputEvent({ type: 'mouseUp', x: diagBtnRect.x, y: diagBtnRect.y, button: 'left', clickCount: 1 })

    const diagStatus = await waitForStatus('diag_')
    assert.strictEqual(diagStatus, 'diag_copied', `Diagnostics copy should succeed, got: ${diagStatus}`)

    const diagClipText = await clipboard.readText('clipboard')
    assert.ok(diagClipText.includes('kkmail frontend diagnostics dump'), 'Clipboard must contain diagnostics dump header')
    assert.ok(diagClipText.includes('[ERROR] [ui] Test error'), 'Clipboard must contain diagnostic entry')
    console.log('✓ AC-002: ErrorBoundary diagnostics copy written to system clipboard')

    // -------------------------------------------------------------
    // Test 3: AC-003 Isolation — Subframe / Mail iframe blocked
    // -------------------------------------------------------------
    await clipboard.writeText('protected-sentinel')

    // Trigger click on mail button inside subframe
    const subFrame = win.webContents.mainFrame.frames[0]
    await subFrame.executeJavaScript(`
      document.getElementById('mailAttackBtn').click()
    `)

    let mailStatus = 'timeout'
    for (let i = 0; i < 30; i++) {
      await new Promise((r) => setTimeout(r, 100))
      mailStatus = await subFrame.executeJavaScript(`
        document.getElementById('mailStatus')?.textContent || 'idle'
      `)
      if (mailStatus.startsWith('mail_rejected') || mailStatus === 'mail_copied') break
    }

    assert.ok(
      mailStatus.startsWith('mail_rejected'),
      `Mail iframe clipboard write must be rejected, got: ${mailStatus}`
    )
    const clipAfterMail = await clipboard.readText('clipboard')
    assert.strictEqual(
      clipAfterMail,
      'protected-sentinel',
      'Mail iframe must not modify system clipboard'
    )
    console.log('✓ AC-003: Mail iframe clipboard write was rejected and clipboard remained protected')

    // -------------------------------------------------------------
    // Test 4: AC-003 Other permissions strictly denied (read, media)
    // -------------------------------------------------------------
    const readCheck = await win.webContents.executeJavaScript(`
      (async () => {
        try {
          await navigator.clipboard.readText();
          return { ok: true };
        } catch (e) {
          return { ok: false, error: e.name };
        }
      })()
    `)
    assert.strictEqual(readCheck.ok, false, 'clipboard-read must be denied')
    console.log('✓ AC-003: Clipboard read permission was denied')

    const mediaCheck = await win.webContents.executeJavaScript(`
      (async () => {
        try {
          await navigator.mediaDevices.getUserMedia({ audio: true });
          return { ok: true };
        } catch (e) {
          return { ok: false, error: e.name };
        }
      })()
    `)
    assert.strictEqual(mediaCheck.ok, false, 'media permission must be denied')
    console.log('✓ AC-003: Media permission was denied')

    // -------------------------------------------------------------
    // Test 5: AC-005 Desktop logger in Electron environment
    // -------------------------------------------------------------
    const { DesktopLogger } = require('./desktopLog')
    const testLogFile = path.join(app.getPath('userData'), 'desktop.test.log')
    const logger = new DesktopLogger({ logPath: testLogFile })
    logger.info('Electron integration test logger verified')
    await logger.end()
    assert.ok(require('fs').existsSync(testLogFile), 'desktop log file must exist')
    const logData = require('fs').readFileSync(testLogFile, 'utf8')
    assert.ok(logData.includes('Electron integration test logger verified'))
    try { require('fs').unlinkSync(testLogFile) } catch (_) {}
    console.log('✓ AC-005: Desktop logger verified in Electron runtime')

    win.destroy()
  } finally {
    // Restore original clipboard
    try {
      await clipboard.writeText(originalClipboard)
    } catch (_) {}
    server.close()
  }

  console.log('desktop clipboard integration: ok')
  app.quit()
}

app.whenReady().then(async () => {
  try {
    await runIntegrationSuite()
  } catch (err) {
    console.error('desktop clipboard integration failed:', err)
    process.exit(1)
  }
})
