const { app, BrowserWindow, ipcMain, session, shell } = require('electron')
const path = require('path')
const fs = require('fs')
const AD_BLOCK_DOMAINS = require('./adblock-list.cjs')
const passwordStore = require('./password-store.cjs')

// Session partition used ONLY by the in-app Browser widget's <webview> tags —
// keeps ad/tracker blocking scoped away from iZACH's own backend/API traffic,
// which runs in the default session.
const BROWSER_PARTITION = 'persist:izach-browser'

function installBrowserAdBlock() {
  const browserSession = session.fromPartition(BROWSER_PARTITION)
  browserSession.webRequest.onBeforeRequest((details, callback) => {
    const host = (() => {
      try { return new URL(details.url).hostname } catch (e) { return '' }
    })()
    const blocked = host && AD_BLOCK_DOMAINS.some(
      (d) => host === d || host.endsWith('.' + d)
    )
    callback({ cancel: !!blocked })
  })
}

function installBrowserIpc() {
  ipcMain.handle('browser:clear-cache', async () => {
    const s = session.fromPartition(BROWSER_PARTITION)
    await s.clearCache()
    await s.clearStorageData({ storages: ['cachestorage', 'shadercache', 'serviceworkers'] })
    return { ok: true }
  })

  ipcMain.handle('passwords:list', () => passwordStore.list())
  ipcMain.handle('passwords:reveal', (event, id) => passwordStore.reveal(id))
  ipcMain.handle('passwords:add', (event, entry) => passwordStore.add(entry))
  ipcMain.handle('passwords:update', (event, id, entry) => passwordStore.update(id, entry))
  ipcMain.handle('passwords:remove', (event, id) => passwordStore.remove(id))
  ipcMain.handle('passwords:import-csv', (event, csvText) => passwordStore.importCsv(csvText))

  // Autofill never calls passwordStore.reveal() directly from the renderer —
  // it always re-verifies Windows Hello first, right here in main, so a
  // compromised or buggy renderer can't skip the consent prompt.
  ipcMain.handle('passwords:autofill-reveal', async (event, id) => {
    const enrollment = _readWebAuthnEnrollment()
    if (!enrollment) return { ok: false, error: 'not_enrolled' }
    const verify = await _runWebAuthnCeremony('verify', { credential_id: enrollment.credentialId })
    if (!verify.ok) return { ok: false, error: verify.error || 'verification_failed' }
    try {
      const entry = passwordStore.list().find((e) => e.id === id)
      if (!entry) return { ok: false, error: 'not_found' }
      const password = passwordStore.reveal(id)
      return { ok: true, username: entry.username, password }
    } catch (e) {
      return { ok: false, error: e.message }
    }
  })

  ipcMain.handle('permissions:list', () => _readPermissions())
  ipcMain.handle('permissions:revoke', (event, origin, permission) => {
    const list = _readPermissions().filter((p) => !(p.origin === origin && p.permission === permission))
    _writePermissions(list)
    return { ok: true }
  })

  // Recording step values flagged "sensitive" (e.g. a typed password) are
  // encrypted here with the same OS-backed safeStorage used by the password
  // vault before the renderer ever writes them to browser_recordings/*.json —
  // decrypted again only on an explicit reveal, or right before replay.
  ipcMain.handle('recordings:encrypt', (event, plain) => passwordStore.encryptString(plain))
  ipcMain.handle('recordings:decrypt', (event, cipher) => passwordStore.decryptString(cipher))

  ipcMain.handle('downloads:list', () => _readDownloads())
  ipcMain.handle('downloads:clear', () => { _writeDownloads([]); return { ok: true } })
  ipcMain.handle('downloads:open', (event, filePath) => {
    const err = shell.openPath(filePath)
    return { ok: !err, error: err || null }
  })
  ipcMain.handle('downloads:show-in-folder', (event, filePath) => {
    shell.showItemInFolder(filePath)
    return { ok: true }
  })
}

// ── Per-site permissions (camera/mic/geolocation) for the Browser widget ──────
// Electron auto-grants every permission request by default unless a handler is
// installed — for a general-purpose browsing surface that's too permissive, so
// this defaults sensitive permissions to deny-until-explicitly-allowed and logs
// every decision so Settings → Browser Settings can show/revoke them per site.
const PERMISSIONS_FILE = path.join(path.dirname(path.dirname(__dirname)), 'browser_permissions.json')
const SENSITIVE_PERMISSIONS = ['media', 'camera', 'microphone', 'geolocation']

