import { describe, expect, it } from 'vitest'
import { previewText } from './previewText'

describe('previewText', () => {
  it('strips HTML tags from previews', () => {
    expect(previewText('<html><head></head><body><p>你好世界</p></body></html>')).toBe('你好世界')
  })
  it('leaves plain text alone and truncates', () => {
    expect(previewText('a'.repeat(200), 10)).toBe(`${'a'.repeat(10)}…`)
  })
})
