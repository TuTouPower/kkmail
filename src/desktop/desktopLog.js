/**
 * Main process file logging infrastructure.
 *
 * Writes desktop main process lifecycle, uncaught exceptions, and console messages
 * to desktop.log under userData (with automatic rotation).
 */
'use strict'

const fs = require('fs')
const path = require('path')
const util = require('util')
const { RotatingLogStream } = require('./logRotation')

function formatIsoTimestamp(d = new Date()) {
  const pad = (n, len = 2) => String(n).padStart(len, '0')
  const year = d.getFullYear()
  const month = pad(d.getMonth() + 1)
  const day = pad(d.getDate())
  const hours = pad(d.getHours())
  const minutes = pad(d.getMinutes())
  const seconds = pad(d.getSeconds())
  const ms = pad(d.getMilliseconds(), 3)
  const offsetMin = -d.getTimezoneOffset()
  const sign = offsetMin >= 0 ? '+' : '-'
  const absOffset = Math.abs(offsetMin)
  const offsetH = pad(Math.floor(absOffset / 60))
  const offsetM = pad(absOffset % 60)
  return `${year}-${month}-${day}T${hours}:${minutes}:${seconds}.${ms}${sign}${offsetH}:${offsetM}`
}

function formatMessage(level, args) {
  const ts = formatIsoTimestamp()
  const rendered = args
    .map((arg) => {
      if (arg instanceof Error) {
        return arg.stack || `${arg.name}: ${arg.message}`
      }
      if (typeof arg === 'object' && arg !== null) {
        try {
          return util.inspect(arg, { depth: 4, breakLength: Infinity })
        } catch (_) {
          return String(arg)
        }
      }
      return String(arg)
    })
    .join(' ')
  return `[${ts}] [${level}] ${rendered}\n`
}

class DesktopLogger {
  constructor(options = {}) {
    this.app = options.app || null
    this.logDir = options.logDir || (options.app && typeof options.app.getPath === 'function' ? options.app.getPath('userData') : process.cwd())
    this.logPath = options.logPath || path.join(this.logDir, 'desktop.log')
    this.stream = null
    this.origConsole = null
    this.hooked = false
    this._initStream(options)
  }

  _initStream(options) {
    try {
      fs.mkdirSync(path.dirname(this.logPath), { recursive: true })
      this.stream = new RotatingLogStream(this.logPath, {
        maxBytes: options.maxBytes || 10 * 1024 * 1024,
        maxFiles: options.maxFiles || 3,
        onError: (err) => {
          if (this.origConsole && this.origConsole.warn) {
            this.origConsole.warn('[desktopLog] write error:', err && err.message)
          }
        },
      })
    } catch (err) {
      this.stream = null
      console.warn('[desktopLog] failed to initialize log stream:', err && err.message)
    }
  }

  write(level, args) {
    if (!this.stream) return
    try {
      const line = formatMessage(level, args)
      this.stream.write(line)
    } catch (_) {
      // Fallback safe: never crash application due to logger failure
    }
  }

  info(...args) {
    this.write('INFO', args)
    if (this.origConsole) this.origConsole.log(...args)
    else console.log(...args)
  }

  warn(...args) {
    this.write('WARN', args)
    if (this.origConsole) this.origConsole.warn(...args)
    else console.warn(...args)
  }

  error(...args) {
    this.write('ERROR', args)
    if (this.origConsole) this.origConsole.error(...args)
    else console.error(...args)
  }

  hookConsoleAndProcess() {
    if (this.hooked) return
    this.hooked = true

    this.origConsole = {
      log: console.log.bind(console),
      info: console.info.bind(console),
      warn: console.warn.bind(console),
      error: console.error.bind(console),
    }

    console.log = (...args) => {
      this.write('INFO', args)
      this.origConsole.log(...args)
    }
    console.info = (...args) => {
      this.write('INFO', args)
      this.origConsole.info(...args)
    }
    console.warn = (...args) => {
      this.write('WARN', args)
      this.origConsole.warn(...args)
    }
    console.error = (...args) => {
      this.write('ERROR', args)
      this.origConsole.error(...args)
    }

    this._onUncaughtException = (err, origin) => {
      this.write('FATAL', ['Uncaught exception in main process:', err, origin || ''])
      return this.end().catch(() => {}).then(() => {
        process.exitCode = 1
        if (this.app && typeof this.app.quit === 'function') {
          this.app.quit()
        } else {
          process.exit(1)
        }
      })
    }
    this._onUnhandledRejection = (reason, promise) => {
      this.write('ERROR', ['Unhandled rejection in main process:', reason])
    }

    process.on('uncaughtException', this._onUncaughtException)
    process.on('unhandledRejection', this._onUnhandledRejection)
  }

  unhook() {
    if (!this.hooked) return
    this.hooked = false

    if (this.origConsole) {
      console.log = this.origConsole.log
      console.info = this.origConsole.info
      console.warn = this.origConsole.warn
      console.error = this.origConsole.error
      this.origConsole = null
    }

    if (this._onUncaughtException) {
      process.removeListener('uncaughtException', this._onUncaughtException)
      this._onUncaughtException = null
    }
    if (this._onUnhandledRejection) {
      process.removeListener('unhandledRejection', this._onUnhandledRejection)
      this._onUnhandledRejection = null
    }
  }

  async end() {
    this.unhook()
    if (this.stream) {
      const s = this.stream
      this.stream = null
      await s.end()
    }
  }
}

let defaultLogger = null

function getDesktopLogger(options) {
  if (!defaultLogger) {
    defaultLogger = new DesktopLogger(options)
  }
  return defaultLogger
}

module.exports = {
  DesktopLogger,
  getDesktopLogger,
  formatIsoTimestamp,
  formatMessage,
}
