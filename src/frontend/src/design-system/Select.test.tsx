import { act, useState } from 'react'
import { afterEach, expect, it, vi } from 'vitest'
import { Combobox, Select } from './Select'
import { cleanup, click, render, typeInto } from '../test/render'

afterEach(() => cleanup())

const options = [
  { value: 'google', label: 'Google' },
  { value: 'microsoft', label: 'Microsoft' },
]

function Harness() {
  const [value, setValue] = useState('google')
  const [typed, setTyped] = useState('')
  return <div>
    <Select id="vendor" ariaLabel="邮箱供应商" value={value} onChange={setValue} options={options} />
    <output data-testid="value">{value}</output>
    <Combobox id="tenant" ariaLabel="租户" value={typed} onChange={setTyped} options={options} />
    <output data-testid="typed">{typed}</output>
  </div>
}

it('opens an in-app popover, selects an option and restores focus to the trigger', async () => {
  const { container } = await render(<Harness />)
  const trigger = container.querySelector('#vendor') as HTMLButtonElement
  expect(trigger.textContent).toBe('Google')
  expect(trigger.getAttribute('aria-expanded')).toBe('false')
  await click(trigger)
  expect(trigger.getAttribute('aria-expanded')).toBe('true')
  const popover = container.querySelector('[data-select-open="true"]') as HTMLElement
  expect(popover.getAttribute('role')).toBe('listbox')
  expect([...popover.querySelectorAll('[role="option"]')].map(option => option.textContent)).toEqual(['Google', 'Microsoft'])
  await click(popover.querySelector('[data-option-value="microsoft"]'))
  expect(container.querySelector('[data-testid="value"]')?.textContent).toBe('microsoft')
  expect(trigger.getAttribute('aria-expanded')).toBe('false')
  expect(document.activeElement).toBe(trigger)
})

it('supports arrow keys, Enter and Escape with an accessible name and disabled state', async () => {
  const { container } = await render(<Harness />)
  const trigger = container.querySelector('#vendor') as HTMLButtonElement
  expect(trigger.getAttribute('aria-label')).toBe('邮箱供应商')
  await act(async () => { trigger.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowDown', bubbles: true })) })
  expect(trigger.getAttribute('aria-expanded')).toBe('true')
  await act(async () => { trigger.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowDown', bubbles: true })) })
  await act(async () => { trigger.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true })) })
  expect(container.querySelector('[data-testid="value"]')?.textContent).toBe('microsoft')
  await act(async () => { trigger.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowDown', bubbles: true })) })
  await act(async () => { trigger.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true })) })
  expect(trigger.getAttribute('aria-expanded')).toBe('false')
  expect(document.activeElement).toBe(trigger)

  const { container: disabledContainer } = await render(<Select value="google" onChange={vi.fn()} options={options} disabled ariaLabel="禁用" />)
  const disabledTrigger = disabledContainer.querySelector('[role="combobox"]') as HTMLButtonElement
  await click(disabledTrigger)
  expect(disabledContainer.querySelector('[data-select-open="true"]')).toBeNull()
})

it('combobox keeps free text input and offers themed suggestions', async () => {
  const { container } = await render(<Harness />)
  const input = container.querySelector('#tenant') as HTMLInputElement
  await typeInto(input, 'goo')
  expect(container.querySelector('[data-testid="typed"]')?.textContent).toBe('goo')
  const popover = container.querySelector('[data-select-open="true"]') as HTMLElement
  expect([...popover.querySelectorAll('[data-option-value]')].map(option => option.getAttribute('data-option-value'))).toEqual(['google'])
  await click(popover.querySelector('[data-option-value="google"]'))
  expect(container.querySelector('[data-testid="typed"]')?.textContent).toBe('google')
  expect(document.activeElement).toBe(input)
  expect(container.querySelector('[data-select-open="true"]')).toBeNull()
  await click(input)
  expect(container.querySelector('[data-select-open="true"]')).not.toBeNull()
})
