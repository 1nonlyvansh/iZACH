const { contextBridge, ipcRenderer } = require('electron')

contextBridge.exposeInMainWorld('electronAPI', {
  minimize: () => ipcRenderer.send('window:minimize'),
  maximize: () => ipcRenderer.send('window:maximize'),
  close:    () => ipcRenderer.send('window:close'),
  openBrowserWindow: (url, playback) => ipcRenderer.send('browser:open-window', url, playback || null),
  clearBrowserCache: () => ipcRenderer.invoke('browser:clear-cache'),
  platform: process.platform,
})

contextBridge.exposeInMainWorld('izachPasswords', {
  list:       () => ipcRenderer.invoke('passwords:list'),
  reveal:     (id) => ipcRenderer.invoke('passwords:reveal', id),
  add:        (entry) => ipcRenderer.invoke('passwords:add', entry),
  update:     (id, entry) => ipcRenderer.invoke('passwords:update', id, entry),
  remove:     (id) => ipcRenderer.invoke('passwords:remove', id),
  importCsv:  (csvText) => ipcRenderer.invoke('passwords:import-csv', csvText),
  autofillReveal: (id) => ipcRenderer.invoke('passwords:autofill-reveal', id),
})

contextBridge.exposeInMainWorld('izachWebAuthn', {
  isEnrolled: () => ipcRenderer.invoke('webauthn:is-enrolled'),
  enroll:     () => ipcRenderer.invoke('webauthn:enroll'),
  verify:     () => ipcRenderer.invoke('webauthn:verify'),
})

contextBridge.exposeInMainWorld('izachPermissions', {
  list:   () => ipcRenderer.invoke('permissions:list'),
  revoke: (origin, permission) => ipcRenderer.invoke('permissions:revoke', origin, permission),
})

contextBridge.exposeInMainWorld('izachDownloads', {
  list:         () => ipcRenderer.invoke('downloads:list'),
  clear:        () => ipcRenderer.invoke('downloads:clear'),
  open:         (filePath) => ipcRenderer.invoke('downloads:open', filePath),
  showInFolder: (filePath) => ipcRenderer.invoke('downloads:show-in-folder', filePath),
})

contextBridge.exposeInMainWorld('izachRecordings', {
  encrypt: (plain) => ipcRenderer.invoke('recordings:encrypt', plain),
  decrypt: (cipher) => ipcRenderer.invoke('recordings:decrypt', cipher),
})

// A guest <webview> page's window.open()/target="_blank" request was denied
// in main.cjs (setWindowOpenHandler) and forwarded here — re-dispatched as a
// plain DOM event so the page (cortex-ui.html / browser-window.html) can open
// it as a new tab, same as clicking such a link does in Chrome or Brave.
// contextIsolation blocks sharing JS objects with the page, but the DOM
// itself is shared, so a CustomEvent on window crosses that boundary fine.
ipcRenderer.on('webview:new-window', (_event, payload) => {
  window.dispatchEvent(new CustomEvent('izach-new-window', { detail: payload }))
})
