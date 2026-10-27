// @vitest-environment jsdom
import { act } from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import App from './App'
import { api } from './api/client'
import { cleanup, render, waitFor } from './test/render'
import { useMailStore } from './store/mailStore'

const listState = vi.hoisted(() => ({ shouldThrow: true, attempts: 0 }))

vi.mock('./components/MessageList', () => ({
  default: () => {
    listState.attempts += 1
    if (listState.shouldThrow) throw new Error('list boom')
    return <div>list-ok</div>
  },
}))
vi.mock('./components/Sidebar', () => ({ default: () => <div>sidebar</div> }))
vi.mock('./components/MessageReader', () => ({ default: () => <div>reader</div> }))
vi.mock('./components/SettingsModal', () => ({ default: () => <div>settings</div> }))
vi.mock('./components/UiReferenceOverlay', () => ({ default: () => null }))
vi.mock('./hooks/useMailCoreRealtime', () => ({ useMailCoreRealtime: () => {} }))

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
})

describe('App list ErrorBoundary resetKey (A361)', () => {
  it('does not reset the list boundary when only search changes, but does when selectedKey changes', async () => {
    vi.spyOn(console, 'error').mockImplementation(() => {})
    vi.spyOn(api, 'checkSession').mockResolvedValue(true)
    useMailStore.setState({ settingsOpen: false, search: '', selectedKey: null, listFilter: 'all' })
    listState.shouldThrow = true
    listState.attempts = 0

    const { container } = await render(<App />)
    await waitFor(() => expect(container.textContent).toContain('邮件列表加载失败'))
    const attemptsAfterCrash = listState.attempts
    expect(attemptsAfterCrash).toBeGreaterThan(0)

    // Typing in search must not reset the boundary: the fallback stays up
    // and the crashed list is not retried on every keystroke.
    await act(async () => { useMailStore.getState().setSearch('hello') })
    expect(container.textContent).toContain('邮件列表加载失败')
    expect(container.textContent).not.toContain('list-ok')
    expect(listState.attempts).toBe(attemptsAfterCrash)

    // A real navigation dimension still resets it and the list recovers.
    listState.shouldThrow = false
    await act(async () => { useMailStore.getState().setSelectedKey('msg-1') })
    await waitFor(() => expect(container.textContent).toContain('list-ok'))
  })
})
