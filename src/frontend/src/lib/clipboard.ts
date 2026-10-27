/**
 * Safely copy text to system clipboard.
 * Uses the modern asynchronous Clipboard API when available (secure contexts: HTTPS / localhost).
 * Falls back to document.execCommand('copy') in non-secure contexts (e.g. self-hosted Web via HTTP)
 * or when the async Clipboard API is unavailable.
 */
export async function copyTextToClipboard(text: string): Promise<void> {
  if (typeof navigator !== 'undefined' && typeof navigator.clipboard?.writeText === 'function') {
    try {
      await navigator.clipboard.writeText(text)
      return
    } catch (err) {
      if (!fallbackCopy(text)) {
        throw err
      }
      return
    }
  }

  if (!fallbackCopy(text)) {
    throw new Error('当前环境不支持剪贴板写入')
  }
}

// document.execCommand is deprecated, but it is the only copy path in
// non-secure (http) contexts where the async Clipboard API is unavailable,
// so it stays strictly as this fallback.
function fallbackCopy(text: string): boolean {
  if (typeof document === 'undefined') return false

  const activeDialog = document.querySelector('dialog[open], [role="dialog"][aria-modal="true"], .settings-dialog')
  const container = activeDialog ?? document.body
  const prevActiveElement = document.activeElement as HTMLElement | null

  const ta = document.createElement('textarea')
  ta.value = text
  ta.style.position = 'fixed'
  ta.style.left = '-9999px'
  ta.style.top = '-9999px'
  ta.style.opacity = '0'
  ta.setAttribute('readonly', '')
  ta.setAttribute('aria-hidden', 'true')
  container.appendChild(ta)
  ta.focus()
  ta.select()
  let ok = false
  try {
    ok = document.execCommand('copy')
  } catch {
    ok = false
  } finally {
    // Cleanup must never throw: the textarea may already be detached, and a
    // throw here would mask the copy result.
    try {
      container.removeChild(ta)
    } catch {
      try {
        ta.remove()
      } catch {
        /* ignore */
      }
    }
    if (prevActiveElement && typeof prevActiveElement.focus === 'function') {
      try {
        prevActiveElement.focus()
      } catch {
        /* ignore */
      }
    }
  }
  return ok
}
