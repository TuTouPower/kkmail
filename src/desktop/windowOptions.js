'use strict'

function windowBackgroundColor(shouldUseDarkColors) {
  return shouldUseDarkColors ? '#16191A' : '#E9EAED'
}

/**
 * A278: Electron's default application menu must not ship in packaged
 * (production) builds — it keeps user-facing DevTools / reload entries.
 * The main process removes it via Menu.setApplicationMenu(null) when
 * this returns true; unpackaged dev runs keep the default menu (and
 * its DevTools access). Anything other than an explicit packaged flag
 * is treated as dev, so a missing flag can never strip the menu.
 */
function shouldRemoveApplicationMenu({ isPackaged } = {}) {
  return isPackaged === true
}

function createMainWindowOptions({ platform, preloadPath, iconPath, backgroundColor }) {
  const options = {
    show: false,
    width: 1280,
    height: 840,
    minWidth: 900,
    minHeight: 600,
    title: 'kkmail',
    backgroundColor,
    icon: iconPath,
    webPreferences: {
      preload: preloadPath,
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      webviewTag: false,
    },
  }

  if (platform === 'darwin') {
    options.titleBarStyle = 'hidden'
    options.trafficLightPosition = { x: 16, y: 13 }
  }

  return options
}

module.exports = { createMainWindowOptions, windowBackgroundColor, shouldRemoveApplicationMenu }
