/**
 * Pure helpers for Electron session hardening (testable without Electron).
 * Applied from main.js: deny webviews, deny all permission prompts, inject a
 * restrictive CSP on every response for the app session.
 */
'use strict'

/** CSP for the SPA shell (loopback mail-core). Mail HTML uses its own srcdoc CSP. */
function appContentSecurityPolicy() {
  return [
    "default-src 'self'",
    "script-src 'self'",
    "style-src 'self' 'unsafe-inline'",
    "img-src 'self' data: blob:",
    "font-src 'self' data:",
    "connect-src 'self'",
    "object-src 'none'",
    "base-uri 'self'",
    "form-action 'self'",
    "frame-src 'self'",
    "frame-ancestors 'none'",
  ].join('; ')
}

/** Replace any existing CSP header (any casing) with ours. */
function mergeCspHeaders(responseHeaders, csp = appContentSecurityPolicy()) {
  const headers = { ...(responseHeaders || {}) }
  for (const key of Object.keys(headers)) {
    if (key.toLowerCase() === 'content-security-policy') delete headers[key]
  }
  headers['Content-Security-Policy'] = [csp]
  return headers
}

/**
 * Check whether a requested permission should be granted.
 *
 * Minimal boundary rules (t025 AC-003):
 * - Only 'clipboard-sanitized-write' may be allowed.
 * - Only the top-level main frame (isMainFrame === true) may write.
 * - Only origins matching the trusted loopback appOrigin may write.
 * - All other permissions ('clipboard-read', 'media', 'geolocation', etc.) are unconditionally denied.
 * - Any iframe (e.g. mail reader iframe), untrusted origin, or invalid URL is unconditionally denied.
 */
function isAllowedPermission(permission, requestingUrl, isMainFrame, trustedOrigin) {
  if (permission !== 'clipboard-sanitized-write') return false
  if (!isMainFrame) return false
  if (!trustedOrigin) return false
  try {
    const url = new URL(requestingUrl)
    return url.origin === trustedOrigin
  } catch {
    return false
  }
}

/**
 * Factory for Electron ses.setPermissionRequestHandler.
 */
function createPermissionRequestHandler(getTrustedOrigin) {
  return function permissionRequestHandler(webContents, permission, callback, details) {
    const trustedOrigin = typeof getTrustedOrigin === 'function' ? getTrustedOrigin() : getTrustedOrigin
    const requestingUrl = details?.requestingUrl || (webContents && typeof webContents.getURL === 'function' ? webContents.getURL() : '')
    const isMainFrame = Boolean(details?.isMainFrame)
    if (isAllowedPermission(permission, requestingUrl, isMainFrame, trustedOrigin)) {
      callback(true)
    } else {
      callback(false)
    }
  }
}

/**
 * Factory for Electron ses.setPermissionCheckHandler.
 */
function createPermissionCheckHandler(getTrustedOrigin) {
  return function permissionCheckHandler(webContents, permission, requestingOrigin, details) {
    const trustedOrigin = typeof getTrustedOrigin === 'function' ? getTrustedOrigin() : getTrustedOrigin
    const requestingUrl = requestingOrigin || details?.requestingUrl || (webContents && typeof webContents.getURL === 'function' ? webContents.getURL() : '')
    const isMainFrame = details ? Boolean(details.isMainFrame) : true
    return isAllowedPermission(permission, requestingUrl, isMainFrame, trustedOrigin)
  }
}

/** Electron setPermissionRequestHandler: always deny. */
function denyPermissionRequest(_webContents, _permission, callback) {
  callback(false)
}

/** Electron setPermissionCheckHandler: always deny. */
function denyPermissionCheck() {
  return false
}

module.exports = {
  appContentSecurityPolicy,
  mergeCspHeaders,
  isAllowedPermission,
  createPermissionRequestHandler,
  createPermissionCheckHandler,
  denyPermissionRequest,
  denyPermissionCheck,
}
