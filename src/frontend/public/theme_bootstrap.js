(() => {
  // The no-stored-preference default must stay 'system': the zustand store
  // in src/frontend/src/store/mailStore.ts uses the same default (A94). If
  // the two drift apart, the first paint and the mounted app disagree and
  // the theme visibly flips.
  let preference = 'system'
  try {
    const stored = JSON.parse(localStorage.getItem('mail-ui-storage') || 'null')
    const theme = stored?.state?.theme
    if (theme === 'dark' || theme === 'light' || theme === 'system') preference = theme
  } catch {
    // Storage can be disabled; follow the operating system preference.
  }

  const systemTheme = typeof window.matchMedia === 'function'
    ? (window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light')
    : 'dark'
  document.documentElement.dataset.theme = preference === 'system' ? systemTheme : preference
})()