function _readPermissions() {
  try { return JSON.parse(fs.readFileSync(PERMISSIONS_FILE, 'utf8')) } catch (e) { return [] }
}
function _writePermissions(list) {
  fs.writeFileSync(PERMISSIONS_FILE, JSON.stringify(list, null, 2), 'utf8')
}
function _originOf(urlLike) {
  try { return new URL(urlLike).hostname } catch (e) { return String(urlLike || 'unknown') }
}

function installBrowserPermissions() {
  const browserSession = session.fromPartition(BROWSER_PARTITION)

  browserSession.setPermissionRequestHandler((webContents, permission, callback, details) => {
    const origin = _originOf(details.requestingUrl || (webContents.getURL && webContents.getURL()))
    const list = _readPermissions()
    const existing = list.find((p) => p.origin === origin && p.permission === permission)
    let granted
    if (existing) {
      granted = existing.status === 'granted'
    } else {
      granted = !SENSITIVE_PERMISSIONS.includes(permission)
      list.push({ origin, permission, status: granted ? 'granted' : 'denied', ts: new Date().toISOString() })
      _writePermissions(list)
    }
    callback(granted)
  })

  browserSession.setPermissionCheckHandler((webContents, permission, requestingOrigin) => {
    const origin = _originOf(requestingOrigin)
    const existing = _readPermissions().find((p) => p.origin === origin && p.permission === permission)
    if (existing) return existing.status === 'granted'
    return !SENSITIVE_PERMISSIONS.includes(permission)
  })
}

// ── Downloads (Browser widget) ─────────────────────────────────────────────
const DOWNLOADS_FILE = path.join(path.dirname(path.dirname(__dirname)), 'browser_downloads.json')
const DOWNLOADS_MAX_ENTRIES = 500

function _readDownloads() {
  try { return JSON.parse(fs.readFileSync(DOWNLOADS_FILE, 'utf8')) } catch (e) { return [] }
}
function _writeDownloads(list) {
  fs.writeFileSync(DOWNLOADS_FILE, JSON.stringify(list.slice(-DOWNLOADS_MAX_ENTRIES), null, 2), 'utf8')
}
function _upsertDownload(entry) {
  const list = _readDownloads()
  const idx = list.findIndex((d) => d.id === entry.id)
  if (idx >= 0) list[idx] = { ...list[idx], ...entry }
  else list.push(entry)
  _writeDownloads(list)
}

function installBrowserDownloads() {
  const browserSession = session.fromPartition(BROWSER_PARTITION)
  browserSession.on('will-download', (event, item) => {
    const id = 'dl' + Date.now().toString(36) + Math.random().toString(36).slice(2, 7)
    const downloadsDir = app.getPath('downloads')
    let savePath = path.join(downloadsDir, item.getFilename())
    let n = 1
    while (fs.existsSync(savePath)) {
      const ext = path.extname(item.getFilename())
      const base = path.basename(item.getFilename(), ext)
      savePath = path.join(downloadsDir, `${base} (${n})${ext}`)
      n++
    }
    item.setSavePath(savePath)

    _upsertDownload({
      id, filename: path.basename(savePath), path: savePath, url: item.getURL(),
      state: 'progressing', receivedBytes: 0, totalBytes: item.getTotalBytes(),
      startedAt: new Date().toISOString(),
    })

    item.on('updated', (e, state) => {
      _upsertDownload({ id, state, receivedBytes: item.getReceivedBytes(), totalBytes: item.getTotalBytes() })
    })
    item.once('done', (e, state) => {
      _upsertDownload({ id, state, receivedBytes: item.getReceivedBytes(), totalBytes: item.getTotalBytes() })
    })
  })
}

// ── WebAuthn/Windows Hello consent gate (password autofill) ─────────────────
// Stores only the public credential ID from one local platform-authenticator
// enrollment — never a secret, so this file is safe even if read by anything
// else on the machine. The actual password vault stays encrypted separately
// (password-store.cjs); this just gates WHEN we're allowed to decrypt it.
const WEBAUTHN_FILE = path.join(path.dirname(path.dirname(__dirname)), 'browser_webauthn.json')
const WEBAUTHN_GATE_URL = 'http://localhost:5050/browser/webauthn-gate'

function _readWebAuthnEnrollment() {
  try { return JSON.parse(fs.readFileSync(WEBAUTHN_FILE, 'utf8')) } catch (e) { return null }
}
function _writeWebAuthnEnrollment(data) {
  fs.writeFileSync(WEBAUTHN_FILE, JSON.stringify(data, null, 2), 'utf8')
}

