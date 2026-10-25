import { describe, expect, it } from 'vitest'
import { errorMessage } from './actions'

describe('action helpers', () => {
  it('extracts messages', () => {
    expect(errorMessage({ status: 401, message: '未登录' })).toBe('未登录')
    expect(errorMessage(new Error('boom'))).toBe('boom')
    expect(errorMessage(null, 'fb')).toBe('fb')
  })

  it('never surfaces "[object Object]" (p053)', () => {
    expect(errorMessage(new Error('[object Object]'), 'fb')).toBe('fb')
    expect(errorMessage('[object Object]', 'fb')).toBe('fb')
    expect(errorMessage({ message: '[object Object]' }, 'fb')).toBe('fb')
    expect(errorMessage({ detail: { error: 'CSRF validation failed', csrf_error: true } })).toBe('CSRF validation failed')
  })

  it('extracts readable text from nested object detail values (p053)', () => {
    expect(errorMessage({ detail: { error: 'CSRF validation failed', csrf_error: true } })).toBe('CSRF validation failed')
    expect(errorMessage({ detail: { message: '内部详情' } })).toBe('内部详情')
    expect(errorMessage({ detail: { detail: { error: '深层错误' } } })).toBe('深层错误')
    expect(errorMessage({ message: { message: '嵌套消息' } })).toBe('嵌套消息')
  })

  it('extracts readable text from array detail values (FastAPI 422)', () => {
    expect(
      errorMessage({ detail: [{ loc: ['body', 'client_request_id'], msg: 'Field required', type: 'missing' }] }),
    ).toBe('Field required')
    expect(errorMessage({ detail: ['第一条', '第二条'] })).toBe('第一条; 第二条')
    expect(errorMessage({ detail: [] }, 'fb')).toBe('fb')
    expect(errorMessage({ detail: {} }, 'fb')).toBe('fb')
  })
})
