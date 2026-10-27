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
    // A331: only https/mailto may leave the app. Loopback http is never an
    // external URL (any local port could be a phishing/probing target);
    // same-origin app http is handled in-app via isLocalAppUrl, not here.
    return u.protocol === 'https:' || u.protocol === 'mailto:'
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
    // Local-app check first: the app origin is loopback http, which
    // isAllowedExternalUrl (A331) no longer treats as external.
    if (isLocalAppUrl(url, appOrigin)) return { action: 'allow' }
    if (!isAllowedExternalUrl(url)) return { action: 'deny' }
    openExternal(url)
    return { action: 'deny' }
  }
}

module.exports = { SIDECAR_NAME, sidecarFileName, sidecarPath, frontendDistPath, isAllowedExternalUrl, isLocalAppUrl, createExternalWindowHandler }
