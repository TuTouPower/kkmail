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
import './App.css'

function App() {
  const { theme, mobileView, sidebarCollapsed, mobileSidebarOpen } = useMailStore()
  const [appEl, setAppEl] = useState<HTMLDivElement | null>(null)
  const [authed, setAuthed] = useState<boolean | null>(null)

  useEffect(() => {
    document.documentElement.dataset.theme = theme
  }, [theme])

  useEffect(() => {
    if (appEl) {
      appEl.dataset.mobileView = mobileView
      appEl.classList.toggle('sidebar-collapsed', sidebarCollapsed && window.innerWidth > 760)
    }
  }, [mobileView, sidebarCollapsed, appEl])

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
    <div className={`app ${mobileSidebarOpen ? 'sidebar-open' : ''}`} ref={setAppEl} data-mobile-view="list">
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
