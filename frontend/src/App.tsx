import { useEffect, useState, useSyncExternalStore } from 'react'
import { useMailStore } from './store/mailStore'
import Sidebar from './components/Sidebar'
import MessageList from './components/MessageList'
import MessageReader from './components/MessageReader'
import LoginPage from './components/LoginPage'
import ComposeModal from './components/ComposeModal'
import { UNAUTHORIZED_EVENT, api } from './api/client'
import { queryClient } from './api/queries'
import './design-system/tokens.css'

function subscribeResize(onChange: () => void) {
  window.addEventListener('resize', onChange)
  return () => window.removeEventListener('resize', onChange)
}

function App() {
  const { theme, mobileView, sidebarCollapsed, mobileSidebarOpen } = useMailStore()
  const [authed, setAuthed] = useState<boolean | null>(null)

  useEffect(() => {
    document.documentElement.dataset.theme = theme
  }, [theme])

  const wide = useSyncExternalStore(subscribeResize, () => window.innerWidth > 760, () => true)

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
      className={['app', mobileSidebarOpen ? 'sidebar-open' : '', sidebarCollapsed && wide ? 'sidebar-collapsed' : ''].filter(Boolean).join(' ')}
      data-mobile-view={mobileView}
    >
      <div className="workspace">
        <Sidebar />
        <MessageList />
        <MessageReader />
      </div>
      <ComposeModal />
    </div>
  )
}

export default App
