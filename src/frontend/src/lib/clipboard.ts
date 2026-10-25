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

function fallbackCopy(text: string): boolean {
  if (typeof document === 'undefined') return false
  const ta = document.createElement('textarea')
  ta.value = text
  ta.style.position = 'fixed'
  ta.style.left = '-9999px'
  ta.style.top = '-9999px'
  ta.style.opacity = '0'
  ta.setAttribute('readonly', '')
  ta.setAttribute('aria-hidden', 'true')
  document.body.appendChild(ta)
  ta.focus()
  ta.select()
  let ok = false
  try {
    ok = document.execCommand('copy')
  } catch {
    ok = false
  } finally {
    document.body.removeChild(ta)
  }
  return ok
}
