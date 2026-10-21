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
 * Uses in-memory buffering and non-blocking fs.write to avoid stalling the Electron main event loop.
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
    } catch (_) {
      this.fd = null
    }
  }

  write(chunk) {
    if (this.closed) return
    const buf = Buffer.isBuffer(chunk) ? chunk : Buffer.from(String(chunk), 'utf8')
    if (buf.length === 0) return

    if (this.currentSize + buf.length >= this.maxBytes) {
      this._flushSync()
      this._rotate()
    }

    this.queue.push(buf)
    this.currentSize += buf.length
    this._scheduleFlush()
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
    if (this.writing || this.closed || this.queue.length === 0 || this.fd === null) return
    this.writing = true
    const buf = this.queue.length === 1 ? this.queue.shift() : Buffer.concat(this.queue.splice(0))
    fs.write(this.fd, buf, 0, buf.length, null, () => {
      this.writing = false
      if (!this.closed && this.queue.length > 0) {
        this._scheduleFlush()
      }
    })
  }

  _flushSync() {
    this.flushScheduled = false
    if (this.fd === null || this.queue.length === 0) return
    try {
      const buf = this.queue.length === 1 ? this.queue.shift() : Buffer.concat(this.queue.splice(0))
      fs.writeSync(this.fd, buf)
    } catch (_) {}
  }

  _rotate() {
    if (this.fd !== null) {
      try { fs.closeSync(this.fd) } catch (_) {}
      this.fd = null
    }
    rotateLogFile(this.filePath, 0, this.maxFiles)
    this.currentSize = 0
    try {
      this.fd = fs.openSync(this.filePath, 'a')
    } catch (_) {
      this.fd = null
    }
  }

  end() {
    this.closed = true
    this._flushSync()
    if (this.fd !== null) {
      try { fs.closeSync(this.fd) } catch (_) {}
      this.fd = null
    }
  }
}

module.exports = { rotateLogFile, RotatingLogStream, DEFAULT_MAX_BYTES, DEFAULT_MAX_FILES }
