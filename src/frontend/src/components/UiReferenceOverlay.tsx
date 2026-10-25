import { memo, useCallback, useEffect, useRef, useState } from 'react'
import { copyTextToClipboard } from '../lib/clipboard'
import { formatUiReferenceText, isUiReferenceShortcut } from '../lib/uiReference'

interface ElementBadge {
  id: string
  key: string
  top: number
  left: number
}

function sameBadgePositions(current: ElementBadge[], next: ElementBadge[]): boolean {
  return current.length === next.length && current.every((badge, index) => {
    const candidate = next[index]
    return badge.id === candidate.id && badge.key === candidate.key && badge.top === candidate.top && badge.left === candidate.left
  })
}

export const UiReferenceOverlay = memo(function UiReferenceOverlay() {
  const [active, setActive] = useState(false)
  const [badges, setBadges] = useState<ElementBadge[]>([])
  const [toast, setToast] = useState<{ text: string; error?: boolean } | null>(null)
  const overlayRef = useRef<HTMLDivElement>(null)
  const badgesRef = useRef<ElementBadge[]>([])

  const scanElements = useCallback(() => {
    if (!active) return
    const elements = document.querySelectorAll<HTMLElement>('[data-ui]')
    const nextBadges: ElementBadge[] = []
    let counter = 0

    elements.forEach((el) => {
      const id = el.getAttribute('data-ui')
      if (!id) return
      // Check visibility
      const rect = el.getBoundingClientRect()
      if (rect.width <= 0 || rect.height <= 0) return
      const style = window.getComputedStyle(el)
      if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') return

      // Ensure position is within or close to viewport
      if (rect.bottom < 0 || rect.top > window.innerHeight || rect.right < 0 || rect.left > window.innerWidth) {
        return
      }

      nextBadges.push({
        id,
        key: `${id}-${counter++}`,
        top: Math.max(0, rect.top + 2),
        left: Math.max(0, rect.left + 2),
      })
    })

    if (!sameBadgePositions(badgesRef.current, nextBadges)) {
      badgesRef.current = nextBadges
      setBadges(nextBadges)
    }
  }, [active])

  // Keydown listener for shortcut and Escape
  useEffect(() => {
    function handleKeyDown(e: KeyboardEvent) {
      if (isUiReferenceShortcut(e)) {
        e.preventDefault()
        e.stopPropagation()
        setActive((prev) => !prev)
        return
      }
      if (active && e.key === 'Escape') {
        e.preventDefault()
        e.stopPropagation()
        setActive(false)
      }
    }

    window.addEventListener('keydown', handleKeyDown, true)
    return () => window.removeEventListener('keydown', handleKeyDown, true)
  }, [active])

  // Re-scan when active and on scroll/resize/mutation
  useEffect(() => {
    if (!active) {
      // oxlint-disable react/set-state-in-effect -- clear transient overlay state when the shortcut closes the overlay.
      badgesRef.current = []
      setBadges([])
      setToast(null)
      // oxlint-enable react/set-state-in-effect
      return
    }

    scanElements()

    let scheduledFrame: number | null = null
    const scheduleScan = () => {
      if (scheduledFrame !== null) return
      scheduledFrame = window.requestAnimationFrame(() => {
        scheduledFrame = null
        scanElements()
      })
    }
    const onScrollOrResize = () => {
      scheduleScan()
    }

    window.addEventListener('scroll', onScrollOrResize, true)
    window.addEventListener('resize', onScrollOrResize)

    const observer = new MutationObserver((mutations) => {
      const overlay = overlayRef.current
      if (overlay && mutations.every((mutation) => overlay.contains(mutation.target))) return
      scheduleScan()
    })
    observer.observe(document.body, { childList: true, subtree: true, attributes: true })

    return () => {
      window.removeEventListener('scroll', onScrollOrResize, true)
      window.removeEventListener('resize', onScrollOrResize)
      observer.disconnect()
      if (scheduledFrame !== null) window.cancelAnimationFrame(scheduledFrame)
    }
  }, [active, scanElements])

  // Auto-clear toast
  useEffect(() => {
    if (!toast) return
    const timer = setTimeout(() => {
      setToast(null)
    }, 2500)
    return () => clearTimeout(timer)
  }, [toast])

  const handleCopy = async (id: string, e: React.MouseEvent) => {
    e.preventDefault()
    e.stopPropagation()
    const text = formatUiReferenceText(id)
    try {
      await copyTextToClipboard(text)
      setToast({ text: `已复制引用：${text}` })
    } catch {
      setToast({ text: `复制失败：剪贴板不可用或未获授权`, error: true })
    }
  }

  if (!active) return null

  return (
    <div
      ref={overlayRef}
      className="ui-reference-overlay"
      style={{
        position: 'fixed',
        inset: 0,
        pointerEvents: 'none',
        zIndex: 99999,
      }}
      aria-live="polite"
    >
      {/* Badges */}
      {badges.map((b) => (
        <button
          key={b.key}
          type="button"
          className="ui-ref-badge"
          style={{
            position: 'fixed',
            top: `${b.top}px`,
            left: `${b.left}px`,
            pointerEvents: 'auto',
            background: 'var(--blue, #2563eb)',
            color: '#fff',
            border: '1px solid rgba(255, 255, 255, 0.4)',
            borderRadius: '4px',
            fontSize: '11px',
            fontWeight: 700,
            fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace',
            lineHeight: 1,
            padding: '2px 4px',
            cursor: 'pointer',
            boxShadow: '0 2px 4px rgba(0, 0, 0, 0.35)',
            transform: 'none',
            zIndex: 100000,
          }}
          title={`点击复制引用：${formatUiReferenceText(b.id)}`}
          aria-label={`UI 编号 ${b.id}`}
          onClick={(e) => handleCopy(b.id, e)}
        >
          {b.id}
        </button>
      ))}

      {/* Toast Feedback */}
      {toast && (
        <div
          role={toast.error ? 'alert' : 'status'}
          style={{
            position: 'fixed',
            bottom: '24px',
            left: '50%',
            transform: 'translateX(-50%)',
            background: toast.error ? 'var(--red, #ef4444)' : 'var(--surface-2, #1e293b)',
            color: '#fff',
            padding: '8px 16px',
            borderRadius: '8px',
            fontSize: '13px',
            fontWeight: 500,
            boxShadow: '0 4px 12px rgba(0, 0, 0, 0.4)',
            zIndex: 100001,
            pointerEvents: 'auto',
          }}
        >
          {toast.text}
        </div>
      )}
    </div>
  )
})

export default UiReferenceOverlay
