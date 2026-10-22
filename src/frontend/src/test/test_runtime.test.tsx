// @vitest-environment jsdom
import { describe, expect, it, vi } from 'vitest'
import { queryClient } from '../api/queries'
import { useMailStore } from '../store/mailStore'
import { render } from './render'

const initialFetch = fetch
let leakedEvents = 0

describe.sequential('shared browser test isolation', () => {
  it.each([1, 2])('starts case %i with empty storage, cache and mounted roots', async () => {
    expect(localStorage.length).toBe(0)
    expect(sessionStorage.length).toBe(0)
    expect(useMailStore.getState().theme).toBe('dark')
    expect(useMailStore.getState().sidebarWidth).toBe(260)
    expect(queryClient.getQueryCache().getAll()).toHaveLength(0)
    expect(document.querySelector('.runtime-probe')).toBeNull()
    expect(fetch).toBe(initialFetch)
    expect(vi.isFakeTimers()).toBe(false)
    window.dispatchEvent(new Event('test-runtime-listener'))
    expect(leakedEvents).toBe(0)

    localStorage.setItem('leftover', 'value')
    sessionStorage.setItem('leftover', 'value')
    useMailStore.getState().setTheme('light')
    useMailStore.getState().setSidebarWidth(399)
    queryClient.setQueryData(['runtime-probe'], { leftover: true })
    await render(<div className="runtime-probe">Mounted</div>)
    window.addEventListener('test-runtime-listener', () => { leakedEvents += 1 })
    vi.stubGlobal('fetch', vi.fn())
    vi.useFakeTimers()
    setTimeout(() => { leakedEvents += 1 }, 100)
    // Deliberately leave all resources to the shared teardown.
  })
})
