/** Pure helpers shared by main.js and its tests. */
const path = require('path')

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

function isAllowedExternalUrl(target) {
  try {
    const u = new URL(target)
    // Reject embedded credentials (https://user:pass@host/…) — phishing / leak risk.
    if (u.username || u.password) return false
    const { protocol } = u
    return protocol === 'https:' || protocol === 'http:' || protocol === 'mailto:'
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

function createExternalWindowHandler(openExternal) {
  return ({ url }) => {
    if (isAllowedExternalUrl(url)) openExternal(url)
    return { action: 'deny' }
  }
}

module.exports = { SIDECAR_NAME, sidecarFileName, sidecarPath, frontendDistPath, isAllowedExternalUrl, isLocalAppUrl, createExternalWindowHandler }
