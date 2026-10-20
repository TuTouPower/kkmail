/** Account capability helpers (send / provider gate). */

export type AccountLike = {
  provider?: string | null
  account_type?: string | null
  status?: string | null
}

/** Outlook/Graph send is allowed only when the account is authorized. Default deny. */
export function canSendFrom(account?: AccountLike | null): boolean {
  if (!account) return false
  const provider = String(account.provider || account.account_type || '').toLowerCase()
  const isOutlookGraph =
    provider === 'graph' ||
    provider === 'outlook' ||
    provider.includes('outlook') ||
    provider.includes('graph')
  if (!isOutlookGraph) return false
  return String(account.status || '').toLowerCase() === 'authorized'
}
