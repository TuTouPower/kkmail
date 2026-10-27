import { lazy, Suspense, useCallback, useEffect, useRef, useState } from 'react'
import { PanelLeft } from 'lucide-react'
import { useMailStore } from './store/mailStore'
import MessageList from './components/MessageList'
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
import { getDesktopPlatform } from './lib/desktopShell'

const Sidebar = lazy(() => import('./components/Sidebar'))
const MessageReader = lazy(() => import('./components/MessageReader'))
const SettingsPage = lazy(() => import('./components/SettingsModal'))
const UiReferenceOverlay = lazy(() => import('./components/UiReferenceOverlay'))

function App() {
  const theme = useMailStore((s) => s.theme)
  const mobileView = useMailStore((s) => s.mobileView)
  const sidebarCollapsed = useMailStore((s) => s.sidebarCollapsed)
  const mobileSidebarOpen = useMailStore((s) => s.mobileSidebarOpen)
  const closeMobileSidebar = useMailStore((s) => s.closeMobileSidebar)
  const settingsOpen = useMailStore((s) => s.settingsOpen)
  const view = useMailStore((s) => s.view)
  const selectedKey = useMailStore((s) => s.selectedKey)
  const listFilter = useMailStore((s) => s.listFilter)
  const toggleSidebar = useMailStore((s) => s.toggleSidebar)
  const toggleMobileSidebar = useMailStore((s) => s.toggleMobileSidebar)
  const sidebarWidth = useMailStore((s) => s.sidebarWidth)
  const listWidth = useMailStore((s) => s.listWidth)
  const setSidebarWidth = useMailStore((s) => s.setSidebarWidth)
  const setListWidth = useMailStore((s) => s.setListWidth)
  const uiReferenceEnabled = useMailStore((s) => s.uiReferenceEnabled ?? true)
  const [authed, setAuthed] = useState<boolean | null>(null)
  const [sessionCheckFailed, setSessionCheckFailed] = useState(false)
  const [sessionCheckAttempt, setSessionCheckAttempt] = useState(0)
  const [oauthReturnPending, setOAuthReturnPending] = useState(false)
  const consumeOAuthReturn = useCallback(() => setOAuthReturnPending(false), [])
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
  const isMacDesktop = getDesktopPlatform() === 'darwin'
  const macLoginDragRegion = isMacDesktop
    ? <div className="mac-login-drag-region" data-testid="mac-login-drag-region" aria-hidden="true" />
    : null
  const sidebarToggleRef = useRef<HTMLButtonElement | null>(null)
  const drawerWasOpen = useRef(false)

  useEffect(() => {
    if (drawerWasOpen.current && !drawerOpen) {
      requestAnimationFrame(() => {
        const toggle = sidebarToggleRef.current
        if (toggle?.isConnected && toggle.getClientRects().length) toggle.focus()
      })
    }
    drawerWasOpen.current = drawerOpen
  }, [drawerOpen])

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

  function consumeOAuthReturnIfPresent(): boolean {
    if (typeof window === 'undefined' || window.location.hash !== '#oauth-return') return false
    useMailStore.getState().openSettings()
    window.history.replaceState(null, '', `${window.location.pathname}${window.location.search}`)
    return true
  }

  useEffect(() => {
    let cancelled = false
    api.checkSession()
      .then((ok) => {
        if (!cancelled) {
          setSessionCheckFailed(false)
          setAuthed(ok)
          if (ok && consumeOAuthReturnIfPresent()) {
            setOAuthReturnPending(true)
          }
        }
      })
      .catch(() => { if (!cancelled) setSessionCheckFailed(true) })
    const onUnauthorized = () => {
      setSessionCheckFailed(false)
      setAuthed(false)
    }
    window.addEventListener(UNAUTHORIZED_EVENT, onUnauthorized)
    return () => {
      cancelled = true
      window.removeEventListener(UNAUTHORIZED_EVENT, onUnauthorized)
    }
  }, [sessionCheckAttempt])

  if (authed === null) {
    return <>
      {macLoginDragRegion}
      <div style={{ minHeight: '100dvh', display: 'grid', placeItems: 'center', gap: 16, color: 'var(--muted)' }}>
        {sessionCheckFailed ? <>
          <div role="alert">无法连接 mail-core，暂时无法检查登录状态。</div>
          <button
            type="button"
            data-testid="retry-session-check"
            onClick={() => {
              setSessionCheckFailed(false)
              setSessionCheckAttempt((attempt) => attempt + 1)
            }}
            style={{
              height: 36,
              padding: '0 16px',
              border: 0,
              borderRadius: 8,
              background: 'var(--primary)',
              color: 'var(--on-primary)',
              cursor: 'pointer',
            }}
          >重试</button>
        </> : <div>正在检查登录状态…</div>}
      </div>
    </>
  }
  if (!authed) {
    return (
      <>
        {macLoginDragRegion}
        <LoginPage onSuccess={() => {
          setAuthed(true)
          if (consumeOAuthReturnIfPresent()) {
            setOAuthReturnPending(true)
          }
          void queryClient.invalidateQueries()
        }} />
        {uiReferenceEnabled && <Suspense fallback={null}><UiReferenceOverlay /></Suspense>}
      </>
    )
  }

  const gridColumns = workspaceGridColumns({
    wide,
    sidebarCollapsed,
    settingsOpen,
    sidebarWidth,
    listWidth,
  })
  const viewResetKey = JSON.stringify(view)
  // Search keystrokes must not reset the list boundary (A361): resetting on
  // every character would silently retry a crashed list while typing.
  const listResetKey = JSON.stringify([view, listFilter, selectedKey])
  const readerResetKey = JSON.stringify([view, selectedKey])

  return (
    <div
      ref={appRef}
      className={['app', isMacDesktop ? 'mac-desktop-shell' : '', drawerOpen ? 'sidebar-open' : '', sidebarCollapsed && wide ? 'sidebar-collapsed' : ''].filter(Boolean).join(' ')}
      data-mobile-view={mobileView}
      style={{
        ['--sidebar-w' as string]: `${sidebarWidth}px`,
        ['--list-w' as string]: `${listWidth}px`,
      }}
    >
      {isMacDesktop && (
        <div className="mac-titlebar-controls" data-testid="mac-titlebar-controls">
          <div className="mac-titlebar-drag-region" aria-hidden="true" />
          <button
            ref={sidebarToggleRef}
            data-ui="ML01"
            data-testid="sidebar-toggle"
            className="mac-titlebar-sidebar-toggle"
            type="button"
            title={wide ? (sidebarCollapsed ? '展开侧栏' : '收起侧栏') : (mobileSidebarOpen ? '关闭导航' : '打开导航')}
            aria-label={wide ? (sidebarCollapsed ? '展开侧栏' : '收起侧栏') : (mobileSidebarOpen ? '关闭导航' : '打开导航')}
            aria-expanded={wide ? !sidebarCollapsed : mobileSidebarOpen}
            onClick={wide ? toggleSidebar : toggleMobileSidebar}
          >
            <PanelLeft size={16} />
          </button>
        </div>
      )}
      <div
        ref={workspaceRef}
        className="workspace"
        data-testid="mail-workspace"
        style={gridColumns ? { gridTemplateColumns: gridColumns } : undefined}
      >
        {(!wide || !sidebarCollapsed) && (
          <ErrorBoundary inline fallbackTitle="侧栏加载失败" resetKey={viewResetKey}>
            <Suspense fallback={null}><Sidebar /></Suspense>
          </ErrorBoundary>
        )}
        {wide && !sidebarCollapsed && (
          <ColumnResize
            ariaLabel="调整侧栏宽度"
            value={sidebarWidth}
            min={180}
            max={420}
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
            <Suspense fallback={<div role="status">正在加载设置…</div>}><SettingsPage sidebarToggleRef={sidebarToggleRef} oauthReturn={oauthReturnPending} onOAuthReturnConsumed={consumeOAuthReturn} /></Suspense>
          </ErrorBoundary>
        ) : (
          <>
            <ErrorBoundary inline fallbackTitle="邮件列表加载失败" resetKey={listResetKey}>
              <MessageList sidebarToggleRef={sidebarToggleRef} />
            </ErrorBoundary>
            {wide && (
              <ColumnResize
                ariaLabel="调整邮件列表宽度"
                value={listWidth}
                min={260}
                max={560}
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
            <ErrorBoundary inline fallbackTitle="邮件详情加载失败" resetKey={readerResetKey}>
              <Suspense fallback={null}><MessageReader /></Suspense>
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
      {uiReferenceEnabled && <Suspense fallback={null}><UiReferenceOverlay /></Suspense>}
    </div>
  )
}

export default App
