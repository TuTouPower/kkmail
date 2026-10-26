export type AccountIconMode = 'none' | 'brand' | 'initials'

export type BrandType =
  | '163'
  | '126'
  | 'yeah'
  | 'qq'
  | 'exchange'
  | 'outlook'
  | 'enterprise'
  | 'default-mail'
  | 'gmail'
  | 'google'
  | 'yahoo'
  | 'yandex'
  | 'icloud'
  | 'protonmail'
  | '139'
  | '189'
  | 'foxmail'
  | 'sina'
  | 'sohu'
  | 'aliyun'
  | 'generic'

export const EMAIL_DOMAIN_BRAND_MAP: Record<string, BrandType> = {
  // 网易系
  '163.com': '163',
  'vip.163.com': '163',
  'netease.com': '163',
  '126.com': '126',
  'vip.126.com': '126',
  'yeah.net': 'yeah',

  // 腾讯系
  'qq.com': 'qq',
  'vip.qq.com': 'qq',
  'foxmail.com': 'foxmail',

  // 微软系
  'outlook.com': 'outlook',
  'hotmail.com': 'outlook',
  'live.com': 'outlook',
  'msn.com': 'outlook',
  'office365.com': 'outlook',

  // 谷歌系
  'gmail.com': 'gmail',
  'googlemail.com': 'gmail',
  'google.com': 'google',

  // 雅虎
  'yahoo.com': 'yahoo',
  'yahoo.co.jp': 'yahoo',
  'yahoo.com.cn': 'yahoo',
  'ymail.com': 'yahoo',

  // Yandex
  'yandex.com': 'yandex',
  'yandex.ru': 'yandex',
  'ya.ru': 'yandex',
  'yandex.by': 'yandex',
  'yandex.kz': 'yandex',
  'yandex.ua': 'yandex',

  // Apple iCloud
  'icloud.com': 'icloud',
  'me.com': 'icloud',
  'mac.com': 'icloud',

  // 运营商
  '139.com': '139',
  '189.cn': '189',

  // 国内门户与阿里
  'sina.com': 'sina',
  'sina.cn': 'sina',
  'vip.sina.com': 'sina',
  'sohu.com': 'sohu',
  'aliyun.com': 'aliyun',

  // 安全邮箱
  'proton.me': 'protonmail',
  'protonmail.com': 'protonmail',
}

export const BRAND_TITLES: Record<string, string> = {
  '163': '163邮箱',
  '126': '126邮箱',
  'yeah': 'Yeah.net邮箱',
  'qq': 'QQ邮箱',
  'exchange': 'Exchange',
  'outlook': 'Outlook',
  'enterprise': '企业邮箱',
  'default-mail': '默认邮箱',
  'generic': '默认邮箱',
  'gmail': 'Gmail',
  'google': 'Google Workspace',
  'yahoo': 'Yahoo',
  'yandex': 'Yandex',
  'icloud': 'iCloud',
  'protonmail': 'Proton Mail',
  '139': '139邮箱',
  '189': '189邮箱',
  'foxmail': 'Foxmail',
  'sina': '新浪邮箱',
  'sohu': '搜狐邮箱',
  'aliyun': '阿里云邮箱',
}

export function getEmailDomain(email?: string): string {
  if (!email || !email.includes('@')) return ''
  const parts = email.split('@')
  return (parts[parts.length - 1] || '').trim().toLowerCase()
}

export function detectAccountBrand(email?: string, provider?: string, accountType?: string): BrandType {
  const domain = getEmailDomain(email)
  const prov = (provider || '').toLowerCase()
  const accType = (accountType || '').toLowerCase()

  // 1. 域名精确命中
  if (domain && EMAIL_DOMAIN_BRAND_MAP[domain]) {
    return EMAIL_DOMAIN_BRAND_MAP[domain]
  }

  // 2. Provider 回退
  if (prov === 'graph') {
    return 'outlook'
  }
  if (prov === 'exchange' || accType === 'exchange') {
    return 'exchange'
  }
  if (accType === 'enterprise') {
    return 'enterprise'
  }

  // 3. 默认回退
  return 'default-mail'
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
