import { describe, expect, it } from 'vitest'
import { RESIZE_TRACK_PX, workspaceGridColumns } from './workspaceLayout'

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

  it('lays out five tracks for the default mail shell', () => {
    const input = { wide: true, sidebarCollapsed: false, settingsOpen: false }
    const cols = workspaceGridColumns({ ...input, sidebarWidth: 260, listWidth: 360 })!
    expect(trackCount(cols)).toBe(5)
  })

  it('keeps settings on one row with sidebar + one handle', () => {
    const input = { wide: true, sidebarCollapsed: false, settingsOpen: true }
    expect(workspaceGridColumns({ ...input, sidebarWidth: 260, listWidth: 360 })).toBe('260px 5px minmax(0, 1fr)')
  })

  it('does not invent desktop columns on mobile', () => {
    expect(workspaceGridColumns({
      wide: false, sidebarCollapsed: false, settingsOpen: false, sidebarWidth: 260, listWidth: 360,
    })).toBeUndefined()
  })

  it('completely hides sidebar on desktop when collapsed (t009 AC-001, AC-003, AC-005)', () => {
    const input = { wide: true, sidebarCollapsed: true, settingsOpen: false }
    const cols = workspaceGridColumns({ ...input, sidebarWidth: 260, listWidth: 360 })!
    expect(cols).toBe('360px 5px minmax(0, 1fr)')
    expect(trackCount(cols)).toBe(3)

    const settingsInput = { wide: true, sidebarCollapsed: true, settingsOpen: true }
    const settingsCols = workspaceGridColumns({ ...settingsInput, sidebarWidth: 260, listWidth: 360 })!
    expect(settingsCols).toBe('minmax(0, 1fr)')
    expect(trackCount(settingsCols)).toBe(1)
  })
})
