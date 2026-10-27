import { describe, expect, it } from 'vitest'
import { BRAND_ICON_COMPONENTS } from './brandIconMap'
import type { BrandType } from '../../store/accountIcon'

// Every member of the BrandType union must have an icon component;
// the Record<BrandType, …> typing makes a missing entry a compile error,
// and this list mirrors the union so a missing entry also fails at runtime.
const ALL_BRANDS: BrandType[] = [
  '126',
  '139',
  '163',
  '189',
  'aliyun',
  'default-mail',
  'enterprise',
  'exchange',
  'foxmail',
  'generic',
  'gmail',
  'google',
  'icloud',
  'outlook',
  'protonmail',
  'qq',
  'sina',
  'sohu',
  'yahoo',
  'yandex',
  'yeah',
]

describe('BRAND_ICON_COMPONENTS', () => {
  it('covers exactly every BrandType with a component', () => {
    expect(Object.keys(BRAND_ICON_COMPONENTS).sort()).toEqual([...ALL_BRANDS].sort())
    for (const brand of ALL_BRANDS) {
      expect(typeof BRAND_ICON_COMPONENTS[brand]).toBe('function')
    }
  })
})
