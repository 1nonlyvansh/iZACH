// Preload for the small dedicated WebAuthn/Windows Hello ceremony window
// (see createWebAuthnGateWindow in main.cjs). Runs regardless of what origin
// the window navigates to, so it works even though the page itself is served
// over http://localhost:5050 (needed for WebAuthn's secure-context check).
const { contextBridge, ipcRenderer } = require('electron')

contextBridge.exposeInMainWorld('izachWebAuthnGate', {
  reportResult: (payload) => ipcRenderer.send('webauthn:gate-result', payload),
})
