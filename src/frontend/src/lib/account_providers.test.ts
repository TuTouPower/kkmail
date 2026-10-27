import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  MICROSOFT_DEFAULT_REDIRECT_URI,
  MICROSOFT_GRAPH_SCOPES,
  MICROSOFT_PUBLIC_CLIENT_ID,
  buildMicrosoftAuthorizeUrl,
  defaultProtocol,
  domains,
  inferVendor,
  vendors,
  type Vendor,
} from './account_providers'
import { EMAIL_DOMAIN_BRAND_MAP, type BrandType } from '../store/accountIcon'

// A93: the OAuth authorize-URL builder and vendor inference are
// security-sensitive (a wrong client_id / redirect / unencoded hint sends
// the user to a wrong or attacker-influenced authorize page) but had no
// unit coverage. These tests pin the domain table, the URL parameter
// encoding, and the constants that must stay aligned with the backend.

const DOMAIN_CASES: Array<[string, Vendor]> = [
  ['user@gmail.com', 'google'],
  ['user@googlemail.com', 'google'],
  ['user@outlook.com', 'microsoft'],
  ['user@outlook.cn', 'microsoft'],
  ['user@hotmail.com', 'microsoft'],
  ['user@live.com', 'microsoft'],
  ['user@msn.com', 'microsoft'],
  ['user@hotmail.co.uk', 'microsoft'],
  ['user@live.co.uk', 'microsoft'],
  ['user@hotmail.fr', 'microsoft'],
  ['user@live.fr', 'microsoft'],
  ['user@hotmail.de', 'microsoft'],
  ['user@live.de', 'microsoft'],
  ['user@outlook.de', 'microsoft'],
  ['user@qq.com', 'qq'],
  ['user@foxmail.com', 'qq'],
  ['user@163.com', 'netease_163'],
  ['user@126.com', 'netease_126'],
  ['user@yeah.net', 'netease_yeah'],
  ['user@icloud.com', 'icloud'],
  ['user@me.com', 'icloud'],
  ['user@mac.com', 'icloud'],
  ['user@yahoo.com', 'yahoo'],
  ['user@yahoo.co.uk', 'yahoo'],
  ['user@zoho.com', 'zoho'],
  ['user@zohomail.com', 'zoho'],
]

describe('inferVendor domain table (A93)', () => {
  it.each(DOMAIN_CASES)('maps %s to %s', (email, vendor) => {
    expect(inferVendor(email)).toBe(vendor)
  })

  it('falls back to other for unknown domains, missing @ and empty input', () => {
    expect(inferVendor('user@example.org')).toBe('other')
    expect(inferVendor('not-an-email')).toBe('other')
    expect(inferVendor('')).toBe('other')
    expect(inferVendor('user@')).toBe('other')
  })

  it('is case-insensitive and ignores surrounding whitespace', () => {
    expect(inferVendor('  User@GMAIL.COM ')).toBe('google')
    expect(inferVendor('User@Outlook.COM')).toBe('microsoft')
  })

  it('does not match on substrings or suffix spoofing', () => {
    expect(inferVendor('user@notgmail.com')).toBe('other')
    expect(inferVendor('user@gmail.com.evil.org')).toBe('other')
    expect(inferVendor('user@evil-gmail.com')).toBe('other')
  })

  it('only microsoft defaults to graph; every other vendor defaults to imap', () => {
    expect(defaultProtocol('microsoft')).toBe('graph')
    for (const vendor of Object.keys(vendors) as Vendor[]) {
      if (vendor !== 'microsoft') expect(defaultProtocol(vendor)).toBe('imap')
    }
  })
})

