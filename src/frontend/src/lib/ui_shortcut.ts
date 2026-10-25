export interface Shortcut {
  code: string
  ctrl: boolean
  meta: boolean
  shift: boolean
  alt: boolean
}

export function isMac(): boolean {
  if (typeof navigator === 'undefined') return false
  return /mac/i.test(navigator.userAgent || '') || /mac/i.test(navigator.platform || '')
}

export function getDefaultShortcut(): Shortcut {
  const mac = isMac()
  return {
    code: 'Period',
    ctrl: !mac,
    meta: mac,
    shift: true,
    alt: false,
  }
}

export function formatShortcut(shortcut: Shortcut): string {
  const parts: string[] = []
  if (shortcut.ctrl) parts.push('Ctrl')
  if (shortcut.alt) parts.push('Alt')
  if (shortcut.shift) parts.push('Shift')
  if (shortcut.meta) parts.push(isMac() ? '⌘' : 'Meta')

  const codeDisplay: Record<string, string> = {
    Period: '.',
    Comma: ',',
    Slash: '/',
    Backslash: '\\',
    BracketLeft: '[',
    BracketRight: ']',
    Semicolon: ';',
    Quote: "'",
    Backquote: '`',
    Minus: '-',
    Equal: '=',
  }
  const display = codeDisplay[shortcut.code] || shortcut.code.replace(/^Key|^Digit/, '')
  parts.push(display)
  return parts.join(' + ')
}

export function matchesShortcut(event: KeyboardEvent, shortcut: Shortcut): boolean {
  if (event.repeat) return false
  const hasCmdOrCtrl = event.ctrlKey || event.metaKey
  const shortcutCmdOrCtrl = shortcut.ctrl || shortcut.meta

  if (Boolean(hasCmdOrCtrl) !== Boolean(shortcutCmdOrCtrl)) return false
  if (Boolean(event.shiftKey) !== Boolean(shortcut.shift)) return false
  if (Boolean(event.altKey) !== Boolean(shortcut.alt)) return false

  return event.code === shortcut.code || (shortcut.code === 'Period' && (event.key === '.' || event.key === '>'))
}
