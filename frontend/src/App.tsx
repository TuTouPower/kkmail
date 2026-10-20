import { useEffect, useState } from 'react'
import { useMailStore } from './store/mailStore'
import Sidebar from './components/Sidebar'
import MessageList from './components/MessageList'
import MessageReader from './components/MessageReader'
import LoginPage from './components/LoginPage'
import { api } from './api/client'
import './design-system/tokens.css'
import './App.css'

function App() {
  const { theme, mobileView, sidebarCollapsed } = useMailStore()
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
    api.getCsrf()
      .then((token) => setAuthed(!!token || token === null))
      .catch(() => setAuthed(false))
  }, [])

  if (authed === null) {
    return <div style={{ minHeight: '100dvh', display: 'grid', placeItems: 'center', color: 'var(--muted)' }}>正在检查登录状态…</div>
  }
  if (!authed) {
    return <LoginPage onSuccess={() => setAuthed(true)} />
  }

  return (
    <div className="app" ref={setAppEl} data-mobile-view="list">
      <div className="workspace">
        <Sidebar />
        <MessageList />
        <MessageReader />
      </div>
    </div>
  )
}

export default App
