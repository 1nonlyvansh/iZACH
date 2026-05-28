const { app, BrowserWindow, ipcMain } = require('electron')
const path = require('path')
const fs = require('fs')

const isDev = process.env.NODE_ENV !== 'production'

function getUIMode() {
  try {
    const settingsPath = path.join(__dirname, '../../api_keys.json')
    const data = JSON.parse(fs.readFileSync(settingsPath, 'utf8'))
    return data.ui || 'classic'
  } catch (e) {
    return 'classic'
  }
}

function createWindow() {
  const uiMode = getUIMode()
  const isSciFi = uiMode === 'scifi'

  const win = new BrowserWindow({
    width: 1440,
    height: 860,
    minWidth: 1200,
    minHeight: 700,
    frame: false,
    backgroundColor: isSciFi ? '#010814' : '#050d1a',
    webPreferences: {
      preload: path.join(__dirname, 'preload.cjs'),
      contextIsolation: true,
      nodeIntegration: false,
      webSecurity: false,
    },
    icon: path.join(__dirname, '../public/icon.png'),
    titleBarStyle: 'hidden',
  })

  if (isSciFi) {
    win.loadFile(path.join(__dirname, '../../cortex-ui.html'))
  } else if (isDev) {
    // Wait for Vite to be ready before loading
    const tryLoad = (attempts) => {
      const http = require('http')
      http.get('http://localhost:5173', (res) => {
        win.loadURL('http://localhost:5173')
      }).on('error', () => {
        if (attempts > 0) {
          setTimeout(() => tryLoad(attempts - 1), 500)
        } else {
          win.loadURL('http://localhost:5173') // last resort
        }
      })
    }
    tryLoad(20) // retry for up to 10 seconds
  } else {
    win.loadFile(path.join(__dirname, '../dist/index.html'))
  }

  // IPC window controls
  ipcMain.on('window:minimize', () => win.minimize())
  ipcMain.on('window:maximize', () => {
    if (win.isMaximized()) win.unmaximize()
    else win.maximize()
  })
  ipcMain.on('window:close', () => win.close())
}

app.whenReady().then(() => {
  createWindow()

  // Grant microphone permission for waveform visualizer
  const { session } = require('electron')
  session.defaultSession.setPermissionRequestHandler((webContents, permission, callback) => {
    if (permission === 'media' || permission === 'microphone') {
      callback(true)
    } else {
      callback(false)
    }
  })

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow()
  })
})

app.on('window-all-closed', () => {
  const { exec } = require('child_process')
  exec('taskkill /F /IM python.exe /T', () => {})
  if (process.platform !== 'darwin') app.quit()
})