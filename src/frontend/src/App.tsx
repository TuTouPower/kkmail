import { useEffect, useRef, useState } from 'react'
import { useMailStore } from './store/mailStore'
import Sidebar from './components/Sidebar'
import MessageList from './components/MessageList'
import MessageReader from './components/MessageReader'
import SettingsPage from './components/SettingsModal'
import LoginPage from './components/LoginPage'
import ColumnResize from './components/ColumnResize'
import ErrorBoundary from './components/ErrorBoundary'
import { UNAUTHORIZED_EVENT, api } from './api/client'
import { queryClient } from './api/queries'
import './design-system/tokens.css'
import { useIsWide } from './lib/viewport'
import { workspaceGridColumns } from './lib/workspaceLayout'
import { useMailCoreRealtime } from './hooks/useMailCoreRealtime'
import { resolveTheme } from './lib/theme'

function App() {
  const theme = useMailStore((s) => s.theme)
  const mobileView = useMailStore((s) => s.mobileView)
  const sidebarCollapsed = useMailStore((s) => s.sidebarCollapsed)
  const mobileSidebarOpen = useMailStore((s) => s.mobileSidebarOpen)
  const closeMobileSidebar = useMailStore((s) => s.closeMobileSidebar)
  const settingsOpen = useMailStore((s) => s.settingsOpen)
  const sidebarWidth = useMailStore((s) => s.sidebarWidth)
  const listWidth = useMailStore((s) => s.listWidth)
  const setSidebarWidth = useMailStore((s) => s.setSidebarWidth)
  const setListWidth = useMailStore((s) => s.setListWidth)
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

  const appRef = useRef<HTMLDivElement>(null)
  const workspaceRef = useRef<HTMLDivElement>(null)
  const dragSidebarRef = useRef(sidebarWidth)
  const dragListRef = useRef(listWidth)

  useEffect(() => {
    dragSidebarRef.current = sidebarWidth
  }, [sidebarWidth])

  useEffect(() => {
    dragListRef.current = listWidth
  }, [listWidth])

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
      ref={appRef}
      className={['app', drawerOpen ? 'sidebar-open' : '', sidebarCollapsed && wide ? 'sidebar-collapsed' : ''].filter(Boolean).join(' ')}
      data-mobile-view={mobileView}
      style={{
        ['--sidebar-w' as string]: `${sidebarWidth}px`,
        ['--list-w' as string]: `${listWidth}px`,
      }}
    >
      <div
        ref={workspaceRef}
        className="workspace"
        data-testid="mail-workspace"
        style={gridColumns ? { gridTemplateColumns: gridColumns } : undefined}
      >
        {(!wide || !sidebarCollapsed) && (
          <ErrorBoundary inline fallbackTitle="侧栏加载失败">
            <Sidebar />
          </ErrorBoundary>
        )}
        {wide && !sidebarCollapsed && (
          <ColumnResize
            ariaLabel="调整侧栏宽度"
            onDrag={(dx) => {
              const next = Math.min(420, Math.max(180, Math.round(dragSidebarRef.current + dx)))
              dragSidebarRef.current = next
              if (appRef.current) {
                appRef.current.style.setProperty('--sidebar-w', `${next}px`)
              }
              if (workspaceRef.current) {
                workspaceRef.current.style.gridTemplateColumns = workspaceGridColumns({
                  wide,
                  sidebarCollapsed,
                  settingsOpen,
                  sidebarWidth: next,
                  listWidth: dragListRef.current,
                }) ?? ''
              }
            }}
            onDragEnd={() => {
              setSidebarWidth(dragSidebarRef.current)
            }}
          />
        )}
        {settingsOpen ? (
          <ErrorBoundary inline fallbackTitle="设置加载失败">
            <SettingsPage />
          </ErrorBoundary>
        ) : (
          <>
            <ErrorBoundary inline fallbackTitle="邮件列表加载失败">
              <MessageList />
            </ErrorBoundary>
            {wide && (
              <ColumnResize
                ariaLabel="调整邮件列表宽度"
                onDrag={(dx) => {
                  const next = Math.min(560, Math.max(260, Math.round(dragListRef.current + dx)))
                  dragListRef.current = next
                  if (appRef.current) {
                    appRef.current.style.setProperty('--list-w', `${next}px`)
                  }
                  if (workspaceRef.current) {
                    workspaceRef.current.style.gridTemplateColumns = workspaceGridColumns({
                      wide,
                      sidebarCollapsed,
                      settingsOpen,
                      sidebarWidth: dragSidebarRef.current,
                      listWidth: next,
                    }) ?? ''
                  }
                }}
                onDragEnd={() => {
                  setListWidth(dragListRef.current)
                }}
              />
            )}
            <ErrorBoundary inline fallbackTitle="邮件详情加载失败">
              <MessageReader />
            </ErrorBoundary>
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
