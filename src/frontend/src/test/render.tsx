import { act, type ReactNode } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { QueryClientProvider } from '@tanstack/react-query'
import { queryClient } from '../api/queries'

// React 19: opt in to act() warnings-free rendering in tests.
;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true

export interface Rendered {
  container: HTMLElement
  unmount: () => void
}

let mounted: Array<{ root: Root; el: HTMLElement }> = []

export async function render(ui: ReactNode): Promise<Rendered> {
  const el = document.createElement('div')
  document.body.appendChild(el)
  const root = createRoot(el)
  await act(async () => {
    root.render(<QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>)
  })
  mounted.push({ root, el })
  return { container: el, unmount: () => act(() => root.unmount()) }
}

export function cleanup() {
  for (const { root, el } of mounted) {
    act(() => root.unmount())
    el.remove()
  }
  mounted = []
  queryClient.clear()
}

/** Flush pending promises/react-query updates until `check` passes (or time out). */
export async function waitFor(check: () => void, timeoutMs = 1000): Promise<void> {
  const start = Date.now()
  for (;;) {
    try {
      check()
      return
    } catch (err) {
      if (Date.now() - start > timeoutMs) throw err
      await act(async () => { await new Promise((r) => setTimeout(r, 10)) })
    }
  }
}

export async function click(el: Element | null) {
  if (!el) throw new Error('element not found')
  await act(async () => { (el as HTMLElement).click() })
}

export async function typeInto(el: HTMLInputElement | null, value: string) {
  if (!el) throw new Error('input not found')
  await act(async () => {
    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!
    setter.call(el, value)
    el.dispatchEvent(new Event('input', { bubbles: true }))
  })
}
