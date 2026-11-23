import { useEffect, useId, useRef, useState, type KeyboardEvent } from 'react'
import './select.css'

export interface SelectOption {
  value: string
  label: string
}

interface CommonProps {
  id?: string
  value: string
  options: SelectOption[]
  onChange: (value: string) => void
  ariaLabel?: string
  disabled?: boolean
  placeholder?: string
}

type SelectProps = CommonProps

export function Select({ id, value, options, onChange, ariaLabel, disabled, placeholder }: SelectProps) {
  const [open, setOpen] = useState(false)
  const [activeIndex, setActiveIndex] = useState(0)
  const rootRef = useRef<HTMLDivElement>(null)
  const triggerRef = useRef<HTMLButtonElement>(null)
  const listId = useId()
  const selectedIndex = options.findIndex(option => option.value === value)
  const current = selectedIndex >= 0 ? options[selectedIndex] : undefined

  useEffect(() => {
    if (!open) return
    const onPointerDown = (event: PointerEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false)
    }
    document.addEventListener('pointerdown', onPointerDown)
    return () => document.removeEventListener('pointerdown', onPointerDown)
  }, [open])

  const close = (restoreFocus: boolean) => {
    setOpen(false)
    if (restoreFocus) triggerRef.current?.focus()
  }

  const commit = (index: number) => {
    const option = options[index]
    if (!option) return
    onChange(option.value)
    close(true)
  }

  const show = () => {
    setActiveIndex(selectedIndex >= 0 ? selectedIndex : 0)
    setOpen(true)
  }

  const onKeyDown = (event: KeyboardEvent<HTMLButtonElement>) => {
    if (disabled) return
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      event.preventDefault()
      if (!open) {
        show()
        return
      }
      const delta = event.key === 'ArrowDown' ? 1 : -1
      setActiveIndex(current => (current + delta + options.length) % options.length)
      return
    }
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault()
      if (!open) show()
      else commit(activeIndex)
      return
    }
    if (event.key === 'Escape') {
      if (open) {
        event.preventDefault()
        close(true)
      }
      return
    }
    if (event.key === 'Tab' && open) setOpen(false)
  }

  return <div className="ds-select" ref={rootRef}>
    <button
      ref={triggerRef}
      type="button"
      id={id}
      className="ds-select-trigger"
      data-select-value={value}
      role="combobox"
      aria-haspopup="listbox"
      aria-expanded={open}
      aria-controls={listId}
      aria-label={ariaLabel}
      aria-activedescendant={open ? `${listId}-option-${activeIndex}` : undefined}
      disabled={disabled}
      onClick={() => open ? close(false) : show()}
      onKeyDown={onKeyDown}
    ><span className="ds-select-value">{current?.label ?? placeholder ?? ''}</span></button>
    {open && <div className="ds-select-popover" id={listId} role="listbox" data-select-open="true" data-select-popover-for={id ?? ariaLabel ?? ''}>
      {options.map((option, index) => <div
        key={option.value}
        id={`${listId}-option-${index}`}
        className={`ds-select-option${index === activeIndex ? ' is-active' : ''}`}
        role="option"
        aria-selected={option.value === value}
        data-option-value={option.value}
        onMouseEnter={() => setActiveIndex(index)}
        onClick={() => commit(index)}
      >{option.label}</div>)}
    </div>}
  </div>
}

export function Combobox({ id, value, options, onChange, ariaLabel, disabled, placeholder }: CommonProps) {
  const [open, setOpen] = useState(false)
  const [activeIndex, setActiveIndex] = useState(0)
  const rootRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)
  const listId = useId()
  const matches = options.filter(option => !value || option.value.toLowerCase().includes(value.toLowerCase()) || option.label.toLowerCase().includes(value.toLowerCase()))

  useEffect(() => {
    if (!open) return
    const onPointerDown = (event: PointerEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false)
    }
    document.addEventListener('pointerdown', onPointerDown)
    return () => document.removeEventListener('pointerdown', onPointerDown)
  }, [open])

  const close = (restoreFocus: boolean) => {
    setOpen(false)
    if (restoreFocus) inputRef.current?.focus()
  }

  const commit = (index: number) => {
    const option = matches[index]
    if (!option) return
    onChange(option.value)
    close(true)
  }

  const onKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (disabled) return
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      event.preventDefault()
      if (!open) {
        setActiveIndex(0)
        setOpen(true)
        return
      }
      if (!matches.length) return
      const delta = event.key === 'ArrowDown' ? 1 : -1
      setActiveIndex(current => (current + delta + matches.length) % matches.length)
      return
    }
    if (event.key === 'Enter' && open && matches[activeIndex]) {
      event.preventDefault()
      commit(activeIndex)
      return
    }
    if (event.key === 'Escape' && open) {
      event.preventDefault()
      close(true)
      return
    }
    if (event.key === 'Tab' && open) setOpen(false)
  }

  return <div className="ds-select ds-combobox" ref={rootRef}>
    <input
      ref={inputRef}
      id={id}
      className="ds-select-trigger ds-combobox-input"
      role="combobox"
      aria-autocomplete="list"
      aria-expanded={open}
      aria-controls={listId}
      aria-label={ariaLabel}
      aria-activedescendant={open && matches[activeIndex] ? `${listId}-option-${activeIndex}` : undefined}
      disabled={disabled}
      value={value}
      placeholder={placeholder}
      onChange={event => { onChange(event.target.value); setActiveIndex(0); setOpen(true) }}
      onClick={() => setOpen(true)}
      onKeyDown={onKeyDown}
    />
    {open && matches.length > 0 && <div className="ds-select-popover" id={listId} role="listbox" data-select-open="true" data-select-popover-for={id ?? ariaLabel ?? ''}>
      {matches.map((option, index) => <div
        key={option.value}
        id={`${listId}-option-${index}`}
        className={`ds-select-option${index === activeIndex ? ' is-active' : ''}`}
        role="option"
        aria-selected={option.value === value}
        data-option-value={option.value}
        onMouseEnter={() => setActiveIndex(index)}
        onClick={() => commit(index)}
      ><span>{option.value}</span>{option.label && option.label !== option.value && <small>{option.label}</small>}</div>)}
    </div>}
  </div>
}
