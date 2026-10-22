export type AccountIconMode = 'none' | 'brand' | 'initials'

export type BrandType = 'gmail' | 'outlook' | '163' | 'qq' | 'generic'

export function getEmailDomain(email?: string): string {
  if (!email || !email.includes('@')) return ''
  const parts = email.split('@')
  return (parts[parts.length - 1] || '').trim().toLowerCase()
}

export function detectAccountBrand(email?: string, provider?: string): BrandType {
  const domain = getEmailDomain(email)
  const prov = (provider || '').toLowerCase()

  // Exact domain matching
  if (domain === 'gmail.com' || domain === 'googlemail.com') {
    return 'gmail'
  }
  if (domain === 'outlook.com' || domain === 'hotmail.com' || domain === 'live.com' || domain === 'msn.com') {
    return 'outlook'
  }
  if (domain === '163.com' || domain === '126.com' || domain === 'yeah.net' || domain === 'netease.com') {
    return '163'
  }
  if (domain === 'qq.com' || domain === 'foxmail.com') {
    return 'qq'
  }

  // Provider fallback only when domain is unknown
  if (prov === 'gmail') {
    return 'gmail'
  }
  if (prov === 'graph') {
    return 'outlook'
  }

  return 'generic'
}

export function getEmailInitial(email?: string): string | null {
  if (!email || !email.includes('@')) return null
  const username = email.split('@')[0].trim()
  if (!username) return null
  // Spread operator safely decomposes unicode surrogate pairs / code points
  const chars = [...username]
  if (!chars.length || !chars[0].trim()) return null
  return chars[0].toUpperCase()
}
