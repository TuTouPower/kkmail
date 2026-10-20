import { describe, expect, it } from 'vitest'
import { errorMessage } from './actions'

describe('action helpers', () => {
  it('extracts messages', () => {
    expect(errorMessage({ status: 401, message: '未登录' })).toBe('未登录')
    expect(errorMessage(new Error('boom'))).toBe('boom')
    expect(errorMessage(null, 'fb')).toBe('fb')
  })
})
