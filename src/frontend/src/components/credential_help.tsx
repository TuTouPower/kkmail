import { useEffect, useRef } from 'react'
import { vendors, type Vendor, type Protocol } from '../lib/account_providers'

export default function CredentialHelp({ vendor, protocol, onClose }: { vendor: Vendor; protocol: Protocol; onClose: () => void }) {
  const ref = useRef<HTMLDialogElement>(null)
  // Mount/unmount lifecycle only: remember the previously focused element
  // and restore it (plus close the dialog) when the component unmounts.
  useEffect(() => {
    const previous = document.activeElement
    const dialog = ref.current!
    return () => { if (dialog.open) dialog.close(); if (previous instanceof HTMLElement && previous.isConnected) previous.focus() }
  }, [])
  // A330: keep the dialog in sync with vendor/protocol while it stays
  // mounted. Content re-renders from the current props, and if the dialog
  // was closed in place we re-open it for the new context; an already-open
  // dialog is left alone (showModal on an open dialog would throw).
  useEffect(() => {
    const dialog = ref.current
    if (dialog && !dialog.open) dialog.showModal()
  }, [vendor, protocol])
  const info = vendors[vendor]
  return <dialog className="settings-dialog" ref={ref} aria-labelledby="credential-help-title" onCancel={event => { event.preventDefault(); event.stopPropagation(); onClose() }}>
    <h2 id="credential-help-title">{info.label} · {protocol === 'imap' || vendor === 'google' ? 'IMAP 凭据获取' : 'OAuth 登录配置'}</h2>
    <ol>{info.steps.map(step => <li key={step}>{step}</li>)}</ol>
    {info.url && <p><a href={info.url} target="_blank" rel="noreferrer">{vendor === 'google' ? '打开 Google 应用专用密码页面' : '查看供应商官方帮助'}</a></p>}
    <button type="button" className="settings-button" aria-label="关闭凭据帮助" onClick={onClose}>关闭说明</button>
  </dialog>
}
