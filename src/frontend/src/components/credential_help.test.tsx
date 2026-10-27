// @vitest-environment jsdom
import { useState } from 'react'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import CredentialHelp from './credential_help'
import type { Protocol, Vendor } from '../lib/account_providers'
import { cleanup, click, render } from '../test/render'

let showModalCalls = 0

beforeEach(() => {
  showModalCalls = 0
  HTMLDialogElement.prototype.showModal = function () {
    showModalCalls += 1
    this.setAttribute('open', '')
  }
  HTMLDialogElement.prototype.close = function () {
    this.removeAttribute('open')
  }
})

afterEach(() => cleanup())

function Harness() {
  const [vendor, setVendor] = useState<Vendor>('google')
  const [protocol] = useState<Protocol>('imap')
  return (
    <>
      <button type="button" data-switch="qq" onClick={() => setVendor('qq')}>switch qq</button>
      <button type="button" data-switch="google" onClick={() => setVendor('google')}>switch google</button>
      <CredentialHelp vendor={vendor} protocol={protocol} onClose={() => {}} />
    </>
  )
}

describe('<CredentialHelp /> (A330)', () => {
  it('keeps an open dialog in sync when vendor changes without unmounting', async () => {
    const { container } = await render(<Harness />)
    const dialog = container.querySelector('dialog')!
    expect(dialog.hasAttribute('open')).toBe(true)
    expect(showModalCalls).toBe(1)
    expect(container.querySelector('#credential-help-title')?.textContent).toContain('Google')

    // Vendor changes while the dialog stays mounted/open: the content
    // follows and showModal must not be re-invoked on an open dialog.
    await click(container.querySelector('[data-switch="qq"]'))
    expect(container.querySelector('#credential-help-title')?.textContent).toContain('QQ')
    expect(dialog.hasAttribute('open')).toBe(true)
    expect(showModalCalls).toBe(1)
  })

  it('re-opens the dialog when vendor changes after it was closed in place (A330)', async () => {
    const { container } = await render(<Harness />)
    const dialog = container.querySelector('dialog')!
    expect(dialog.hasAttribute('open')).toBe(true)

    // Dialog closed without unmounting the component (desync state).
    dialog.close()
    expect(dialog.hasAttribute('open')).toBe(false)

    await click(container.querySelector('[data-switch="qq"]'))
    expect(container.querySelector('#credential-help-title')?.textContent).toContain('QQ')
    expect(dialog.hasAttribute('open')).toBe(true)
    expect(showModalCalls).toBe(2)
  })

  it('restores focus to the previously focused element on unmount', async () => {
    const trigger = document.createElement('button')
    trigger.textContent = 'trigger'
    document.body.appendChild(trigger)
    trigger.focus()
    const second = await render(<CredentialHelp vendor="google" protocol="imap" onClose={() => {}} />)
    second.unmount()
    expect(document.activeElement).toBe(trigger)
    trigger.remove()
  })
})
