import { describe, expect, it } from 'vitest'
import { ensureSuccess, errorMessage } from './actions'

describe('action helpers', () => {
  it('throws on success:false', () => {
    expect(() => ensureSuccess({ success: false, error: '账号不存在' })).toThrow('账号不存在')
    expect(() => ensureSuccess({ success: false, error: { message: 'x' } })).toThrow('x')
    expect(ensureSuccess({ success: true })).toEqual({ success: true })
  })
  it('extracts messages', () => {
    expect(errorMessage({ status: 401, message: '未登录' })).toBe('未登录')
    expect(errorMessage(null, 'fb')).toBe('fb')
  })
})
