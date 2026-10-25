import { useEffect, useRef, useState, type MouseEvent, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { Copy } from 'lucide-react'
import { copyTextToClipboard } from '../lib/clipboard'

interface CopyAddressProps {
  address: string
  children?: ReactNode
  className?: string
  variant?: 'text' | 'icon'
}

interface CopyFeedback {
  message: string
  failed: boolean
  left: number
  top: number
}

function isCopyableEmail(address: string): boolean {
  const value = address.trim()
  const at = value.indexOf('@')
  return at > 0
    && at === value.lastIndexOf('@')
    && at < value.length - 1
    && !/[\s<>;,]/.test(value)
}

export default function CopyAddress({ address, children, className = '', variant = 'text' }: CopyAddressProps) {
  const [feedback, setFeedback] = useState<CopyFeedback | null>(null)
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const mountedRef = useRef(true)
  const normalizedAddress = address.trim()

  useEffect(() => {
    mountedRef.current = true
    return () => {
      mountedRef.current = false
      if (timerRef.current !== null) clearTimeout(timerRef.current)
    }
  }, [])

  async function copyAddress(event: MouseEvent<HTMLButtonElement>) {
    event.preventDefault()
    event.stopPropagation()
    const bounds = event.currentTarget.getBoundingClientRect()
    try {
      await copyTextToClipboard(normalizedAddress)
      if (!mountedRef.current) return
      showFeedback('已复制地址', 2000, false, bounds)
    } catch (error) {
      if (!mountedRef.current) return
      const reason = error instanceof Error ? error.message.trim() : String(error).trim()
      showFeedback(`复制失败：${reason || '剪贴板写入失败'}。请手动选择并复制地址`, 5000, true, bounds)
    }
  }

  function showFeedback(message: string, delayMs: number, failed: boolean, bounds: DOMRect) {
    if (timerRef.current !== null) clearTimeout(timerRef.current)
    const tooltipHeight = 48
    const top = bounds.bottom + tooltipHeight + 8 <= window.innerHeight
      ? bounds.bottom + 4
      : Math.max(8, bounds.top - tooltipHeight - 4)
    const left = Math.max(8, Math.min(bounds.left, window.innerWidth - 288))
    setFeedback({ message, failed, left, top })
    timerRef.current = setTimeout(() => {
      timerRef.current = null
      setFeedback(null)
    }, delayMs)
  }

  if (!isCopyableEmail(normalizedAddress)) return <>{children ?? address}</>

  return (
    <span className={`copy-address-control${variant === 'icon' ? ' is-icon' : ''}`} data-no-drag="true">
      <button
        type="button"
        className={`${variant === 'icon' ? 'copy-address-button' : 'copy-address-text'}${className ? ` ${className}` : ''}`}
        aria-label={`复制邮箱地址 ${normalizedAddress}`}
        title={feedback?.message || '复制邮箱地址'}
        onClick={(event) => void copyAddress(event)}
      >
        {variant === 'icon' ? <Copy size={14} aria-hidden="true" /> : children ?? normalizedAddress}
      </button>
      {feedback && typeof document !== 'undefined' && createPortal(
        <span
          className="copy-address-feedback"
          data-failed={feedback.failed}
          style={{ left: feedback.left, top: feedback.top }}
          role="status"
          aria-live="polite"
        >
          {feedback.message}
        </span>,
        document.body,
      )}
    </span>
  )
}
