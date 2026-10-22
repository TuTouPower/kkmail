import { afterEach, beforeEach, vi } from 'vitest'

// Install actual jsdom Storage before importing the persisted store. Node's
// optional host storage must never select a file shared across test workers.
const browserWindow = (globalThis as unknown as { jsdom: { window: Window } }).jsdom.window
Object.defineProperty(globalThis, 'localStorage', { configurable: true, value: browserWindow.localStorage })
Object.defineProperty(globalThis, 'sessionStorage', { configurable: true, value: browserWindow.sessionStorage })

const { useMailStore } = await import('../store/mailStore')
const { queryClient } = await import('../api/queries')
const { cleanup } = await import('./render')
const { __resetCsrfForTests } = await import('../api/client')
const visibility = Object.getOwnPropertyDescriptor(document, 'visibilityState')
const clipboard = Object.getOwnPropertyDescriptor(navigator, 'clipboard')
const nativeRemove = window.removeEventListener.bind(window)
let listeners: Array<[string, EventListenerOrEventListenerObject, boolean | AddEventListenerOptions | undefined]> = []

beforeEach(() => {
  useMailStore.setState(useMailStore.getInitialState(), true)
  localStorage.clear()
  sessionStorage.clear()
  queryClient.clear()
  __resetCsrfForTests()
  const nativeAdd = window.addEventListener.bind(window)
  vi.spyOn(window, 'addEventListener').mockImplementation((type, listener, options) => {
    listeners.push([type, listener, options])
    nativeAdd(type, listener, options)
  })
})

afterEach(() => {
  cleanup()
  for (const [type, listener, options] of listeners) nativeRemove(type, listener, options)
  listeners = []
  if (vi.isFakeTimers()) vi.clearAllTimers()
  vi.useRealTimers()
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
  vi.unstubAllEnvs()
  if (visibility) Object.defineProperty(document, 'visibilityState', visibility)
  else Reflect.deleteProperty(document, 'visibilityState')
  if (clipboard) Object.defineProperty(navigator, 'clipboard', clipboard)
  else Reflect.deleteProperty(navigator, 'clipboard')
  useMailStore.setState(useMailStore.getInitialState(), true)
  localStorage.clear()
  sessionStorage.clear()
  __resetCsrfForTests()
})