// Opens the small ceremony window, waits for the page's single reported
// result, and always closes the window afterward (success, failure, or the
// user just closing it manually, which resolves as a cancellation).
function _runWebAuthnCeremony(mode, extraQuery) {
  return new Promise((resolve) => {
    // platform lets the gate page (served by the Python backend, which has
    // no way to know what OS the Electron client is on) show "Touch ID" on
    // macOS instead of always saying "Windows Hello".
    const query = new URLSearchParams({ mode, platform: process.platform, ...extraQuery }).toString()
    const gateWin = new BrowserWindow({
      width: 420,
      height: 320,
      resizable: false,
      minimizable: false,
      maximizable: false,
      frame: false,
      backgroundColor: '#050d1a',
      webPreferences: {
        preload: path.join(__dirname, 'webauthn-gate-preload.cjs'),
        contextIsolation: true,
        nodeIntegration: false,
      },
    })

    let settled = false
    const finish = (result) => {
      if (settled) return
      settled = true
      resolve(result)
      if (!gateWin.isDestroyed()) gateWin.close()
    }

    ipcMain.once('webauthn:gate-result', (_event, payload) => finish(payload || { ok: false, error: 'no result' }))
    gateWin.on('closed', () => finish({ ok: false, error: 'cancelled' }))
    gateWin.loadURL(`${WEBAUTHN_GATE_URL}?${query}`)
  })
}

function installWebAuthnIpc() {
  ipcMain.handle('webauthn:is-enrolled', () => !!_readWebAuthnEnrollment())

  ipcMain.handle('webauthn:enroll', async () => {
    const result = await _runWebAuthnCeremony('register', {})
    if (result.ok && result.credentialId) {
      _writeWebAuthnEnrollment({ credentialId: result.credentialId, enrolledAt: new Date().toISOString() })
    }
    return result
  })

  ipcMain.handle('webauthn:verify', async () => {
    const enrollment = _readWebAuthnEnrollment()
    if (!enrollment) return { ok: false, error: 'not enrolled' }
    return _runWebAuthnCeremony('verify', { credential_id: enrollment.credentialId })
  })
}

const isDev = process.env.NODE_ENV !== 'production'

// When packaged, __dirname lives inside the app bundle's Resources — the live
// iZACH project (main.py, cortex-ui.html, api_keys.json) is a separate
// location on disk that isn't shipped inside the bundle, so the UI/settings
// stay editable in place without a rebuild. IZACH_PROJECT_ROOT (set by
// launch_izach.py when spawning the packaged app) points here; falls back to
// the existing __dirname-relative resolution for dev mode (`electron .`
// running directly inside the live project tree).
const PROJECT_ROOT = process.env.IZACH_PROJECT_ROOT || path.join(__dirname, '../..')

// Chrome-/Brave-like right-click menu for a <webview> guest page. Electron
// ships no default context menu at all for webContents — without this,
// right-clicking a page in iZACH's browser did nothing.
function _buildGuestContextMenu(guestWebContents, params, win) {
  const { Menu, clipboard } = require('electron')
  const items = []

  if (params.linkURL) {
    items.push({
      label: 'Open Link in New Tab',
      click: () => { if (!win.isDestroyed()) win.webContents.send('webview:new-window', { url: params.linkURL, disposition: 'background-tab' }) },
    })
    items.push({ label: 'Copy Link Address', click: () => clipboard.writeText(params.linkURL) })
    items.push({ type: 'separator' })
  }

  if (params.mediaType === 'image' && params.srcURL) {
    items.push({ label: 'Save Image As…', click: () => guestWebContents.downloadURL(params.srcURL) })
    items.push({ label: 'Copy Image URL', click: () => clipboard.writeText(params.srcURL) })
    items.push({ type: 'separator' })
  }

  if (params.isEditable) {
    items.push({ label: 'Cut', enabled: params.editFlags.canCut, click: () => guestWebContents.cut() })
    items.push({ label: 'Copy', enabled: params.editFlags.canCopy, click: () => guestWebContents.copy() })
    items.push({ label: 'Paste', enabled: params.editFlags.canPaste, click: () => guestWebContents.paste() })
    items.push({ label: 'Select All', enabled: params.editFlags.canSelectAll, click: () => guestWebContents.selectAll() })
    items.push({ type: 'separator' })
  } else if (params.selectionText) {
    items.push({ label: 'Copy', click: () => clipboard.writeText(params.selectionText) })
    items.push({ type: 'separator' })
  }

  items.push({ label: 'Back', enabled: guestWebContents.canGoBack(), click: () => guestWebContents.goBack() })
  items.push({ label: 'Forward', enabled: guestWebContents.canGoForward(), click: () => guestWebContents.goForward() })
  items.push({ label: 'Reload', click: () => guestWebContents.reload() })
  items.push({ type: 'separator' })
  items.push({ label: 'Inspect Element', click: () => guestWebContents.inspectElement(params.x, params.y) })

  return Menu.buildFromTemplate(items)
}

