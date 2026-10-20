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
    const { protocol } = new URL(target)
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

module.exports = { SIDECAR_NAME, sidecarFileName, sidecarPath, frontendDistPath, isAllowedExternalUrl, isLocalAppUrl }
