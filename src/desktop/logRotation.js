/**
 * Lightweight, zero-dependency log rotation for desktop log files.
 *
 * Prevents mail-core.log and postgres.log from expanding indefinitely on user disks.
 */
const fs = require('fs')
const path = require('path')

const DEFAULT_MAX_BYTES = 10 * 1024 * 1024 // 10 MB per file
const DEFAULT_MAX_FILES = 3 // Keep at most 3 historical rotated files

/**
 * Rotate a log file if it exceeds maxBytes.
 * Example: app.log -> app.1.log -> app.2.log -> app.3.log (older ones deleted).
 */
function rotateLogFile(filePath, maxBytes = DEFAULT_MAX_BYTES, maxFiles = DEFAULT_MAX_FILES) {
  try {
    if (!fs.existsSync(filePath)) return false
    const stat = fs.statSync(filePath)
    if (stat.size < maxBytes) return false

    const dir = path.dirname(filePath)
    const ext = path.extname(filePath)
    const base = path.basename(filePath, ext)

    // Remove oldest archive if it exists
    const oldest = path.join(dir, `${base}.${maxFiles}${ext}`)
    if (fs.existsSync(oldest)) {
      try { fs.unlinkSync(oldest) } catch (_) {}
    }

    // Shift previous backups: app.2.log -> app.3.log, app.1.log -> app.2.log
    for (let i = maxFiles - 1; i >= 1; i--) {
      const src = path.join(dir, `${base}.${i}${ext}`)
      const dst = path.join(dir, `${base}.${i + 1}${ext}`)
      if (fs.existsSync(src)) {
        try { fs.renameSync(src, dst) } catch (_) {}
      }
    }

    // Move current file to app.1.log
    const firstBackup = path.join(dir, `${base}.1${ext}`)
    fs.renameSync(filePath, firstBackup)
    return true
  } catch (_) {
    return false
  }
}

/**
 * An asynchronous write stream that automatically rotates when reaching maxBytes.
 * Uses in-memory buffering and serialized non-blocking fs.write to avoid stalling Electron main.
 * Serializes in-flight writes, rotations, and close operations so logs are never dropped or corrupted.
 */
class RotatingLogStream {
  constructor(filePath, options = {}) {
    this.filePath = filePath
    this.maxBytes = options.maxBytes || DEFAULT_MAX_BYTES
    this.maxFiles = options.maxFiles || DEFAULT_MAX_FILES
    this.currentSize = 0
    this.fd = null
    this.queue = []
    this.writing = false
    this.flushScheduled = false
    this.closed = false
    this.lastError = null
    this.drainWaiters = []
    this.onError = typeof options.onError === 'function' ? options.onError : null

    this._init()
  }

  _init() {
    try {
      fs.mkdirSync(path.dirname(this.filePath), { recursive: true })
      rotateLogFile(this.filePath, this.maxBytes, this.maxFiles)

      if (fs.existsSync(this.filePath)) {
        this.currentSize = fs.statSync(this.filePath).size
      } else {
        this.currentSize = 0
      }
      this.fd = fs.openSync(this.filePath, 'a')
    } catch (err) {
      this.fd = null
      this.lastError = err
    }
  }

  write(chunk) {
    if (this.closed) return false
    const buf = Buffer.isBuffer(chunk) ? chunk : Buffer.from(String(chunk), 'utf8')
    if (buf.length === 0) return true

    this.queue.push(buf)
    this._scheduleFlush()
    return true
  }

  _scheduleFlush() {
    if (this.flushScheduled || this.writing || this.closed) return
    this.flushScheduled = true
    setImmediate(() => {
      this.flushScheduled = false
      this._flushAsync()
    })
  }

  _flushAsync() {
    if (this.writing || this.fd === null) return

    if (this.queue.length === 0) {
      this._notifyDrain()
      return
    }

    // Rotate only when idle (no in-flight write) if next chunk exceeds maxBytes
    const nextLen = this.queue[0].length
    if (this.currentSize + nextLen >= this.maxBytes && this.currentSize > 0) {
      this._rotate()
    }

    if (this.fd === null) {
      this._notifyDrain(this.lastError || new Error('Log file descriptor unavailable'))
      return
    }

    const buf = this.queue.shift()
    this._writeAsyncChunk(buf, 0)
  }

  _writeAsyncChunk(buf, offset) {
    this.writing = true
    const remaining = buf.length - offset
    fs.write(this.fd, buf, offset, remaining, null, (err, bytesWritten) => {
      if (err) {
        this.writing = false
        this.lastError = err
        if (typeof this.onError === 'function') {
          try { this.onError(err) } catch (_) {}
        } else {
          console.warn('[logRotation] write error:', err && err.message ? err.message : err)
        }
        this._notifyDrain(err)
        return
      }

      if (bytesWritten < remaining) {
        this.currentSize += bytesWritten
        this._writeAsyncChunk(buf, offset + bytesWritten)
        return
      }

      this.currentSize += bytesWritten
      this.writing = false

      if (this.queue.length > 0) {
        this._scheduleFlush()
      } else {
        this._notifyDrain()
      }
    })
  }

  _flushSync() {
    this.flushScheduled = false
    while (this.queue.length > 0) {
      const next = this.queue[0]
      if (this.currentSize + next.length >= this.maxBytes && this.currentSize > 0) {
        this._rotate()
      }
      if (this.fd === null) break
      const buf = this.queue.shift()
      let offset = 0
      while (offset < buf.length) {
        try {
          const written = fs.writeSync(this.fd, buf, offset, buf.length - offset)
          if (written <= 0) break
          offset += written
          this.currentSize += written
        } catch (err) {
          this.lastError = err
          if (typeof this.onError === 'function') {
            try { this.onError(err) } catch (_) {}
          }
          break
        }
      }
    }
  }

  _rotate() {
    this._closeFd()
    rotateLogFile(this.filePath, 0, this.maxFiles)
    this.currentSize = 0
    try {
      this.fd = fs.openSync(this.filePath, 'a')
    } catch (err) {
      this.fd = null
      this.lastError = err
    }
  }

  _closeFd() {
    if (this.fd !== null) {
      try { fs.closeSync(this.fd) } catch (_) {}
      this.fd = null
    }
  }

  drain() {
    if (!this.writing && this.queue.length === 0) {
      return Promise.resolve()
    }
    return new Promise((resolve, reject) => {
      this.drainWaiters.push({ resolve, reject })
    })
  }

  _notifyDrain(err = null) {
    if (this.writing || (this.queue.length > 0 && !err && this.fd !== null)) {
      return
    }
    const waiters = this.drainWaiters.splice(0)
    for (const { resolve, reject } of waiters) {
      if (err) reject(err)
      else resolve()
    }
  }

  end(cb) {
    this.closed = true
    if (this.writing) {
      const p = this.drain().then(() => {
        this._closeFd()
        if (typeof cb === 'function') cb()
      }).catch((err) => {
        this._closeFd()
        if (typeof cb === 'function') cb(err)
      })
      return p
    }

    this._flushSync()
    this._closeFd()
    this._notifyDrain()
    if (typeof cb === 'function') cb()
    return Promise.resolve()
  }
}

module.exports = { rotateLogFile, RotatingLogStream, DEFAULT_MAX_BYTES, DEFAULT_MAX_FILES }