// Every other browser opens target="_blank" links / window.open() calls in a
// new tab. Electron's <webview> denies that request by default unless a
// handler is installed on the GUEST's webContents — with none installed, the
// request (and anything gated behind a page's own "you're being redirected,
// OK?" confirm dialog) was just silently dropped after the user clicked OK.
// did-attach-webview fires once per <webview> the HOST window creates, so
// hooking it here covers every tab in both the embedded panel and the
// standalone iZACH Browser window.
function installWebviewGuestHandlers(win) {
  win.webContents.on('did-attach-webview', (_event, guestWebContents) => {
    guestWebContents.setWindowOpenHandler(({ url, disposition }) => {
      if (!win.isDestroyed()) {
        win.webContents.send('webview:new-window', { url, disposition })
      }
      return { action: 'deny' }
    })

    guestWebContents.on('context-menu', (_e, params) => {
      _buildGuestContextMenu(guestWebContents, params, win).popup({ window: win })
    })
  })
}

function getUIMode() {
  // macOS has no Forge UI ('classic') and no Background Mode — force
  // 'scifi' regardless of what's on disk, so a stale pre-upgrade config (or
  // a value written on Windows and synced over) can never put a Mac install
  // into a mode it doesn't support.
  if (process.platform === 'darwin') return 'scifi'
  try {
    const settingsPath = path.join(PROJECT_ROOT, 'api_keys.json')
    const data = JSON.parse(fs.readFileSync(settingsPath, 'utf8'))
    return data.ui || 'classic'
  } catch (e) {
    return 'classic'
  }
}

