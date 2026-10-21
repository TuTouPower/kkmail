/**
 * Preload: expose only the minimum surface. No nodeIntegration.
 */
const { contextBridge } = require('electron')

contextBridge.exposeInMainWorld('kkmailDesktop', {
  platform: process.platform,
  versions: {
    electron: process.versions.electron,
    chrome: process.versions.chrome,
  },
})
