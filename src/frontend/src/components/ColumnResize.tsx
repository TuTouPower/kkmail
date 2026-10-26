import { useCallback, useEffect, useRef } from 'react'

export default function ColumnResize({
  ariaLabel,
  value,
  min,
  max,
  onDrag,
  onDragEnd,
}: {
  ariaLabel: string
  value: number
  min: number
  max: number
  onDrag: (deltaX: number) => void
  onDragEnd?: () => void
}) {
  const lastX = useRef(0)
  const onDragRef = useRef(onDrag)
  const onDragEndRef = useRef(onDragEnd)
  const activeDragEndRef = useRef<(() => void) | null>(null)

  useEffect(() => {
    onDragRef.current = onDrag
    onDragEndRef.current = onDragEnd
  }, [onDrag, onDragEnd])

  // F3: a drag's window listeners only removed themselves on
  // pointerup/pointercancel; unmounting mid-drag leaked them (and the
  // dead component kept receiving moves). End any active drag on
  // unmount through the same cleanup path.
  useEffect(() => () => {
    activeDragEndRef.current?.()
    activeDragEndRef.current = null
  }, [])

  const onPointerDown = useCallback((e: React.PointerEvent<HTMLDivElement>) => {
    e.preventDefault()
    activeDragEndRef.current?.()
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
      if (activeDragEndRef.current === end) activeDragEndRef.current = null
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
    activeDragEndRef.current = end
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
      aria-valuemin={min}
      aria-valuemax={max}
      aria-valuenow={value}
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
