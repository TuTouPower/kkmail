// groupColor comes from server-side group data and is attacker-influenceable,
// so it must never reach style.background unchecked (url()/expression()
// injection). Only plain hex colors are trusted; anything else falls back.
const SAFE_HEX_COLOR = /^#[0-9a-f]{3,8}$/i

export function safeCssBackground(color: string | null | undefined, fallback: string): string {
  const value = (color ?? '').trim()
  return SAFE_HEX_COLOR.test(value) ? value : fallback
}
