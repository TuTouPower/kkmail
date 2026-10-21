import { describe, expect, it } from 'vitest'
import { formatFileSize } from './formatSize'

describe('formatFileSize', () => {
  it('handles 0, null, undefined and negative numbers', () => {
    expect(formatFileSize(0)).toBe('0 B')
    expect(formatFileSize(null)).toBe('')
    expect(formatFileSize(undefined)).toBe('')
    expect(formatFileSize(-100)).toBe('')
    expect(formatFileSize(NaN)).toBe('')
  })

  it('formats byte values under 1 KB', () => {
    expect(formatFileSize(1)).toBe('1 B')
    expect(formatFileSize(512)).toBe('512 B')
    expect(formatFileSize(1023)).toBe('1023 B')
  })

  it('formats KB, MB, GB values with up to one decimal place without trailing zero', () => {
    expect(formatFileSize(1024)).toBe('1 KB')
    expect(formatFileSize(1536)).toBe('1.5 KB')
    expect(formatFileSize(1048576)).toBe('1 MB')
    expect(formatFileSize(20971520)).toBe('20 MB')
    expect(formatFileSize(1073741824)).toBe('1 GB')
    expect(formatFileSize(1610612736)).toBe('1.5 GB')
  })
})
