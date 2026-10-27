import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'
import * as queries from './queries'

describe('dead exports (A203)', () => {
  it('queries no longer exports MAIL_LIST_PREFIX, at runtime or in source', () => {
    expect((queries as Record<string, unknown>).MAIL_LIST_PREFIX).toBeUndefined()
    const source = readFileSync(resolve(__dirname, 'queries.ts'), 'utf8')
    expect(source).not.toContain('MAIL_LIST_PREFIX')
  })

  it('schemaTypes no longer declares the unused SyncJobOut alias', () => {
    const source = readFileSync(resolve(__dirname, 'schemaTypes.ts'), 'utf8')
    expect(source).not.toContain('SyncJobOut')
  })
})
