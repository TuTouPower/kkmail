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
    const u = new URL(target)
    // Embedded credentials must never count as the trusted local app,
    // even when the host/port match the app origin.
    if (u.username || u.password) return false
    return u.origin === origin
  } catch {
    return false
  }
}

/** appOrigin may be a string or a zero-arg getter resolved at event time. */
function resolveAppOrigin(appOrigin) {
  return typeof appOrigin === 'function' ? appOrigin() : appOrigin
}

function createExternalWindowHandler(openExternal, appOrigin) {
  return ({ url }) => {
    // Local-app check first: the app origin is loopback http, which
    // isAllowedExternalUrl (A331) no longer treats as external.
    if (isLocalAppUrl(url, resolveAppOrigin(appOrigin))) return { action: 'allow' }
    if (!isAllowedExternalUrl(url)) return { action: 'deny' }
    openExternal(url)
    return { action: 'deny' }
  }
}

/** will-navigate / will-redirect guard: local app URLs pass, others are
 *  prevented and only https/mailto are handed to the system browser. */
function createNavigationGuardHandler(openExternal, appOrigin) {
  return (event, target) => {
    if (isLocalAppUrl(target, resolveAppOrigin(appOrigin))) return
    event.preventDefault()
    if (isAllowedExternalUrl(target)) openExternal(target)
  }
}

/**
 * A127: attach the full guard set (window-open handler + navigation guards)
 * to any webContents — main window and window.open popups alike — so an
 * allowed same-origin popup cannot navigate away unguarded.
 */
function attachContentGuards(contents, openExternal, appOrigin) {
  contents.setWindowOpenHandler(createExternalWindowHandler(openExternal, appOrigin))
  const navigationGuard = createNavigationGuardHandler(openExternal, appOrigin)
  contents.on('will-navigate', navigationGuard)
  contents.on('will-redirect', navigationGuard)
  return navigationGuard
}

module.exports = { SIDECAR_NAME, sidecarFileName, sidecarPath, frontendDistPath, isAllowedExternalUrl, isLocalAppUrl, createExternalWindowHandler, createNavigationGuardHandler, attachContentGuards }