describe('buildMicrosoftAuthorizeUrl (A93)', () => {
  it('builds the v2.0 authorize URL with the built-in public client by default', () => {
    const url = new URL(buildMicrosoftAuthorizeUrl({ state: 'state-1' }))
    expect(`${url.origin}${url.pathname}`).toBe('https://login.microsoftonline.com/common/oauth2/v2.0/authorize')
    expect(url.searchParams.get('client_id')).toBe(MICROSOFT_PUBLIC_CLIENT_ID)
    expect(url.searchParams.get('response_type')).toBe('code')
    expect(url.searchParams.get('redirect_uri')).toBe(MICROSOFT_DEFAULT_REDIRECT_URI)
    expect(url.searchParams.get('response_mode')).toBe('query')
    expect(url.searchParams.get('scope')).toBe(MICROSOFT_GRAPH_SCOPES)
    expect(url.searchParams.get('state')).toBe('state-1')
    expect(url.searchParams.get('prompt')).toBe('select_account')
    expect(url.searchParams.has('login_hint')).toBe(false)
  })

  it('honours trimmed custom client_id / redirect_uri and encodes special characters', () => {
    const raw = buildMicrosoftAuthorizeUrl({
      clientId: '  custom-client  ',
      redirectUri: ' http://localhost:9999/callback?x=1&y=2 ',
      email: 'a+b@example.com',
      state: 's t&a=t+e',
    })
    const url = new URL(raw)
    expect(url.searchParams.get('client_id')).toBe('custom-client')
    expect(url.searchParams.get('redirect_uri')).toBe('http://localhost:9999/callback?x=1&y=2')
    expect(url.searchParams.get('login_hint')).toBe('a+b@example.com')
    expect(url.searchParams.get('state')).toBe('s t&a=t+e')
    // The raw query must be percent/form encoded, never interpolated verbatim.
    expect(raw).not.toContain('login_hint=a+b@example.com')
    expect(raw).not.toContain('state=s t&a=t+e')
    expect(raw).toContain('login_hint=a%2Bb%40example.com')
  })

  it('falls back to the defaults for blank client_id / redirect_uri', () => {
    const url = new URL(buildMicrosoftAuthorizeUrl({ clientId: '   ', redirectUri: '', state: 'x' }))
    expect(url.searchParams.get('client_id')).toBe(MICROSOFT_PUBLIC_CLIENT_ID)
    expect(url.searchParams.get('redirect_uri')).toBe(MICROSOFT_DEFAULT_REDIRECT_URI)
  })

  it('sets login_hint only for a non-blank email, trimmed', () => {
    const withHint = new URL(buildMicrosoftAuthorizeUrl({ email: '  user@outlook.com ', state: 'x' }))
    expect(withHint.searchParams.get('login_hint')).toBe('user@outlook.com')
    const blank = new URL(buildMicrosoftAuthorizeUrl({ email: '   ', state: 'x' }))
    expect(blank.searchParams.has('login_hint')).toBe(false)
  })

  it('generates a non-empty state when none is supplied', () => {
    const a = new URL(buildMicrosoftAuthorizeUrl()).searchParams.get('state')
    const b = new URL(buildMicrosoftAuthorizeUrl()).searchParams.get('state')
    expect(a).toBeTruthy()
    expect(b).toBeTruthy()
    expect(a).not.toBe(b)
  })
})

describe('backend contract alignment (A93)', () => {
  // Contract assertion: these literals mirror DEFAULT_MICROSOFT_CLIENT_ID /
  // DEFAULT_MICROSOFT_REDIRECT_URI in
  // src/mail_core/accounts/microsoft_oauth.py. The simplified onboarding
  // flow only works while the frontend authorize URL and the backend token
  // exchange agree on the same public client and redirect URI, so a drift
  // on either side must fail here instead of breaking sign-in silently.
  it('keeps the public client id and redirect URI aligned with the backend defaults', () => {
    expect(MICROSOFT_PUBLIC_CLIENT_ID).toBe('9e5f94bc-e8a4-4e73-b8be-63364c29d753')
    expect(MICROSOFT_DEFAULT_REDIRECT_URI).toBe('http://localhost:8080')
  })

  it('requests exactly the Graph mail scopes plus offline_access', () => {
    expect(MICROSOFT_GRAPH_SCOPES).toBe(
      'https://graph.microsoft.com/Mail.ReadWrite https://graph.microsoft.com/User.Read offline_access',
    )
  })
})

