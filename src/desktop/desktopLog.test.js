const assert = require('assert')
const fs = require('fs')
const os = require('os')
const path = require('path')
const {
  DesktopLogger,
  formatIsoTimestamp,
  formatMessage,
} = require('./desktopLog')

async function runTests() {
  // 1. Timestamp formatting test
  const ts = formatIsoTimestamp()
  const isoPattern = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}[+-]\d{2}:\d{2}$/
  assert.ok(isoPattern.test(ts), `Timestamp must match ISO 8601 with timezone: ${ts}`)

  // 2. Format message test
  const err = new Error('Test error message')
  const formattedErr = formatMessage('ERROR', [err])
  assert.ok(formattedErr.includes('[ERROR]'), 'Must include log level')
  assert.ok(formattedErr.includes('Test error message'), 'Must include error message')
  assert.ok(formattedErr.includes(err.stack.split('\n')[1].trim()), 'Must include stack trace')

  // 3. File logging test in temporary directory
  const tempDir = fs.mkdtempSync(path.join(os.tmpdir(), 'desktop-log-test-'))
  const logFile = path.join(tempDir, 'desktop.log')

  try {
    const logger = new DesktopLogger({ logPath: logFile })
    logger.info('Desktop logger initialized successfully')
    logger.warn('Sample warning message', { code: 42 })
    logger.error('Sample error message', new Error('Boom'))

    await logger.end()

    assert.ok(fs.existsSync(logFile), 'desktop.log must exist')
    const content = fs.readFileSync(logFile, 'utf8')
    assert.ok(content.includes('[INFO] Desktop logger initialized successfully'))
    assert.ok(content.includes('[WARN] Sample warning message'))
    assert.ok(content.includes('{ code: 42 }'))
    assert.ok(content.includes('[ERROR] Sample error message Error: Boom'))
  } finally {
    try { fs.rmSync(tempDir, { recursive: true, force: true }) } catch (_) {}
  }

  // 4. Hook console & process test
  const tempDir2 = fs.mkdtempSync(path.join(os.tmpdir(), 'desktop-log-hook-test-'))
  const logFile2 = path.join(tempDir2, 'desktop.log')

  try {
    const logger = new DesktopLogger({ logPath: logFile2 })
    logger.hookConsoleAndProcess()

    // Test console hooking
    console.log('Hooked console.log message')
    console.warn('Hooked console.warn message')
    console.error('Hooked console.error message')

    // Test process listeners
    process.emit('uncaughtException', new Error('Simulated uncaught exception'))
    process.emit('unhandledRejection', 'Simulated unhandled rejection')

    await logger.end()

    const content2 = fs.readFileSync(logFile2, 'utf8')
    assert.ok(content2.includes('[INFO] Hooked console.log message'))
    assert.ok(content2.includes('[WARN] Hooked console.warn message'))
    assert.ok(content2.includes('[ERROR] Hooked console.error message'))
    assert.ok(content2.includes('[FATAL] Uncaught exception in main process: Error: Simulated uncaught exception'))
    assert.ok(content2.includes('[ERROR] Unhandled rejection in main process: Simulated unhandled rejection'))
  } finally {
    try { fs.rmSync(tempDir2, { recursive: true, force: true }) } catch (_) {}
  }

  // 5. Rotation test
  const tempDir3 = fs.mkdtempSync(path.join(os.tmpdir(), 'desktop-log-rot-test-'))
  const logFile3 = path.join(tempDir3, 'desktop.log')

  try {
    const smallMaxBytes = 300
    const logger = new DesktopLogger({ logPath: logFile3, maxBytes: smallMaxBytes, maxFiles: 2 })
    for (let i = 0; i < 20; i++) {
      logger.info(`Message line ${i}: ${'x'.repeat(40)}`)
    }
    await logger.end()

    assert.ok(fs.existsSync(logFile3), 'Current desktop.log must exist')
    const backup1 = path.join(tempDir3, 'desktop.1.log')
    assert.ok(fs.existsSync(backup1), 'desktop.1.log must exist after rotation')
  } finally {
    try { fs.rmSync(tempDir3, { recursive: true, force: true }) } catch (_) {}
  }

  console.log('desktopLog.test.js: ok')
}

runTests().catch((err) => {
  console.error('desktopLog.test.js failed:', err)
  process.exit(1)
})
