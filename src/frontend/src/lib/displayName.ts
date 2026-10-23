/** Extract a display name from an RFC 5322 From-like header. */
export function displayName(from?: string): string {
  const raw = (from || '').trim()
  if (!raw) return ''
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

/** Extract the email address from an RFC 5322 From-like header. */
export function displayEmail(from?: string): string {
  const raw = (from || '').trim()
  if (!raw) return ''
  const angled = raw.match(/<([^>]+)>/)
  if (angled) {
    return angled[1].trim()
  }
  return raw
}
