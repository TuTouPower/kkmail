import { useEffect, useState } from 'react'
import { useMailStore } from './store/mailStore'
import Sidebar from './components/Sidebar'
import MessageList from './components/MessageList'
import MessageReader from './components/MessageReader'
import LoginPage from './components/LoginPage'
import ComposeModal from './components/ComposeModal'
import { UNAUTHORIZED_EVENT, api } from './api/client'
import { queryClient } from './api/queries'
import './design-system/tokens.css'
import { useIsWide } from './lib/viewport'

function App() {
  const { theme, mobileView, sidebarCollapsed, mobileSidebarOpen, closeMobileSidebar } = useMailStore()
  const [authed, setAuthed] = useState<boolean | null>(null)

  useEffect(() => {
    document.documentElement.dataset.theme = theme
  }, [theme])

  const wide = useIsWide()
  const drawerOpen = mobileSidebarOpen && !wide

  // Mobile drawer: Escape closes it and the page behind must not scroll.
  useEffect(() => {
    if (!drawerOpen) return
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') closeMobileSidebar() }
    window.addEventListener('keydown', onKey)
    const prevOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => {
      window.removeEventListener('keydown', onKey)
      document.body.style.overflow = prevOverflow
    }
  }, [drawerOpen, closeMobileSidebar])

  // Leaving the mobile layout must not leave a stale open drawer behind.
  useEffect(() => {
    if (wide && mobileSidebarOpen) closeMobileSidebar()
  }, [wide, mobileSidebarOpen, closeMobileSidebar])

  useEffect(() => {
    let cancelled = false
    api.checkSession()
      .then((ok) => { if (!cancelled) setAuthed(ok) })
      // Network/server error: keep the shell usable; individual queries show errors.
      .catch(() => { if (!cancelled) setAuthed(true) })
    const onUnauthorized = () => setAuthed(false)
    window.addEventListener(UNAUTHORIZED_EVENT, onUnauthorized)
    return () => {
      cancelled = true
      window.removeEventListener(UNAUTHORIZED_EVENT, onUnauthorized)
    }
  }, [])

  if (authed === null) {
    return <div style={{ minHeight: '100dvh', display: 'grid', placeItems: 'center', color: 'var(--muted)' }}>正在检查登录状态…</div>
  }
  if (!authed) {
    return <LoginPage onSuccess={() => { setAuthed(true); void queryClient.invalidateQueries() }} />
  }

  return (
    <div
      className={['app', drawerOpen ? 'sidebar-open' : '', sidebarCollapsed && wide ? 'sidebar-collapsed' : ''].filter(Boolean).join(' ')}
      data-mobile-view={mobileView}
    >
      <div className="workspace">
        <Sidebar />
        {drawerOpen && (
          <div
            className="drawer-backdrop"
            data-testid="drawer-backdrop"
            aria-hidden="true"
            // Close on click (not pointerdown): the backdrop must still be under
            // the pointer when the click fires, or the tap lands on the list.
            onClick={(e) => { e.preventDefault(); e.stopPropagation(); closeMobileSidebar() }}
          />
        )}
        <MessageList />
        <MessageReader />
      </div>
      <ComposeModal />
    </div>
  )
}

export default App
