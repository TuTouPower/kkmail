import { create } from 'zustand'
import { persist } from 'zustand/middleware'

export type ViewState =
  | { type: 'allInbox' }
  | { type: 'accountFolder'; accountId: number; email: string; folder: string }

interface MailUiState {
  theme: 'dark' | 'light'
  setTheme: (theme: 'dark' | 'light') => void
  sidebarCollapsed: boolean
  toggleSidebar: () => void
  mobileView: 'list' | 'detail'
  setMobileView: (view: 'list' | 'detail') => void
  view: ViewState
  setView: (view: ViewState) => void
  selectedKey: string | null
  setSelectedKey: (key: string | null) => void
  search: string
  setSearch: (q: string) => void
  listFilter: 'all' | 'unread' | 'flagged'
  setListFilter: (f: 'all' | 'unread' | 'flagged') => void
  sortNewest: boolean
  toggleSort: () => void
  collapsedGroups: string[]
  toggleGroup: (group: string) => void
  collapsedAccounts: string[]
  toggleAccount: (id: string) => void
  composeOpen: boolean
  composeMode: 'new' | 'reply' | 'forward'
  composeDraft: { to: string; subject: string; body: string; accountId?: number }
  openCompose: (mode?: 'new' | 'reply' | 'forward', draft?: Partial<MailUiState['composeDraft']>) => void
  setComposeOpen: (open: boolean) => void
  selectedIds: string[]
  toggleSelected: (key: string) => void
  clearSelected: () => void
  selectAll: (keys: string[]) => void
  flaggedIds: string[]
  toggleFlag: (key: string) => void
}

export const useMailStore = create<MailUiState>()(
  persist(
    (set) => ({
      theme: 'dark',
      setTheme: (theme) => set({ theme }),
      sidebarCollapsed: false,
      toggleSidebar: () => set((s) => ({ sidebarCollapsed: !s.sidebarCollapsed })),
      mobileView: 'list',
      setMobileView: (view) => set({ mobileView: view }),
      view: { type: 'allInbox' },
      setView: (view) => set({ view, selectedKey: null, mobileView: 'list' }),
      selectedKey: null,
      setSelectedKey: (key) => set({ selectedKey: key }),
      search: '',
      setSearch: (q) => set({ search: q }),
      listFilter: 'all',
      setListFilter: (f) => set({ listFilter: f }),
      sortNewest: true,
      toggleSort: () => set((s) => ({ sortNewest: !s.sortNewest })),
      collapsedGroups: [],
      toggleGroup: (group) =>
        set((s) => ({
          collapsedGroups: s.collapsedGroups.includes(group)
            ? s.collapsedGroups.filter((g) => g !== group)
            : [...s.collapsedGroups, group],
        })),
      collapsedAccounts: [],
      toggleAccount: (id) =>
        set((s) => ({
          collapsedAccounts: s.collapsedAccounts.includes(id)
            ? s.collapsedAccounts.filter((x) => x !== id)
            : [...s.collapsedAccounts, id],
        })),
      composeOpen: false,
      composeMode: 'new',
      composeDraft: { to: '', subject: '', body: '' },
      openCompose: (mode = 'new', draft = {}) =>
        set({
          composeOpen: true,
          composeMode: mode,
          composeDraft: {
            to: draft.to || '',
            subject: draft.subject || '',
            body: draft.body || '',
            accountId: draft.accountId,
          },
        }),
      setComposeOpen: (open) => set({ composeOpen: open }),
      selectedIds: [],
      toggleSelected: (key) =>
        set((s) => ({
          selectedIds: s.selectedIds.includes(key) ? s.selectedIds.filter((id) => id !== key) : [...s.selectedIds, key],
        })),
      clearSelected: () => set({ selectedIds: [] }),
      selectAll: (keys: string[]) => set({ selectedIds: keys }),
      flaggedIds: [],
      toggleFlag: (key) =>
        set((s) => ({
          flaggedIds: s.flaggedIds.includes(key) ? s.flaggedIds.filter((id) => id !== key) : [...s.flaggedIds, key],
        })),
    }),
    { name: 'mail-ui-storage', partialize: (s) => ({ theme: s.theme }) },
  ),
)

export const FOLDERS = [
  { id: 'inbox', label: '收件箱', api: 'inbox' },
  { id: 'junkemail', label: '垃圾邮件', api: 'junkemail' },
  { id: 'deleteditems', label: '废纸篓', api: 'deleteditems' },
  { id: 'all', label: '全部', api: 'all' },
] as const

export function providerBadge(provider?: string, accountType?: string) {
  const p = (provider || accountType || '').toLowerCase()
  if (p.includes('163') || p.includes('netease')) return '163'
  if (p.includes('outlook') || p.includes('hotmail') || p.includes('live')) return 'O'
  if (p.includes('gmail') || p.includes('google')) return 'G'
  if (p.includes('qq')) return 'Q'
  return (p.slice(0, 1) || 'M').toUpperCase()
}

export function providerColor(provider?: string, accountType?: string) {
  const p = (provider || accountType || '').toLowerCase()
  if (p.includes('163') || p.includes('netease')) return '#d94b47'
  if (p.includes('outlook') || p.includes('hotmail')) return '#0879d9'
  if (p.includes('gmail') || p.includes('google')) return '#4285f4'
  if (p.includes('qq')) return '#12b7f5'
  return '#6d8fd1'
}
