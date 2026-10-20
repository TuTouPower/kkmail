/** Extract a display name from an RFC 5322 From-like header. */
export function displayName(from?: string): string {
  const raw = (from || '').trim()
  if (!raw) return '未知'
  // "Name" <addr> or Name <addr>
  const angled = raw.match(/^\s*"?([^"<]*)"?\s*<[^>]+>\s*$/)
  if (angled) {
    const name = angled[1].trim().replace(/^"|"$/g, '')
    if (name) return name
  }
  // Bare address → local part
  if (raw.includes('@') && !raw.includes(' ')) {
    return raw.split('@')[0] || raw
  }
  // Already a plain name (or leftover angle-less text)
  return raw.replace(/<[^>]*>/g, '').replace(/^"|"$/g, '').trim() || raw
}
