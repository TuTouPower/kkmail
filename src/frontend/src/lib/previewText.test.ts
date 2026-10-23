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

describe('provider preview display', () => {
  it('preserves angle-bracket email addresses, including inside HTML', () => {
    expect(previewText('Contact <support@openai.com> or <a@example.com>')).toBe('Contact <support@openai.com> or <a@example.com>')
    expect(previewText('<p>Contact <support@openai.com></p>')).toBe('Contact <support@openai.com>')
  })
  it('omits HTML document metadata from display', () => {
    expect(previewText('<html><head><title>Hidden</title></head><body>Hello</body></html>')).toBe('Hello')
  })
})

describe('HTML preview metadata', () => {
  it('removes doctype and comments without changing an email address', () => {
    expect(previewText('<!DOCTYPE html><!-- metadata --><p>Contact <support@openai.com></p>')).toBe('Contact <support@openai.com>')
  })
  it('hides incomplete document metadata in truncated provider previews', () => {
    expect(previewText('<html><head><meta charset=')).toBe('')
  })
})
