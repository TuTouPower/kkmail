import { memo } from 'react'
import { Mail } from 'lucide-react'
import { detectAccountBrand, getEmailInitial, type AccountIconMode } from '../store/accountIcon'
import { providerColor, useMailStore } from '../store/mailStore'

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

  // Brand mode
  const brand = detectAccountBrand(email, provider)
  switch (brand) {
    case 'gmail':
      return (
        <span
          className={`${baseCls} account-brand-gmail`}
          style={{ background: groupColor || '#ea4335' }}
          aria-hidden="true"
          title="Gmail"
        >
          G
        </span>
      )
    case 'outlook':
      return (
        <span
          className={`${baseCls} account-brand-outlook`}
          style={{ background: groupColor || '#0078d4' }}
          aria-hidden="true"
          title="Outlook"
        >
          O
        </span>
      )
    case '163':
      return (
        <span
          className={`${baseCls} account-brand-163`}
          style={{ background: groupColor || '#d94b47', fontSize: '9px' }}
          aria-hidden="true"
          title="网易邮箱"
        >
          163
        </span>
      )
    case 'qq':
      return (
        <span
          className={`${baseCls} account-brand-qq`}
          style={{ background: groupColor || '#12b7f5', fontSize: '9px' }}
          aria-hidden="true"
          title="QQ邮箱"
        >
          QQ
        </span>
      )
    case 'generic':
    default:
      return (
        <span
          className={`${baseCls} account-brand-generic`}
          style={{ background: groupColor || 'var(--muted)' }}
          aria-hidden="true"
        >
          <Mail size={11} />
        </span>
      )
  }
})

export default AccountIcon
