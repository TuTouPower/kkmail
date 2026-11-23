import assert from 'node:assert/strict'
import test from 'node:test'
import { findNativeControls } from './check_native_select.mjs'

test('accepts token-driven primitive usage', () => {
  const problems = findNativeControls({
    'src/design-system/Select.tsx': 'return <div role="listbox"><Select value={value} /></div>',
    'src/components/form.tsx': '<label><Combobox id="tenant" value={value} /></label>',
  })
  assert.deepEqual(problems, [])
})

test('rejects native select and datalist with file and line', () => {
  const problems = findNativeControls({
    'src/components/legacy.tsx': 'const a = 1\n<select id="a" />\n<datalist id="b" />',
  })
  assert.deepEqual(problems, [
    { file: 'src/components/legacy.tsx', line: 2, tag: 'select' },
    { file: 'src/components/legacy.tsx', line: 3, tag: 'datalist' },
  ])
})
