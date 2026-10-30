import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import type { AccountIconMode } from './accountIcon'
import type { Shortcut } from '../lib/ui_shortcut'

export type FavoriteCategory = 'inbox' | 'unread' | 'sent' | 'drafts' | 'trash' | 'junk'

export type ViewState =
  | { type: 'allInbox' }
  | { type: 'favorite'; category: FavoriteCategory; accountId?: string; email?: string }
  | { type: 'group'; groupId: string; groupName: string; category: FavoriteCategory }
  | { type: 'account'; accountId: string; email: string }
  | { type: 'folder'; accountId: string; email: string; folderId: string; folderName: string; folderRole?: string }

interface MailUiState {
  theme: 'dark' | 'light' | 'system'
  setTheme: (theme: 'dark' | 'light' | 'system') => void
  mailBodyDarkMode: 'smart' | 'original'
  setMailBodyDarkMode: (mode: 'smart' | 'original') => void
  accountIconMode: AccountIconMode
  setAccountIconMode: (mode: AccountIconMode) => void
  sidebarCollapsed: boolean
  toggleSidebar: () => void
  mobileSidebarOpen: boolean
  toggleMobileSidebar: () => void
  closeMobileSidebar: () => void
  settingsOpen: boolean
  openSettings: () => void
  closeSettings: () => void
  sidebarWidth: number
  listWidth: number
  setSidebarWidth: (w: number) => void
  setListWidth: (w: number) => void
  mobileView: 'list' | 'detail'
  setMobileView: (view: 'list' | 'detail') => void
  view: ViewState
  /** Switch view; also resets selection and closes the mobile drawer. */
  setView: (view: ViewState) => void
  /** 所有收件箱 / 未读邮件 / 已标记 entries in the sidebar. */
  openSmartView: (filter: 'all' | 'unread' | 'flagged') => void
  selectedKey: string | null
  setSelectedKey: (key: string | null) => void
  search: string
  setSearch: (q: string) => void
  listFilter: 'all' | 'unread' | 'flagged'
  setListFilter: (f: 'all' | 'unread' | 'flagged') => void
  sortNewest: boolean
  toggleSort: () => void
  sidebarSections: { allAccounts: boolean; accountList: boolean }
  toggleSidebarSection: (section: 'allAccounts' | 'accountList') => void
  expandedSidebarGroups: string[]
  toggleSidebarGroup: (groupId: string) => void
  expandedSidebarCategories: string[]
  toggleSidebarCategory: (key: string) => void
  expandedSidebarAccounts: string[]
  toggleSidebarAccount: (accountId: string) => void
  selectedIds: string[]
  toggleSelected: (key: string) => void
  clearSelected: () => void
  selectAll: (keys: string[]) => void
  uiReferenceEnabled: boolean
  setUiReferenceEnabled: (enabled: boolean) => void
  uiReferenceShortcut: Shortcut | null
  setUiReferenceShortcut: (shortcut: Shortcut | null) => void
}

// State every view switch must reset, shared by setView/openSmartView so the
// two cannot drift: selection is dropped, the reader returns to the list, and the mobile drawer closes.
const navigationReset = () => ({
  selectedKey: null,
  selectedIds: [] as string[],
  mobileView: 'list' as const,
  mobileSidebarOpen: false,
  settingsOpen: false,
  search: '',
  listFilter: 'all' as const,
})

