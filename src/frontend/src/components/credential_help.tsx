import { useEffect, useRef } from 'react'
import { vendors, type Vendor, type Protocol } from '../lib/account_providers'

export default function CredentialHelp({ vendor, protocol, onClose }: { vendor: Vendor; protocol: Protocol; onClose: () => void }) {
  const ref = useRef<HTMLDialogElement>(null)
  useEffect(() => {
    const previous = document.activeElement
    const dialog = ref.current!
    dialog.showModal()
    return () => { dialog.close(); if (previous instanceof HTMLElement && previous.isConnected) previous.focus() }
  }, [])
  const info = vendors[vendor]
  return <dialog className="settings-dialog" ref={ref} aria-labelledby="credential-help-title" onCancel={event => { event.preventDefault(); event.stopPropagation(); onClose() }}>
    <h2 id="credential-help-title">{info.label} · {protocol === 'imap' ? 'IMAP 凭据获取' : 'OAuth 登录配置'}</h2>
    <ol>{info.steps.map(step => <li key={step}>{step}</li>)}</ol>
    {info.url && <p><a href={info.url} target="_blank" rel="noreferrer">查看供应商官方帮助</a></p>}
    <button type="button" className="settings-button" aria-label="关闭凭据帮助" onClick={onClose}>关闭说明</button>
  </dialog>
}
