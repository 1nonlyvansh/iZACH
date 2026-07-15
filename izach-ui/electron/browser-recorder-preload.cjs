// Injected into every <webview> in Cortex UI's Browser widget (see cortex-ui.html
// browserNewTab()). Captures clicks and form input while recording is armed, and
// reports each step back to the host page via ipcRenderer.sendToHost — the host
// listens on the webview's 'ipc-message' event (channel 'browser-record-event').
const { ipcRenderer } = require('electron')

let recording = false

ipcRenderer.on('browser-record-toggle', (_event, enabled) => {
  recording = !!enabled
})

function cssSelector(el) {
  if (!el || el.nodeType !== 1) return null
  if (el.id) return `#${CSS.escape(el.id)}`
  const parts = []
  let node = el
  while (node && node.nodeType === 1 && parts.length < 6) {
    let part = node.tagName.toLowerCase()
    if (node.classList && node.classList.length) {
      part += '.' + Array.from(node.classList).slice(0, 2).map((c) => CSS.escape(c)).join('.')
    }
    const parent = node.parentElement
    if (parent) {
      const siblings = Array.from(parent.children).filter((c) => c.tagName === node.tagName)
      if (siblings.length > 1) {
        part += `:nth-of-type(${siblings.indexOf(node) + 1})`
      }
    }
    parts.unshift(part)
    node = parent
  }
  return parts.join(' > ')
}

document.addEventListener('click', (e) => {
  if (!recording) return
  const selector = cssSelector(e.target)
  if (!selector) return
  ipcRenderer.sendToHost('browser-record-event', {
    type: 'click',
    selector,
    text: (e.target.innerText || '').slice(0, 40),
  })
}, true)

document.addEventListener('change', (e) => {
  if (!recording) return
  const el = e.target
  if (!el || !('value' in el)) return
  const selector = cssSelector(el)
  if (!selector) return
  // Password fields ARE captured now (the user wants login flows replayable)
  // but flagged `sensitive` — the host encrypts this value with safeStorage
  // before it's ever written to browser_recordings/*.json, and this preload
  // never persists it itself.
  ipcRenderer.sendToHost('browser-record-event', {
    type: 'fill',
    selector,
    value: el.value,
    sensitive: el.type === 'password',
  })
}, true)
