import { describe, expect, it } from 'vitest'
import { parseSseChunk } from './client'

describe('parseSseChunk', () => {
  it('parses data lines and skips junk', () => {
    const evts = parseSseChunk('data: {"type":"progress","current":1,"total":2}\n: keep-alive\ndata: not-json')
    expect(evts).toEqual([{ type: 'progress', current: 1, total: 2 }])
  })
})