function createWindow() {
  const uiMode = getUIMode()

  // Background mode: no window. If Electron is launched anyway (e.g. stale
  // shortcut), quit without opening a window — and WITHOUT the python taskkill
  // in window-all-closed, since the backend must keep running headless.
  if (uiMode === 'background') {
    console.log('[iZACH] Background mode — no UI window. Quitting Electron.')
    app.exit(0)
    return
  }

  const isSciFi = uiMode === 'scifi'

  // macOS: keep the real native traffic lights (titleBarStyle 'hidden' alone,
  // no frame:false) instead of drawing our own — frame:false suppresses ALL
  // native chrome including those, which is why the custom Windows-style
  // (—/□/✕, top-right) bar in cortex-ui.html was showing up as the ONLY
  // window controls on Mac too. Windows keeps frame:false + the custom bar,
  // matching that platform's own convention of apps drawing their own chrome.
  const win = new BrowserWindow({
    width: 1440,
    height: 860,
    minWidth: 1200,
    minHeight: 700,
    ...(process.platform === 'darwin'
      ? { titleBarStyle: 'hidden', trafficLightPosition: { x: 14, y: 14 } }
      : { frame: false }),
    backgroundColor: isSciFi ? '#010814' : '#050d1a',
    webPreferences: {
      preload: path.join(__dirname, 'preload.cjs'),
      contextIsolation: true,
      nodeIntegration: false,
      webSecurity: false,
      webviewTag: true,
    },
    icon: path.join(__dirname, '../public/icon.png'),
    titleBarStyle: 'hidden',
  })
  installWebviewGuestHandlers(win)

  if (isSciFi) {
    win.loadFile(path.join(PROJECT_ROOT, 'cortex-ui.html'))
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
}

// Standalone "iZACH Browser" window — opened from Cortex UI's Browser widget
// via the "Open in iZACH Browser" button, continuing from whatever URL was
// active there. Shares the same 'persist:izach-browser' session partition as
// the embedded panel, so cookies/logins/ad-block rules carry over.
function createBrowserWindow(startUrl, playback) {
  const win = new BrowserWindow({
    width: 1280,
    height: 820,
    minWidth: 800,
    minHeight: 600,
    ...(process.platform === 'darwin'
      ? { titleBarStyle: 'hidden', trafficLightPosition: { x: 14, y: 14 } }
      : { frame: false }),
    backgroundColor: '#010814',
    webPreferences: {
      preload: path.join(__dirname, 'preload.cjs'),
      contextIsolation: true,
      nodeIntegration: false,
      webSecurity: false,
      webviewTag: true,
    },
    icon: path.join(__dirname, '../public/icon.png'),
    title: 'iZACH Browser',
  })
  installWebviewGuestHandlers(win)
  const query = startUrl ? { url: startUrl } : {}
  // Resume playback from the docked panel's tab, if any was captured.
  if (playback && typeof playback.t === 'number') {
    query.t = String(playback.t)
    query.paused = playback.paused ? '1' : '0'
  }
  win.loadFile(path.join(__dirname, 'browser-window.html'), { query })
}

app.whenReady().then(() => {
  createWindow()
  installBrowserAdBlock()
  installBrowserIpc()
  installBrowserPermissions()
  installBrowserDownloads()
  installWebAuthnIpc()

  // IPC window controls — resolved from the sender so minimize/maximize/close
  // act on whichever window (main or a standalone browser window) sent it,
  // rather than always targeting the first window created.
  ipcMain.on('window:minimize', (event) => {
    const w = BrowserWindow.fromWebContents(event.sender)
    if (w) w.minimize()
  })
  ipcMain.on('window:maximize', (event) => {
    const w = BrowserWindow.fromWebContents(event.sender)
    if (w) { if (w.isMaximized()) w.unmaximize(); else w.maximize() }
  })
  ipcMain.on('window:close', (event) => {
    const w = BrowserWindow.fromWebContents(event.sender)
    if (w) w.close()
  })
  ipcMain.on('browser:open-window', (event, url, playback) => createBrowserWindow(url, playback))

  // Grant microphone permission for waveform visualizer
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
  // If the user switched to Background Mode, keep the Python backend (and its
  // tray icon) running — only quit the Electron window.
  if (getUIMode() === 'background') {
    if (process.platform !== 'darwin') app.quit()
    return
  }
  const { exec } = require('child_process')
  if (process.platform === 'win32') {
    // 'taskkill /F /IM python.exe /T' matches by image name only — it kills
    // EVERY python.exe running on the machine, not just iZACH's own backend
    // (any other Python app/venv/IDE process the user has open dies too).
    // Filter by command line instead, same specificity as the Mac branch's
    // pkill -f below (matches main.py's exact path, not just the exe name).
    // NOTE: no backslash-doubling here — unlike a regex or a POSIX shell
    // pattern, PowerShell's -like operator has no escape character, so \ is
    // just a literal path separator. Doubling it (as an earlier version of
    // this fix did) makes the pattern require \\ where Win32_Process's real
    // CommandLine only ever has \, so it silently matched nothing — verified
    // by testing both forms against real backend processes.
    const backendMainWin = path.join(PROJECT_ROOT, 'main.py')
    const psKill = `Get-CimInstance Win32_Process -Filter "Name='python.exe'" | ` +
      `Where-Object { $_.CommandLine -like '*${backendMainWin}*' } | ` +
      `ForEach-Object { Stop-Process -Id $_.ProcessId -Force }`
    exec(`powershell -NoProfile -Command "${psKill}"`, () => {})
  } else if (process.platform === 'darwin') {
    // main.cjs doesn't spawn these services itself (launch_izach.py does, each
    // in its own Terminal window), so there are no child PIDs to track directly
    // here — pkill -f matches each one's full command line, specific enough to
    // avoid catching unrelated processes on the same machine. Closing the UI is
    // meant to take the whole iZACH stack offline, not just the Electron window,
    // so every service launch_izach.py started gets torn down here too.
    const backendMain = path.join(PROJECT_ROOT, 'main.py')
    const waBridge = path.join(PROJECT_ROOT, 'whatsapp_bridge.js')
    exec(`pkill -f "${backendMain}"`, () => {})
    exec(`pkill -f "${waBridge}"`, () => {})
    exec('pkill -f "bin/n8n"', () => {})
    exec('pkill -f "ngrok http"', () => {})
  }
  // Mac apps conventionally stay running (in the dock) after the last window
  // closes — deliberately overridden here since the user wants closing the UI
  // to mean iZACH is fully offline, not idling in the background.
  app.quit()
})