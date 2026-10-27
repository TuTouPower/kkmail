import { memo } from 'react'
import { Mail } from 'lucide-react'
import { detectAccountBrand, getEmailInitial, BRAND_TITLES, type AccountIconMode } from '../store/accountIcon'
import { providerColor, useMailStore } from '../store/mailStore'
import { BRAND_ICON_COMPONENTS } from './brand-icons/brandIconMap'

// groupColor comes from server-side group data and is attacker-influenceable,
// so it must never reach style.background unchecked (url()/expression()
// injection). Only plain hex colors are trusted; anything else falls back.
const SAFE_HEX_COLOR = /^#[0-9a-f]{3,8}$/i

export function safeCssBackground(color: string | null | undefined, fallback: string): string {
  const value = (color ?? '').trim()
  return SAFE_HEX_COLOR.test(value) ? value : fallback
}

export interface AccountIconProps {
  email?: string
  provider?: string
  accountType?: string
  groupColor?: string | null
  className?: string
  mode?: AccountIconMode
}

export const AccountIcon = memo(function AccountIcon({
  email,
  provider,
  accountType,
  groupColor,
  className = '',
  mode: propMode,
}: AccountIconProps) {
  const storeMode = useMailStore((s) => s.accountIconMode)
  const mode = propMode ?? storeMode

  if (mode === 'none') {
    return null
  }

  const baseCls = ['account-dot', className].filter(Boolean).join(' ')

  if (mode === 'initials') {
    const initial = getEmailInitial(email)
    if (initial) {
      return (
        <span
          className={`${baseCls} account-initials`}
          style={{ background: groupColor ? safeCssBackground(groupColor, 'var(--muted)') : providerColor(provider, accountType) }}
          aria-hidden="true"
        >
          {initial}
        </span>
      )
    }
    return (
      <span
        className={`${baseCls} account-generic`}
        style={{ background: safeCssBackground(groupColor, 'var(--muted)') }}
        aria-hidden="true"
      >
        <Mail size={11} />
      </span>
    )
  }

  // Brand mode: use dedicated SVG brand icon or fallback to default-mail icon
  const brand = detectAccountBrand(email, provider, accountType)
  const IconComponent = BRAND_ICON_COMPONENTS[brand] ?? BRAND_ICON_COMPONENTS['default-mail']
  const title = BRAND_TITLES[brand] ?? BRAND_TITLES['default-mail']

  return (
    <span
      className={`${baseCls} account-brand-${brand}`}
      style={{ background: 'transparent', padding: 0, overflow: 'hidden' }}
      aria-hidden="true"
      title={title}
    >
      <IconComponent />
    </span>
  )
})

export default AccountIcon