export const useMailStore = create<MailUiState>()(
  persist(
    (set) => ({
      // Default must stay 'system': public/theme_bootstrap.js paints the
      // first frame with the same default before React mounts (A94). If the
      // two drift apart, the UI flashes from one theme to the other.
      theme: 'system',
      setTheme: (theme) => set({ theme }),
      mailBodyDarkMode: 'smart',
      setMailBodyDarkMode: (mode) => set({ mailBodyDarkMode: mode }),
      accountIconMode: 'brand',
      setAccountIconMode: (mode) => set({ accountIconMode: mode }),
      sidebarCollapsed: false,
      toggleSidebar: () => set((s) => ({ sidebarCollapsed: !s.sidebarCollapsed })),
      mobileSidebarOpen: false,
      toggleMobileSidebar: () => set((s) => ({ mobileSidebarOpen: !s.mobileSidebarOpen })),
      closeMobileSidebar: () => set({ mobileSidebarOpen: false }),
      settingsOpen: false,
      openSettings: () => set({ settingsOpen: true, mobileSidebarOpen: false, mobileView: 'list' }),
      closeSettings: () => set({ settingsOpen: false }),
      sidebarWidth: 260,
      listWidth: 360,
      setSidebarWidth: (w) => set({ sidebarWidth: Math.min(420, Math.max(180, Math.round(w))) }),
      setListWidth: (w) => set({ listWidth: Math.min(560, Math.max(260, Math.round(w))) }),
      mobileView: 'list',
      setMobileView: (view) => set({ mobileView: view }),
      view: { type: 'allInbox' },
      setView: (view) => set({ view, ...navigationReset() }),
      openSmartView: (filter) => set({ ...navigationReset(), view: { type: 'allInbox' }, listFilter: filter }),
      selectedKey: null,
      setSelectedKey: (key) => set({ selectedKey: key }),
      search: '',
      setSearch: (q) => set({ search: q }),
      listFilter: 'all',
      setListFilter: (f) => set({ listFilter: f }),
      sortNewest: true,
      toggleSort: () => set((s) => ({ sortNewest: !s.sortNewest })),
      sidebarSections: { allAccounts: true, accountList: true },
      toggleSidebarSection: (section) => set((s) => ({
        sidebarSections: { ...s.sidebarSections, [section]: !s.sidebarSections[section] },
      })),
      expandedSidebarGroups: [],
      toggleSidebarGroup: (groupId) => set((s) => ({
        expandedSidebarGroups: s.expandedSidebarGroups.includes(groupId)
          ? s.expandedSidebarGroups.filter((id) => id !== groupId)
          : [...s.expandedSidebarGroups, groupId],
      })),
      expandedSidebarCategories: [],
      toggleSidebarCategory: (key) => set((s) => ({
        expandedSidebarCategories: s.expandedSidebarCategories.includes(key)
          ? s.expandedSidebarCategories.filter((item) => item !== key)
          : [...s.expandedSidebarCategories, key],
      })),
      expandedSidebarAccounts: [],
      toggleSidebarAccount: (accountId) => set((s) => ({
        expandedSidebarAccounts: s.expandedSidebarAccounts.includes(accountId)
          ? s.expandedSidebarAccounts.filter((id) => id !== accountId)
          : [...s.expandedSidebarAccounts, accountId],
      })),
      selectedIds: [],
      toggleSelected: (key) =>
        set((s) => ({
          selectedIds: s.selectedIds.includes(key) ? s.selectedIds.filter((id) => id !== key) : [...s.selectedIds, key],
        })),
      clearSelected: () => set({ selectedIds: [] }),
      selectAll: (keys: string[]) => set({ selectedIds: keys }),
      uiReferenceEnabled: true,
      setUiReferenceEnabled: (enabled) => set({ uiReferenceEnabled: enabled }),
      uiReferenceShortcut: null,
      setUiReferenceShortcut: (shortcut) => set({ uiReferenceShortcut: shortcut }),
    }),
    { name: 'mail-ui-storage', partialize: (s) => ({
      theme: s.theme,
      mailBodyDarkMode: s.mailBodyDarkMode,
      sidebarWidth: s.sidebarWidth,
      listWidth: s.listWidth,
      accountIconMode: s.accountIconMode,
      sidebarSections: s.sidebarSections,
      expandedSidebarGroups: s.expandedSidebarGroups,
      expandedSidebarCategories: s.expandedSidebarCategories,
      expandedSidebarAccounts: s.expandedSidebarAccounts,
      uiReferenceEnabled: s.uiReferenceEnabled,
      uiReferenceShortcut: s.uiReferenceShortcut,
    }) },
  ),
)

export function providerColor(provider?: string, accountType?: string) {
  const p = (provider || accountType || '').toLowerCase()
  if (p.includes('163') || p.includes('netease')) return '#d94b47'
  if (p.includes('outlook') || p.includes('hotmail')) return '#0879d9'
  if (p.includes('google')) return '#4285f4'
  if (p.includes('qq')) return '#12b7f5'
  return '#6d8fd1'
}
