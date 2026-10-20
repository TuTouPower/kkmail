import { describe, expect, it } from 'vitest'
import ColumnResize from './ColumnResize'

describe('ColumnResize', () => {
  it('is a drag handle component', () => {
    expect(typeof ColumnResize).toBe('function')
    expect(ColumnResize.name).toBe('ColumnResize')
  })
})