describe('vendor domain table vs brand domain table cross-consistency (A96)', () => {
  // A96: account_providers' vendor table and accountIcon's brand table are
  // two hand-maintained domain tables whose coverage had drifted apart.
  // Instead of silently diverging further, every domain that exists in
  // only one table is listed below with its adjudication; adding a domain
  // to either table without adjudicating it here fails this test.
  //
  // Vendor-only (11): regional Microsoft/Yahoo domains still need a vendor
  // for the correct sign-in flow and IMAP host, while the brand table
  // intentionally has no region-specific icons (the base domains carry
  // the brand); zoho.com / zohomail.com need the vendor's IMAP steps but
  // no Zoho brand icon exists in the brand set.
  const VENDOR_ONLY_ADJUDICATED = [
    'hotmail.co.uk', 'hotmail.de', 'hotmail.fr', 'live.co.uk', 'live.de',
    'live.fr', 'outlook.cn', 'outlook.de', 'yahoo.co.uk',
    'zoho.com', 'zohomail.com',
  ]
  // Brand-only (24): brands for mailboxes the vendor table deliberately
  // routes to 'other' (custom IMAP: Yandex, Proton, Sina, Sohu, Aliyun,
  // 139/189 carrier mail, NetEase/Google/Microsoft alias and VIP domains),
  // because they need no vendor-specific credential steps.
  const BRAND_ONLY_ADJUDICATED = [
    '139.com', '189.cn', 'aliyun.com', 'google.com', 'netease.com',
    'office365.com', 'proton.me', 'protonmail.com', 'sina.cn', 'sina.com',
    'sohu.com', 'vip.126.com', 'vip.163.com', 'vip.qq.com', 'vip.sina.com',
    'ya.ru', 'yahoo.co.jp', 'yahoo.com.cn', 'yandex.by', 'yandex.com',
    'yandex.kz', 'yandex.ru', 'yandex.ua', 'ymail.com',
  ]
  // For domains present in both tables, the brand must be the icon that
  // belongs to the vendor (foxmail is the one adjudicated exception: it
  // follows QQ's vendor flow but keeps its own brand icon).
  const VENDOR_BRANDS: Record<Vendor, BrandType[]> = {
    other: [],
    google: ['gmail'],
    microsoft: ['outlook'],
    qq: ['qq', 'foxmail'],
    netease_163: ['163'],
    netease_126: ['126'],
    netease_yeah: ['yeah'],
    icloud: ['icloud'],
    yahoo: ['yahoo'],
    zoho: [],
  }

  it('exhaustively routes every vendor-table domain through inferVendor', () => {
    for (const [domain, vendor] of Object.entries(domains)) {
      expect(inferVendor(`user@${domain}`), domain).toBe(vendor)
    }
  })

  it('has no unadjudicated vendor-only domains', () => {
    const vendorOnly = Object.keys(domains).filter((d) => !(d in EMAIL_DOMAIN_BRAND_MAP)).sort()
    expect(vendorOnly).toEqual([...VENDOR_ONLY_ADJUDICATED].sort())
  })

  it('has no unadjudicated brand-only domains', () => {
    const brandOnly = Object.keys(EMAIL_DOMAIN_BRAND_MAP).filter((d) => !(d in domains)).sort()
    expect(brandOnly).toEqual([...BRAND_ONLY_ADJUDICATED].sort())
  })

  it('keeps overlapping domains on the brand that belongs to their vendor', () => {
    for (const [domain, vendor] of Object.entries(domains)) {
      const brand = EMAIL_DOMAIN_BRAND_MAP[domain]
      if (!brand) continue
      expect(VENDOR_BRANDS[vendor], domain).toContain(brand)
    }
  })
})

describe('OAuth state generation fallback (A152)', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  it('prefers crypto.randomUUID when available and never calls getRandomValues', () => {
    vi.stubGlobal('crypto', {
      randomUUID: () => '11111111-2222-4333-8444-555555555555',
      getRandomValues: () => { throw new Error('must not be called') },
    })
    const state = new URL(buildMicrosoftAuthorizeUrl()).searchParams.get('state')
    expect(state).toBe('11111111-2222-4333-8444-555555555555')
  })

  it('falls back to crypto.getRandomValues UUID bytes in non-secure contexts, never Math.random', () => {
    const mathRandom = vi.spyOn(Math, 'random').mockImplementation(() => {
      throw new Error('Math.random must not be used for OAuth state')
    })
    vi.stubGlobal('crypto', {
      randomUUID: undefined,
      getRandomValues: (arr: Uint8Array) => {
        for (let i = 0; i < arr.length; i++) arr[i] = i
        return arr
      },
    })
    const state = new URL(buildMicrosoftAuthorizeUrl()).searchParams.get('state')
    // Bytes 0..15 with the version (4) and variant (10xx) bits fixed up.
    expect(state).toBe('00010203-0405-4607-8809-0a0b0c0d0e0f')
    expect(state).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/)
    expect(mathRandom).not.toHaveBeenCalled()
  })
})
