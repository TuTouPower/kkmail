import { useEffect, useState } from 'react'
import { useMailStore } from './store/mailStore'
import Sidebar from './components/Sidebar'
import MessageList from './components/MessageList'
import MessageReader from './components/MessageReader'
import './design-system/tokens.css'
import './App.css'

function App() {
  const { theme, mobileView, sidebarCollapsed } = useMailStore()
  const [appEl, setAppEl] = useState<HTMLDivElement | null>(null)

  useEffect(() => {
    document.documentElement.dataset.theme = theme
  }, [theme])

  useEffect(() => {
    if (appEl) {
      appEl.dataset.mobileView = mobileView
      appEl.classList.toggle('sidebar-collapsed', sidebarCollapsed && window.innerWidth > 760)
    }
  }, [mobileView, sidebarCollapsed, appEl])

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
