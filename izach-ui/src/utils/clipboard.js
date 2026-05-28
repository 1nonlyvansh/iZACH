// Universal copy-to-clipboard helper that works in Electron AND web contexts.
//
// navigator.clipboard.writeText() only works in:
//   - HTTPS pages
//   - localhost
//   - Electron renderers WITH the right contextIsolation + permissions config
//
// In iZACH's Electron build it silently failed because no permission handler
// was wired. This helper tries every available API in order until one succeeds.
export async function copyToClipboard(text) {
  if (text == null) return false
  const str = String(text)

  // 1. Electron preload — most reliable if available
  try {
    if (window.electronAPI?.clipboardWrite) {
      window.electronAPI.clipboardWrite(str)
      return true
    }
  } catch {}

  // 2. Standard clipboard API
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(str)
      return true
    }
  } catch {}

  // 3. Legacy execCommand fallback — works without permissions
  try {
    const ta = document.createElement('textarea')
    ta.value = str
    ta.style.position = 'fixed'
    ta.style.opacity = '0'
    ta.style.left = '-9999px'
    document.body.appendChild(ta)
    ta.focus()
    ta.select()
    const ok = document.execCommand('copy')
    document.body.removeChild(ta)
    return ok
  } catch {}

  return false
}
