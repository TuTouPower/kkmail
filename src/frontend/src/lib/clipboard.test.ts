// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from 'vitest'
import { copyTextToClipboard } from './clipboard'

describe('copyTextToClipboard', () => {
  afterEach(() => {
    vi.restoreAllMocks()
    Reflect.deleteProperty(navigator, 'clipboard')
  })

  it('copies via navigator.clipboard.writeText when available', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined)
    Object.defineProperty(navigator, 'clipboard', {
      configurable: true,
      value: { writeText },
    })

    await copyTextToClipboard('test@example.com')
    expect(writeText).toHaveBeenCalledWith('test@example.com')
    expect(document.body.querySelectorAll('textarea').length).toBe(0)
  })

  it('falls back to document.execCommand when navigator.clipboard is missing', async () => {
    const execCommand = vi.fn().mockReturnValue(true)
    document.execCommand = execCommand

    await copyTextToClipboard('user@qq.com')
    expect(execCommand).toHaveBeenCalledWith('copy')
    expect(document.body.querySelectorAll('textarea').length).toBe(0)
  })

  it('falls back to document.execCommand when navigator.clipboard.writeText throws', async () => {
    const writeText = vi.fn().mockRejectedValue(new Error('writeText rejected'))
    Object.defineProperty(navigator, 'clipboard', {
      configurable: true,
      value: { writeText },
    })
    const execCommand = vi.fn().mockReturnValue(true)
    document.execCommand = execCommand

    await copyTextToClipboard('fallback@domain.com')
    expect(writeText).toHaveBeenCalledWith('fallback@domain.com')
    expect(execCommand).toHaveBeenCalledWith('copy')
    expect(document.body.querySelectorAll('textarea').length).toBe(0)
  })

  it('throws error when neither navigator.clipboard nor execCommand succeeds', async () => {
    const execCommand = vi.fn().mockReturnValue(false)
    document.execCommand = execCommand

    await expect(copyTextToClipboard('fail@example.com')).rejects.toThrow('当前环境不支持剪贴板写入')
    expect(document.body.querySelectorAll('textarea').length).toBe(0)
  })

  it('rethrows original writeText error when execCommand fails', async () => {
    const writeText = vi.fn().mockRejectedValue(new Error('Permission denied'))
    Object.defineProperty(navigator, 'clipboard', {
      configurable: true,
      value: { writeText },
    })
    const execCommand = vi.fn().mockReturnValue(false)
    document.execCommand = execCommand

    await expect(copyTextToClipboard('fail@example.com')).rejects.toThrow('Permission denied')
    expect(document.body.querySelectorAll('textarea').length).toBe(0)
  })

  it('appends textarea inside active dialog and restores focus on fallback copy (P2-10)', async () => {
    const dialog = document.createElement('dialog')
    dialog.setAttribute('open', '')
    const button = document.createElement('button')
    dialog.appendChild(button)
    document.body.appendChild(dialog)
    button.focus()
    expect(document.activeElement).toBe(button)

    let textareaParent: Node | null = null
    const execCommand = vi.fn(() => {
      const ta = document.querySelector('textarea')
      textareaParent = ta ? ta.parentElement : null
      return true
    })
    document.execCommand = execCommand

    await copyTextToClipboard('modal-copy@test.com')
    expect(execCommand).toHaveBeenCalledWith('copy')
    // Verify textarea was appended inside dialog, NOT directly to body
    expect(textareaParent).toBe(dialog)
    // Verify focus was restored to the button
    expect(document.activeElement).toBe(button)

    document.body.removeChild(dialog)
  })
})
