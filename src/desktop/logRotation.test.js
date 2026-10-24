const assert = require('assert')
const fs = require('fs')
const path = require('path')
const os = require('os')
const { rotateLogFile, RotatingLogStream } = require('./logRotation')

const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'kkmail-log-test-'))

;(async () => {
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

    // Test 3: RotatingLogStream write does not invoke fs.writeSync in normal path
    const asyncFile = path.join(tmpDir, 'async.log')
    const asyncStream = new RotatingLogStream(asyncFile, { maxBytes: 1000 })
    let writeSyncCalled = false
    const origWriteSync = fs.writeSync
    fs.writeSync = (...args) => {
      writeSyncCalled = true
      return origWriteSync.apply(fs, args)
    }
    try {
      asyncStream.write('async-chunk-1\n')
      asyncStream.write('async-chunk-2\n')
      assert.strictEqual(writeSyncCalled, false, 'write() should not call fs.writeSync synchronously')
    } finally {
      fs.writeSync = origWriteSync
    }
    asyncStream.end()
    assert.strictEqual(fs.readFileSync(asyncFile, 'utf8'), 'async-chunk-1\nasync-chunk-2\n')

    // Test 4: Partial write continues writing remaining buffer until complete
    const partialFile = path.join(tmpDir, 'partial.log')
    const partialStream = new RotatingLogStream(partialFile, { maxBytes: 1000 })
    const origWrite = fs.write
    let callCount = 0
    fs.write = (fd, buf, offset, length, position, cb) => {
      callCount++
      if (callCount === 1) {
        // Write only 4 bytes in the first chunk
        return origWrite.call(fs, fd, buf, offset, Math.min(4, length), position, cb)
      }
      return origWrite.call(fs, fd, buf, offset, length, position, cb)
    }
    try {
      partialStream.write('abcdefghijklmn\n')
      await partialStream.drain()
      await partialStream.end()
      assert.ok(callCount >= 2, 'fs.write should be called again for remaining buffer')
      assert.strictEqual(fs.readFileSync(partialFile, 'utf8'), 'abcdefghijklmn\n')
    } finally {
      fs.write = origWrite
    }

    // Test 5: Write errors are recorded and accurately reported to drain/waiters
    const errorFile = path.join(tmpDir, 'error.log')
    let caughtError = null
    const errorStream = new RotatingLogStream(errorFile, {
      maxBytes: 1000,
      onError: (err) => { caughtError = err },
    })
    const origWrite2 = fs.write
    fs.write = (_fd, _buf, _offset, _len, _pos, cb) => {
      cb(new Error('simulated disk I/O failure'))
    }
    try {
      errorStream.write('should fail\n')
      let drainFailed = false
      try {
        await errorStream.drain()
      } catch (err) {
        drainFailed = true
        assert.strictEqual(err.message, 'simulated disk I/O failure')
      }
      assert.strictEqual(drainFailed, true, 'drain() must reject on write failure')
      assert.strictEqual(errorStream.lastError.message, 'simulated disk I/O failure')
      assert.strictEqual(caughtError && caughtError.message, 'simulated disk I/O failure')
    } finally {
      fs.write = origWrite2
      await errorStream.end().catch(() => {})
    }

    // Test 6: A failed rotation drops queued data and rejects drain waiters
    const unavailableFile = path.join(tmpDir, 'unavailable.log')
    const unavailableError = new Error('simulated log reopen failure')
    let unavailableErrorCallback = null
    const unavailableStream = new RotatingLogStream(unavailableFile, {
      maxBytes: 10,
      onError: (err) => { unavailableErrorCallback = err },
    })
    unavailableStream.write('12345678')
    await unavailableStream.drain()
    const origOpenSync = fs.openSync
    fs.openSync = () => { throw unavailableError }
    try {
      unavailableStream.write('abcdefghij')
      const drainPromise = unavailableStream.drain()
      await assert.rejects(drainPromise, (err) => err === unavailableError)
      assert.strictEqual(unavailableStream.fd, null)
      assert.strictEqual(unavailableStream.queue.length, 0)
      assert.strictEqual(unavailableStream.lastError, unavailableError)
      assert.strictEqual(unavailableErrorCallback, unavailableError)
    } finally {
      fs.openSync = origOpenSync
      await unavailableStream.end().catch(() => {})
    }

    // Test 7: The queue is bounded and overflow is reported to drain waiters
    const boundedFile = path.join(tmpDir, 'bounded.log')
    let overflowError = null
    const boundedStream = new RotatingLogStream(boundedFile, {
      maxBytes: 1000,
      maxQueueLength: 1,
      onError: (err) => { overflowError = err },
    })
    let releaseWrite = null
    const origWrite4 = fs.write
    fs.write = (fd, buf, offset, length, position, cb) => {
      if (!releaseWrite) {
        releaseWrite = () => origWrite4.call(fs, fd, buf, offset, length, position, cb)
        return
      }
      return origWrite4.call(fs, fd, buf, offset, length, position, cb)
    }
    try {
      boundedStream.write('in-flight\n')
      await new Promise((resolve) => setImmediate(resolve))
      boundedStream.write('queued\n')
      const drainPromise = boundedStream.drain()
      assert.strictEqual(boundedStream.write('overflow\n'), false)
      assert.strictEqual(boundedStream.queue.length, 0)
      assert.match(boundedStream.lastError.message, /queue limit exceeded/)
      releaseWrite()
      await assert.rejects(drainPromise, /queue limit exceeded/)
      assert.strictEqual(overflowError, boundedStream.lastError)
    } finally {
      fs.write = origWrite4
      await boundedStream.end().catch(() => {})
    }

    // Test 8: In-flight write serializes close (fd remains open until in-flight finishes)
    const inflightFile = path.join(tmpDir, 'inflight.log')
    const inflightStream = new RotatingLogStream(inflightFile, { maxBytes: 1000 })
    let writeBlocked = true
    let delayedCb = null
    const origWrite3 = fs.write
    fs.write = (fd, buf, offset, length, position, cb) => {
      if (writeBlocked) {
        writeBlocked = false
        delayedCb = () => origWrite3.call(fs, fd, buf, offset, length, position, cb)
        return
      }
      return origWrite3.call(fs, fd, buf, offset, length, position, cb)
    }
    try {
      inflightStream.write('inflight-content\n')
      await new Promise((r) => setImmediate(r))
      assert.strictEqual(inflightStream.writing, true, 'must be in writing state')

      // Call end while write is in flight
      const endPromise = inflightStream.end()
      assert.ok(inflightStream.fd !== null, 'fd must NOT be closed while in-flight write is pending')

      delayedCb()
      await endPromise
      assert.strictEqual(inflightStream.fd, null, 'fd must be closed after in-flight write finishes')
      assert.strictEqual(fs.readFileSync(inflightFile, 'utf8'), 'inflight-content\n')
    } finally {
      fs.write = origWrite3
    }

    console.log('logRotation.test.js: ok')
  } finally {
    fs.rmSync(tmpDir, { recursive: true, force: true })
  }
})().catch((err) => {
  console.error(err)
  process.exit(1)
})
