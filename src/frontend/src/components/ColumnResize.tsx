import { useCallback, useEffect, useRef } from 'react'

export default function ColumnResize({
  ariaLabel,
  onDrag,
  onDragEnd,
}: {
  ariaLabel: string
  onDrag: (deltaX: number) => void
  onDragEnd?: () => void
}) {
  const lastX = useRef(0)
  const onDragRef = useRef(onDrag)
  const onDragEndRef = useRef(onDragEnd)

  useEffect(() => {
    onDragRef.current = onDrag
    onDragEndRef.current = onDragEnd
  }, [onDrag, onDragEnd])

  const onPointerDown = useCallback((e: React.PointerEvent<HTMLDivElement>) => {
    e.preventDefault()
    lastX.current = e.clientX
    const target = e.currentTarget
    const pointerId = e.pointerId
    target.setPointerCapture(pointerId)
    const move = (ev: PointerEvent) => {
      const dx = ev.clientX - lastX.current
      lastX.current = ev.clientX
      if (dx) onDragRef.current(dx)
    }
    const end = () => {
      window.removeEventListener('pointermove', move)
      window.removeEventListener('pointerup', end)
      window.removeEventListener('pointercancel', end)
      try {
        if (target.hasPointerCapture(pointerId)) target.releasePointerCapture(pointerId)
      } catch {
        /* capture already lost */
      }
      onDragEndRef.current?.()
    }
    window.addEventListener('pointermove', move)
    window.addEventListener('pointerup', end)
    window.addEventListener('pointercancel', end)
  }, [])

  return (
    <div
      className="column-resize"
      role="separator"
      aria-orientation="vertical"
      aria-label={ariaLabel}
      tabIndex={0}
      onPointerDown={onPointerDown}
      onKeyDown={(e) => {
        if (e.key === 'ArrowLeft') {
          onDrag(-8)
          onDragEnd?.()
        }
        if (e.key === 'ArrowRight') {
          onDrag(8)
          onDragEnd?.()
        }
      }}
    />
  )
}
