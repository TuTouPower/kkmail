import { describe, expect, it } from 'vitest'
import { previewText } from './previewText'

describe('previewText', () => {
  it('strips HTML tags from previews', () => {
    expect(previewText('<html><head></head><body><p>你好世界</p></body></html>')).toBe('你好世界')
  })
  it('decodes decimal and hexadecimal numeric entities in plain text and HTML', () => {
    expect(previewText('Today&#8217;s mail &#x1F642;')).toBe('Today’s mail 🙂')
    expect(previewText('<p>Quote: &#x201C;hello&#x201D;</p>')).toBe('Quote: “hello”')
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

describe('previewText input bound (A359)', () => {
  it('bounds the text fed into the strip/regex passes to 4×max', () => {
    // Each entity is 5 raw chars decoding to 1 visible char. With max=180 the
    // strip input is capped at 720 raw chars = 144 entities, so content past
    // the cap is never processed even though the unbounded preview would
    // have shown 180 chars plus an ellipsis.
    expect(previewText('&#97;'.repeat(1000))).toBe('a'.repeat(144))
  })
  it('still truncates a bounded long plain preview to max', () => {
    expect(previewText('b'.repeat(5000), 100)).toBe(`${'b'.repeat(100)}…`)
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
