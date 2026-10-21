const assert = require('assert')
const fs = require('fs')
const path = require('path')
const os = require('os')
const { rotateLogFile, RotatingLogStream } = require('./logRotation')

const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'kkmail-log-test-'))

try {
  // Test 1: rotateLogFile respects size threshold
  const logFile = path.join(tmpDir, 'test.log')
  fs.writeFileSync(logFile, 'hello world\n')

  // Not rotated if under threshold
  const r1 = rotateLogFile(logFile, 100, 3)
  assert.strictEqual(r1, false)
  assert.strictEqual(fs.existsSync(logFile), true)
  assert.strictEqual(fs.existsSync(path.join(tmpDir, 'test.1.log')), false)

  // Rotated when size >= maxBytes
  const r2 = rotateLogFile(logFile, 5, 3)
  assert.strictEqual(r2, true)
  assert.strictEqual(fs.existsSync(logFile), false)
  assert.strictEqual(fs.existsSync(path.join(tmpDir, 'test.1.log')), true)

  // Rotating again pushes 1 -> 2
  fs.writeFileSync(logFile, 'second line\n')
  rotateLogFile(logFile, 5, 3)
  assert.strictEqual(fs.existsSync(path.join(tmpDir, 'test.2.log')), true)
  assert.strictEqual(fs.readFileSync(path.join(tmpDir, 'test.2.log'), 'utf8'), 'hello world\n')
  assert.strictEqual(fs.readFileSync(path.join(tmpDir, 'test.1.log'), 'utf8'), 'second line\n')

  // Test 2: RotatingLogStream writes and automatically rotates
  const streamFile = path.join(tmpDir, 'stream.log')
  const stream = new RotatingLogStream(streamFile, { maxBytes: 20, maxFiles: 2 })
  stream.write('chunk-1-1234567890\n') // 19 bytes
  assert.strictEqual(fs.existsSync(streamFile), true)
  stream.write('chunk-2-1234567890\n') // exceeds 20 bytes -> should rotate
  stream.end()

  assert.strictEqual(fs.existsSync(path.join(tmpDir, 'stream.1.log')), true)
  assert.strictEqual(fs.existsSync(streamFile), true)

  console.log('logRotation.test.js: ok')
} finally {
  fs.rmSync(tmpDir, { recursive: true, force: true })
}
