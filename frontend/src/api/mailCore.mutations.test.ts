import { afterEach, describe, expect, it, vi } from 'vitest'
import { postMailCoreMessageFlag, postMailCoreMessageRead } from './mailCore'
import { markReadOptimistic, queryClient, type MailItem } from './queries'

vi.mock('../lib/mailCoreFlag', () => ({
  mailCoreBaseUrl: () => 'http://mail-core.test',
  isMailCoreEnabled: () => true,
}))

afterEach(() => {
  vi.unstubAllGlobals()
  queryClient.clear()
})

describe('postMailCoreMessageRead / Flag', () => {
  it('POSTs read body', async () => {
    const fetchMock = vi.fn(async () =>
      new Response(JSON.stringify({ id: 'm1', is_read: true }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    )
    vi.stubGlobal('fetch', fetchMock)
    const out = await postMailCoreMessageRead('m1', true)
    expect(out.is_read).toBe(true)
    expect(fetchMock).toHaveBeenCalledOnce()
    const call = fetchMock.mock.calls[0] as unknown as [string, RequestInit]
    expect(String(call[0])).toContain('/api/mail/messages/m1/read')
    expect(call[1]?.method).toBe('POST')
    expect(JSON.parse(String(call[1]?.body))).toEqual({ is_read: true })
  })

  it('POSTs flag body', async () => {
    const fetchMock = vi.fn(async () =>
      new Response(JSON.stringify({ id: 'm1', is_flagged: true }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    )
    vi.stubGlobal('fetch', fetchMock)
    const out = await postMailCoreMessageFlag('m1', true)
    expect(out.is_flagged).toBe(true)
    const call = fetchMock.mock.calls[0] as unknown as [string, RequestInit]
    expect(String(call[0])).toContain('/api/mail/messages/m1/flag')
    expect(JSON.parse(String(call[1]?.body))).toEqual({ is_flagged: true })
  })
})

describe('markReadOptimistic mail-core', () => {
  it('optimistically marks then POSTs mail-core; reverts on failure', async () => {
    const item: MailItem = {
      id: 'uuid-1',
      subject: 'S',
      from: 'a@b.c',
      is_read: false,
      has_attachments: false,
      accountEmail: 'acc-1',
      folder: 'inbox',
      id_mode: 'mail_core',
    }
    queryClient.setQueryData(['mail-core', 'inbox'], [item])

    const fetchMock = vi.fn(async () =>
      new Response('boom', { status: 500 }),
    )
    vi.stubGlobal('fetch', fetchMock)

    await expect(markReadOptimistic([item])).rejects.toThrow()
    const cached = queryClient.getQueryData<MailItem[]>(['mail-core', 'inbox'])
    expect(cached?.[0]?.is_read).toBe(false)
    expect(String((fetchMock.mock.calls[0] as unknown as [string])[0])).toContain('/read')
  })

  it('keeps optimistic read when POST succeeds', async () => {
    const item: MailItem = {
      id: 'uuid-2',
      subject: 'S',
      from: 'a@b.c',
      is_read: false,
      has_attachments: false,
      accountEmail: 'acc-1',
      folder: 'inbox',
      id_mode: 'mail_core',
    }
    queryClient.setQueryData(['mail-core', 'inbox'], [item])
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        new Response(JSON.stringify({ id: 'uuid-2', is_read: true }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        }),
      ),
    )
    await markReadOptimistic([item])
    const cached = queryClient.getQueryData<MailItem[]>(['mail-core', 'inbox'])
    expect(cached?.[0]?.is_read).toBe(true)
  })
})

import { flagOptimistic } from './queries'

describe('flagOptimistic mail-core', () => {
  it('applies local then POSTs; reverts local on failure', async () => {
    const item: MailItem = {
      id: 'uuid-f',
      subject: 'S',
      from: 'a@b.c',
      is_read: true,
      has_attachments: false,
      accountEmail: 'acc-1',
      folder: 'inbox',
      id_mode: 'mail_core',
    }
    const local = vi.fn()
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => new Response('nope', { status: 503 })),
    )
    await expect(flagOptimistic(item, true, local)).rejects.toThrow()
    expect(local).toHaveBeenCalledTimes(2) // apply + revert
  })

  it('skips POST for flask items', async () => {
    const item: MailItem = {
      id: '1',
      subject: 'S',
      from: 'a@b.c',
      is_read: true,
      has_attachments: false,
      accountEmail: 'a@b.c',
      folder: 'inbox',
      id_mode: '',
    }
    const local = vi.fn()
    const fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)
    await flagOptimistic(item, true, local)
    expect(local).toHaveBeenCalledOnce()
    expect(fetchMock).not.toHaveBeenCalled()
  })
})
