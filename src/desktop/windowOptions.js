'use strict'

function windowBackgroundColor(shouldUseDarkColors) {
  return shouldUseDarkColors ? '#171819' : '#E9EAED'
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

module.exports = { createMainWindowOptions, windowBackgroundColor }
