import { useState } from 'react'
import { api } from '../api/client'

export default function LoginPage({ onSuccess }: { onSuccess: () => void }) {
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    setError('')
    setLoading(true)
    try {
      await api.login(password)
      onSuccess()
    } catch (err: unknown) {
      const message = err && typeof err === 'object' && 'message' in err ? String((err as { message: string }).message) : '登录失败'
      setError(message)
    } finally {
      setLoading(false)
    }
  }

  const isDesktop = typeof window !== 'undefined' && Boolean((window as unknown as { kkmailDesktop?: unknown }).kkmailDesktop)

  return (
    <div style={{ minHeight: '100dvh', display: 'grid', placeItems: 'center', background: 'var(--canvas)', color: 'var(--text)', padding: 20 }}>
      <form
        onSubmit={submit}
        style={{
          width: 'min(420px, 100%)',
          background: 'var(--surface)',
          border: '1px solid var(--line)',
          borderRadius: 16,
          padding: 28,
          boxShadow: 'var(--shadow)',
        }}
      >
        <div style={{ fontSize: 20, fontWeight: 700, letterSpacing: '-0.3px', marginBottom: 6 }}>kkmail</div>
        <p style={{ margin: '0 0 20px', color: 'var(--muted)', fontSize: 13 }}>多账号邮箱 · mail-core</p>
        <input type="text" name="username" autoComplete="username" value="kkmail" readOnly hidden aria-hidden="true" />
        <label htmlFor="login-password" style={{ display: "block", fontSize: 12, color: "var(--muted)", marginBottom: 6 }}>登录密码</label>
        <input id="login-password" name="password"
          type="password"
          autoComplete="current-password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          autoFocus
          required
          style={{
            width: '100%',
            height: 40,
            borderRadius: 10,
            border: '1px solid var(--line)',
            background: 'var(--surface-2)',
            padding: '0 12px',
            marginBottom: 14,
          }}
        />
        {error && <div style={{ color: 'var(--red)', fontSize: 12, marginBottom: 12 }}>{error}</div>}
        <button
          type="submit"
          disabled={loading}
          style={{
            width: '100%',
            height: 40,
            border: 0,
            borderRadius: 10,
            background: 'var(--blue)',
            color: '#fff',
            fontWeight: 650,
          }}
        >
          {loading ? '登录中…' : '登录'}
        </button>
        <div style={{ marginTop: 14, fontSize: 11, color: 'var(--muted)', lineHeight: 1.5 }}>
          {isDesktop
            ? '桌面环境：请查看启动时的初始密码对话框（如已修改请使用新密码）'
            : '密码配置见 MAIL_CORE_LOGIN_PASSWORD / MAIL_CORE_LOGIN_PASSWORD_HASH'}
        </div>
      </form>
    </div>
  )
}
