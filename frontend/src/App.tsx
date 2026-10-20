import { useEffect, useState } from 'react'
import { useMailStore } from './store/mailStore'
import Sidebar from './components/Sidebar'
import MessageList from './components/MessageList'
import MessageReader from './components/MessageReader'
import SettingsPage from './components/SettingsModal'
import LoginPage from './components/LoginPage'
import ColumnResize from './components/ColumnResize'
import { UNAUTHORIZED_EVENT, api } from './api/client'
import { queryClient } from './api/queries'
import './design-system/tokens.css'
import { useIsWide } from './lib/viewport'
import { workspaceGridColumns } from './lib/workspaceLayout'
import { useMailCoreRealtime } from './hooks/useMailCoreRealtime'

function resolveTheme(theme: 'dark' | 'light' | 'system'): 'dark' | 'light' {
  if (theme !== 'system') return theme
  return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
}

function App() {
  const {
    theme, mobileView, sidebarCollapsed, mobileSidebarOpen, closeMobileSidebar,
    settingsOpen, sidebarWidth, listWidth, setSidebarWidth, setListWidth,
  } = useMailStore()
  const [authed, setAuthed] = useState<boolean | null>(null)
  useMailCoreRealtime(authed === true)

  useEffect(() => {
    const apply = () => { document.documentElement.dataset.theme = resolveTheme(theme) }
    apply()
    if (theme !== 'system') return
    const mq = window.matchMedia('(prefers-color-scheme: dark)')
    const onChange = () => apply()
    mq.addEventListener('change', onChange)
    return () => mq.removeEventListener('change', onChange)
  }, [theme])

  const wide = useIsWide()
  const drawerOpen = mobileSidebarOpen && !wide

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

  useEffect(() => {
    if (wide && mobileSidebarOpen) closeMobileSidebar()
  }, [wide, mobileSidebarOpen, closeMobileSidebar])

  useEffect(() => {
    let cancelled = false
    api.checkSession()
      .then((ok) => { if (!cancelled) setAuthed(ok) })
      .catch(() => { if (!cancelled) setAuthed(false) })
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

  const gridColumns = workspaceGridColumns({
    wide,
    sidebarCollapsed,
    settingsOpen,
    sidebarWidth,
    listWidth,
  })

  return (
    <div
      className={['app', drawerOpen ? 'sidebar-open' : '', sidebarCollapsed && wide ? 'sidebar-collapsed' : '', settingsOpen ? 'settings-mode' : ''].filter(Boolean).join(' ')}
      data-mobile-view={mobileView}
      style={{
        ['--sidebar-w' as string]: `${sidebarWidth}px`,
        ['--list-w' as string]: `${listWidth}px`,
      }}
    >
      <div
        className="workspace"
        data-testid="mail-workspace"
        style={gridColumns ? { gridTemplateColumns: gridColumns } : undefined}
      >
        <Sidebar />
        {wide && !sidebarCollapsed && (
          <ColumnResize
            ariaLabel="调整侧栏宽度"
            onDrag={(dx) => setSidebarWidth(sidebarWidth + dx)}
          />
        )}
        {settingsOpen ? (
          <SettingsPage />
        ) : (
          <>
            <MessageList />
            {wide && (
              <ColumnResize
                ariaLabel="调整邮件列表宽度"
                onDrag={(dx) => setListWidth(listWidth + dx)}
              />
            )}
            <MessageReader />
          </>
        )}
      </div>
      {/* Outside the grid so it never consumes a track when the drawer opens. */}
      {drawerOpen && (
        <div
          className="drawer-backdrop"
          data-testid="drawer-backdrop"
          aria-hidden="true"
          onClick={(e) => { e.preventDefault(); e.stopPropagation(); closeMobileSidebar() }}
        />
      )}
    </div>
  )
}

export default App
