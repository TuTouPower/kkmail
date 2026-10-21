import { describe, expect, it } from 'vitest'
import { RESIZE_TRACK_PX, workspaceGridChildRoles, workspaceGridColumns } from './workspaceLayout'

/** Count CSS grid tracks without splitting inside minmax(...). */
function trackCount(cols: string): number {
  return cols.replace(/minmax\([^)]*\)/g, 'TRACK').split(/\s+/).filter(Boolean).length
}

describe('workspaceGridColumns', () => {
  it('reserves a track for each resize handle so panes stay in one row', () => {
    const cols = workspaceGridColumns({
      wide: true,
      sidebarCollapsed: false,
      settingsOpen: false,
      sidebarWidth: 260,
      listWidth: 360,
    })!
    expect(trackCount(cols)).toBe(5)
    expect(cols).toContain(`${RESIZE_TRACK_PX}px`)
    expect(cols.startsWith('260px')).toBe(true)
    expect(cols).toContain('360px')
  })

  it('matches child roles to column count for the default mail shell', () => {
    const input = { wide: true, sidebarCollapsed: false, settingsOpen: false }
    const roles = workspaceGridChildRoles(input)
    const cols = workspaceGridColumns({ ...input, sidebarWidth: 260, listWidth: 360 })!
    expect(roles).toEqual(['sidebar', 'resize-sidebar', 'list', 'resize-list', 'reader'])
    expect(trackCount(cols)).toBe(roles.length)
  })

  it('keeps settings on one row with sidebar + one handle', () => {
    const input = { wide: true, sidebarCollapsed: false, settingsOpen: true }
    expect(workspaceGridChildRoles(input)).toEqual(['sidebar', 'resize-sidebar', 'settings'])
    expect(workspaceGridColumns({ ...input, sidebarWidth: 260, listWidth: 360 })).toBe('260px 5px minmax(0, 1fr)')
  })

  it('does not invent desktop columns on mobile', () => {
    expect(workspaceGridColumns({
      wide: false, sidebarCollapsed: false, settingsOpen: false, sidebarWidth: 260, listWidth: 360,
    })).toBeUndefined()
  })
})
