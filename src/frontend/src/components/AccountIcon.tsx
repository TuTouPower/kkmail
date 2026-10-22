import { memo } from 'react'
import { Mail } from 'lucide-react'
import { detectAccountBrand, getEmailInitial, BRAND_TITLES, type AccountIconMode } from '../store/accountIcon'
import { providerColor, useMailStore } from '../store/mailStore'
import { BRAND_ICON_COMPONENTS } from './brand-icons/brandIconMap'

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
          style={{ background: groupColor || providerColor(provider, accountType) }}
          aria-hidden="true"
        >
          {initial}
        </span>
      )
    }
    return (
      <span
        className={`${baseCls} account-generic`}
        style={{ background: groupColor || 'var(--muted)' }}
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
