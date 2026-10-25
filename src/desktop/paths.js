/** Pure helpers shared by main.js and its tests. */
const path = require('path')
const net = require('net')

const SIDECAR_NAME = 'kkmail-backend'

function sidecarFileName(platform) {
  return platform === 'win32' ? `${SIDECAR_NAME}.exe` : SIDECAR_NAME
}

function sidecarPath(resourcesPath, platform) {
  if (!resourcesPath) return ''
  return path.join(resourcesPath, 'backend', sidecarFileName(platform))
}

function frontendDistPath(resourcesPath) {
  if (!resourcesPath) return ''
  return path.join(resourcesPath, 'frontend', 'dist')
}

function isLoopbackHostname(hostname) {
  const host = hostname.toLowerCase().replace(/^\[|\]$/g, '').replace(/\.$/, '')
  if (host === 'localhost' || host.endsWith('.localhost')) return true
  if (net.isIP(host) === 4) return Number(host.split('.')[0]) === 127
  return net.isIP(host) === 6 && host === '::1'
}

function isAllowedExternalUrl(target) {
  try {
    const u = new URL(target)
    // Reject embedded credentials (https://user:pass@host/…) — phishing / leak risk.
    if (u.username || u.password) return false
    if (u.protocol === 'https:' || u.protocol === 'mailto:') return true
    return u.protocol === 'http:' && isLoopbackHostname(u.hostname)
  } catch {
    return false
  }
}

function isLocalAppUrl(target, origin) {
  try {
    return new URL(target).origin === origin
  } catch {
    return false
  }
}

function createExternalWindowHandler(openExternal, appOrigin) {
  return ({ url }) => {
    if (!isAllowedExternalUrl(url)) return { action: 'deny' }
    if (isLocalAppUrl(url, appOrigin)) return { action: 'allow' }
    openExternal(url)
    return { action: 'deny' }
  }
}

module.exports = { SIDECAR_NAME, sidecarFileName, sidecarPath, frontendDistPath, isAllowedExternalUrl, isLocalAppUrl, createExternalWindowHandler }
