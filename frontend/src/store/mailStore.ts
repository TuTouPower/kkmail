import { create } from 'zustand'
import { persist } from 'zustand/middleware'

export interface Account {
  id: string
  email: string
  provider: string
  group: string
  color: string
}

export interface Message {
  id: number
  accountId: string
  folder: string
  sender: string
  initial: string
  color: string
  subject: string
  preview: string
  date: string
  time: string
  unread: boolean
  flagged: boolean
  attachments: number
  body: string
  attachmentName?: string
  attachmentSize?: string
}

interface MailState {
  theme: 'dark' | 'light'
  setTheme: (theme: 'dark' | 'light') => void
  sidebarCollapsed: boolean
  toggleSidebar: () => void
  mobileView: 'list' | 'detail'
  setMobileView: (view: 'list' | 'detail') => void
  selectedId: number | null
  setSelectedId: (id: number | null) => void
  search: string
  setSearch: (q: string) => void
  listFilter: 'all' | 'unread' | 'flagged'
  setListFilter: (f: 'all' | 'unread' | 'flagged') => void
  sortNewest: boolean
  toggleSort: () => void
  view: { type: string; accountId?: string; folder?: string }
  setView: (view: MailState['view']) => void
  collapsedGroups: Set<string>
  toggleGroup: (group: string) => void
  collapsedAccounts: Set<string>
  toggleAccount: (id: string) => void
  accounts: Account[]
  messages: Message[]
  markAllVisibleRead: () => void
}

// Demo data matching the HTML prototype
const demoAccounts: Account[] = [
  { id: 'gmail-main', email: 'demo1@example.com', provider: 'Gmail', group: '个人邮箱', color: '#4285f4' },
  { id: 'gmail-zhang', email: 'demo2@example.com', provider: 'Gmail', group: '个人邮箱', color: '#4285f4' },
  { id: 'outlook-work', email: 'work@example.com', provider: 'Outlook', group: '工作邮箱', color: '#0879d9' },
  { id: '163-main', email: 'redacted_mobile@example.com', provider: '网易 163', group: '其他邮箱', color: '#d94b47' },
]

const demoMessages: Message[] = [
  { id: 1, accountId: 'gmail-main', folder: 'inbox', sender: 'Spotify', initial: 'S', color: '#7196d1', subject: 'Take the party with you. Get 2 free months of Premium.', preview: "Your soundtrack's coming with you, wherever you go. Enjoy two months on us.", date: '2026/10/20', time: '16:44', unread: true, flagged: false, attachments: 0, body: '<p>Enjoy 2 free months of Premium.</p>' },
  { id: 2, accountId: 'gmail-main', folder: 'inbox', sender: 'Discord', initial: 'D', color: '#5865f2', subject: 'maedahbatool 在 Community 中提到了你', preview: '您有 3 条新消息 · announcements 查看最新讨论', date: '2026/10/20', time: '09:22', unread: true, flagged: false, attachments: 0, body: '<p>你好！maedahbatool 提到了你。</p>' },
  { id: 3, accountId: 'outlook-work', folder: 'inbox', sender: 'Microsoft 365', initial: 'M', color: '#0879d9', subject: 'Your weekly productivity summary', preview: 'Here is what happened across your Microsoft 365 workspace.', date: '2026/10/20', time: '14:06', unread: true, flagged: false, attachments: 0, body: '<p>Weekly summary ready.</p>' },
  { id: 4, accountId: '163-main', folder: 'inbox', sender: '网易邮箱团队', initial: '网', color: '#d94b47', subject: '网易邮箱安全中心提醒', preview: '您的邮箱安全设置有一项待确认，请及时查看。', date: '2026/10/20', time: '10:27', unread: true, flagged: false, attachments: 0, body: '<p>请检查安全设置。</p>' },
]

export const useMailStore = create<MailState>()(
  persist(
    (set, get) => ({
      theme: 'dark',
      setTheme: (theme) => set({ theme }),
      sidebarCollapsed: false,
      toggleSidebar: () => set((s) => ({ sidebarCollapsed: !s.sidebarCollapsed })),
      mobileView: 'list',
      setMobileView: (view) => set({ mobileView: view }),
      selectedId: 1,
      setSelectedId: (id) => set({ selectedId: id }),
      search: '',
      setSearch: (q) => set({ search: q }),
      listFilter: 'all',
      setListFilter: (f) => set({ listFilter: f }),
      sortNewest: true,
      toggleSort: () => set((s) => ({ sortNewest: !s.sortNewest })),
      view: { type: 'allInbox' },
      setView: (view) => set({ view, selectedId: null }),
      collapsedGroups: new Set(),
      toggleGroup: (group) =>
        set((s) => {
          const next = new Set(s.collapsedGroups)
          next.has(group) ? next.delete(group) : next.add(group)
          return { collapsedGroups: next }
        }),
      collapsedAccounts: new Set(['gmail-zhang']),
      toggleAccount: (id) =>
        set((s) => {
          const next = new Set(s.collapsedAccounts)
          next.has(id) ? next.delete(id) : next.add(id)
          return { collapsedAccounts: next }
        }),
      accounts: demoAccounts,
      messages: demoMessages,
      markAllVisibleRead: () => {
        const { messages } = get()
        // Simplified: mark all currently "visible" as read
        set({
          messages: messages.map((m) => ({ ...m, unread: false })),
        })
      },
    }),
    { name: 'mail-demo-storage', partialize: (s) => ({ theme: s.theme }) }
  )
)
