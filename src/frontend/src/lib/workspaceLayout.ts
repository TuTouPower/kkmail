/** Width of each column-resize grid track (must match .column-resize CSS). */
export const RESIZE_TRACK_PX = 5

export type WorkspaceLayoutInput = {
  wide: boolean
  sidebarCollapsed: boolean
  settingsOpen: boolean
  sidebarWidth: number
  listWidth: number
}

/**
 * CSS grid-template-columns for the mail shell.
 * ColumnResize nodes are real grid children, so every handle needs its own track;
 * otherwise panes wrap onto new rows (collapsed/stacked layout).
 */
export function workspaceGridColumns(input: WorkspaceLayoutInput): string | undefined {
  const { wide, sidebarCollapsed, settingsOpen, sidebarWidth, listWidth } = input
  if (!wide) return undefined

  const resize = `${RESIZE_TRACK_PX}px`
  if (sidebarCollapsed) {
    if (settingsOpen) return `minmax(0, 1fr)`
    return `${listWidth}px ${resize} minmax(0, 1fr)`
  }
  if (settingsOpen) return `${sidebarWidth}px ${resize} minmax(0, 1fr)`
  return `${sidebarWidth}px ${resize} ${listWidth}px ${resize} minmax(0, 1fr)`
}

/** How many non-overlay children the workspace grid should place. */
export function workspaceGridChildRoles(input: Omit<WorkspaceLayoutInput, 'sidebarWidth' | 'listWidth'>): string[] {
  const { wide, sidebarCollapsed, settingsOpen } = input
  const roles: string[] = []
  if (!wide) {
    roles.push('sidebar')
  } else if (!sidebarCollapsed) {
    roles.push('sidebar', 'resize-sidebar')
  }
  if (settingsOpen) {
    roles.push('settings')
    return roles
  }
  roles.push('list')
  if (wide) roles.push('resize-list')
  roles.push('reader')
  return roles
}
