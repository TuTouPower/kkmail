import { describe, expect, it } from 'vitest'
import {
  MICROSOFT_DEFAULT_REDIRECT_URI,
  MICROSOFT_GRAPH_SCOPES,
  MICROSOFT_PUBLIC_CLIENT_ID,
  buildMicrosoftAuthorizeUrl,
  defaultProtocol,
  inferVendor,
  vendors,
  type Vendor,
} from './account_providers'

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
