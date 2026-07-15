// Encrypted password vault for the internal browser's Passwords manager.
// Uses Electron's safeStorage (OS-backed — DPAPI on Windows) so credentials
// are never written to disk in plain text. The vault file only ever holds
// encrypted blobs; safeStorage.decryptString() only works for the same OS
// user account that encrypted them, same guarantee Chrome/Edge rely on.
const { safeStorage, app } = require('electron')
const fs = require('fs')
const path = require('path')

const VAULT_PATH = path.join(path.dirname(path.dirname(__dirname)), 'browser_passwords.json')

function _readVault() {
  try {
    return JSON.parse(fs.readFileSync(VAULT_PATH, 'utf8'))
  } catch (e) {
    return []
  }
}

function _writeVault(entries) {
  fs.writeFileSync(VAULT_PATH, JSON.stringify(entries, null, 2), 'utf8')
}

function _encrypt(plain) {
  if (!safeStorage.isEncryptionAvailable()) {
    throw new Error('OS-level encryption is not available on this machine.')
  }
  return safeStorage.encryptString(plain).toString('base64')
}

function _decrypt(b64) {
  return safeStorage.decryptString(Buffer.from(b64, 'base64'))
}

// List entries with password masked (never send decrypted passwords to the
// renderer for a passive list view — only decrypt on an explicit "reveal"
// or "fill" action).
function list() {
  return _readVault().map(({ id, site, username, createdAt }) => ({ id, site, username, createdAt }))
}

function reveal(id) {
  const entry = _readVault().find((e) => e.id === id)
  if (!entry) throw new Error('Entry not found.')
  return _decrypt(entry.password)
}

function add({ site, username, password }) {
  if (!site || !username || !password) throw new Error('site, username, and password are all required.')
  const entries = _readVault()
  const id = 'pw' + Date.now().toString(36) + Math.random().toString(36).slice(2, 7)
  entries.push({ id, site: site.trim(), username: username.trim(), password: _encrypt(password), createdAt: new Date().toISOString() })
  _writeVault(entries)
  return { id }
}

function update(id, { site, username, password }) {
  const entries = _readVault()
  const idx = entries.findIndex((e) => e.id === id)
  if (idx === -1) throw new Error('Entry not found.')
  if (site) entries[idx].site = site.trim()
  if (username) entries[idx].username = username.trim()
  if (password) entries[idx].password = _encrypt(password)
  _writeVault(entries)
  return { ok: true }
}

function remove(id) {
  const entries = _readVault().filter((e) => e.id !== id)
  _writeVault(entries)
  return { ok: true }
}

// Google Passwords Manager CSV export columns: name,url,username,password,note
// (Chrome/Brave/Opera all export in this same shape since they're all Chromium-based).
function _parseCsvLine(line) {
  const out = []
  let cur = ''
  let inQuotes = false
  for (let i = 0; i < line.length; i++) {
    const c = line[i]
    if (inQuotes) {
      if (c === '"' && line[i + 1] === '"') { cur += '"'; i++ }
      else if (c === '"') { inQuotes = false }
      else { cur += c }
    } else {
      if (c === '"') inQuotes = true
      else if (c === ',') { out.push(cur); cur = '' }
      else cur += c
    }
  }
  out.push(cur)
  return out
}

function importCsv(csvText) {
  const lines = csvText.split(/\r?\n/).filter((l) => l.trim().length > 0)
  if (lines.length < 2) return { imported: 0, skipped: 0 }

  const header = _parseCsvLine(lines[0]).map((h) => h.trim().toLowerCase())
  const urlIdx = header.indexOf('url')
  const userIdx = header.indexOf('username')
  const passIdx = header.indexOf('password')

  if (urlIdx === -1 || userIdx === -1 || passIdx === -1) {
    throw new Error('Unrecognized CSV format — expected Google/Chrome Passwords export columns (name,url,username,password).')
  }

  const entries = _readVault()
  let imported = 0, skipped = 0
  for (let i = 1; i < lines.length; i++) {
    const cols = _parseCsvLine(lines[i])
    const url = (cols[urlIdx] || '').trim()
    const username = (cols[userIdx] || '').trim()
    const password = (cols[passIdx] || '').trim()
    if (!url || !username || !password) { skipped++; continue }
    let site = url
    try { site = new URL(url).hostname } catch (e) { /* keep raw value */ }
    const id = 'pw' + Date.now().toString(36) + Math.random().toString(36).slice(2, 7) + i
    entries.push({ id, site, username, password: _encrypt(password), createdAt: new Date().toISOString() })
    imported++
  }
  _writeVault(entries)
  return { imported, skipped }
}

module.exports = { list, reveal, add, update, remove, importCsv, encryptString: _encrypt, decryptString: _decrypt }
