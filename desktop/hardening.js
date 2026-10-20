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
  denyPermissionRequest,
  denyPermissionCheck,
}
