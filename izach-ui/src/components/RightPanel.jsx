import React, { useState, useEffect } from 'react'
import QRCode from 'qrcode'

function SectionHeader({ label }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '10px 16px 8px' }}>
      <span style={{ color: '#00e5ff' }}>*</span>
      <span style={{ color: '#00e5ff', fontFamily: "'Share Tech Mono'", fontSize: '10px', letterSpacing: '0.2em' }}>
        {label}
      </span>
      <div style={{ flex: 1, height: 1, background: '#0d2a3a' }} />
    </div>
  )
}

function Divider() {
  return <div style={{ height: 1, margin: '0 16px', background: '#0d2a3a' }} />
}

// ── Spotify ───────────────────────────────────────────────────
const BASE = 'http://localhost:5050'

async function spotifyAction(action) {
  try {
    await fetch(`${BASE}/spotify/control`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ action }),
    })
  } catch {}
}

function SpotifyPanel({ track }) {
  const {
    playing, title, artist, device,
    albumArt, progress, duration, volume,
  } = track

  const pct = duration > 0 ? (progress / duration) * 100 : 0

  return (
    <div>
      <SectionHeader label="SPOTIFY" />
      <div style={{ padding: '0 16px 12px' }}>

        {/* Track info */}
        <div style={{ display: 'flex', gap: 10, marginBottom: 10 }}>
          {/* Album art or placeholder */}
          <div style={{
            width: 38, height: 38, flexShrink: 0,
            borderRadius: 4, overflow: 'hidden',
            background: '#0d2a3a',
            border: '1px solid #1a4a5a',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
          }}>
            {albumArt
              ? <img src={albumArt} alt="art" style={{ width: '100%', height: '100%', objectFit: 'cover' }} />
              : (
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none">
                  <circle cx="12" cy="12" r="10" fill={playing ? '#1db954' : '#1a4a5a'} />
                  <polygon points="10,8 16,12 10,16" fill="#050d1a" />
                </svg>
              )
            }
          </div>

          <div style={{ overflow: 'hidden', flex: 1 }}>
            <p style={{
              color: playing ? '#c8e8f0' : '#3a6070',
              fontFamily: "'JetBrains Mono'", fontSize: '10px',
              whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis',
              marginBottom: 2,
            }}>
              {title}
            </p>
            <p style={{
              color: '#3a6070', fontFamily: "'JetBrains Mono'", fontSize: '9px',
              whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis',
            }}>
              {artist}
            </p>
          </div>
        </div>

        {/* Progress bar */}
        <div style={{ marginBottom: 8 }}>
          <div style={{ height: 2, background: '#0d2a3a', borderRadius: 1, overflow: 'hidden' }}>
            <div style={{
              height: '100%', width: `${pct}%`,
              background: playing ? '#1db954' : '#1a4a5a',
              boxShadow: playing ? '0 0 4px #1db95466' : 'none',
              borderRadius: 1,
              transition: 'width 1s linear',
            }} />
          </div>
        </div>

        {/* Device + volume */}
        <div style={{ marginBottom: 8 }}>
          <p style={{ color: '#1a4a5a', fontFamily: "'Share Tech Mono'", fontSize: '8px', letterSpacing: '0.12em', marginBottom: 3 }}>
            DEVICE
          </p>
          <p style={{ color: '#3a6070', fontFamily: "'JetBrains Mono'", fontSize: '9px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
            {device}
          </p>
        </div>

        {/* Volume bar */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <span style={{ color: '#1a4a5a', fontSize: '9px' }}>◁</span>
          <div style={{ flex: 1, height: 2, background: '#0d2a3a', borderRadius: 1 }}>
            <div style={{
              height: '100%', width: `${volume}%`,
              background: 'linear-gradient(90deg, #005060, #00e5ff)',
              borderRadius: 1,
              transition: 'width 0.5s ease',
            }} />
          </div>
          <span style={{ color: '#3a6070', fontFamily: "'Share Tech Mono'", fontSize: '9px' }}>
            {volume}%
          </span>
        </div>

        {/* Playback controls */}
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 8, marginTop: 8 }}>
          {[
            { label: '⏮', action: 'prev' },
            { label: playing ? '⏸' : '▶', action: 'playpause' },
            { label: '⏭', action: 'next' },
          ].map(btn => (
            <button
              key={btn.action}
              onClick={() => spotifyAction(btn.action)}
              style={{
                background: 'rgba(0,229,255,0.06)',
                border: '1px solid #0d2a3a',
                borderRadius: 4,
                color: '#00e5ff',
                fontFamily: "'Share Tech Mono'",
                fontSize: '13px',
                width: 32, height: 28,
                cursor: 'pointer',
                display: 'flex', alignItems: 'center', justifyContent: 'center',
              }}
            >
              {btn.label}
            </button>
          ))}
        </div>

        {/* Not playing notice */}
        {!playing && (
          <p style={{ color: '#1a4a5a', fontFamily: "'Share Tech Mono'", fontSize: '9px', letterSpacing: '0.1em', marginTop: 8 }}>
            NOTHING PLAYING
          </p>
        )}
      </div>
    </div>
  )
}
  


// ── Status dot ────────────────────────────────────────────────
function StatusDot({ status }) {
  return (
    <span
      className={status === 'online' ? 'status-online' : 'status-offline'}
      style={{
        display: 'inline-block', width: 7, height: 7,
        borderRadius: '50%',
        background: status === 'online' ? '#1db954' : '#ff3d3d',
        flexShrink: 0,
      }}
    />
  )
}

function StatusPanel({ label, status, detail }) {
  return (
    <div>
      <SectionHeader label={label} />
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '0 16px 12px' }}>
        <StatusDot status={status} />
        <span style={{
          color: status === 'online' ? '#1db954' : '#ff3d3d',
          fontFamily: "'Share Tech Mono'", fontSize: '10px',
          letterSpacing: '0.2em', textTransform: 'uppercase',
        }}>
          {status}
        </span>
        {detail && (
          <span style={{ color: '#1a4a5a', fontFamily: "'JetBrains Mono'", fontSize: '9px', marginLeft: 2 }}>
            {detail}
          </span>
        )}
      </div>
    </div>
  )
}

function NotificationsPanel({ notifications }) {
  return (
    <div>
      <SectionHeader label="NOTIFICATIONS" />
      <div style={{ padding: '0 16px 12px' }}>
        {(!notifications || notifications.length === 0) ? (
          <p style={{ color: '#1a4a5a', fontFamily: "'JetBrains Mono'", fontSize: '9px' }}>No notifications</p>
        ) : notifications.map((n, i) => (
          <div key={i} style={{
            marginBottom: 6, padding: '5px 8px',
            background: 'rgba(0,229,255,0.04)',
            border: '1px solid #0d2a3a', borderRadius: 3,
          }}>
            <p style={{ color: '#c8e8f0', fontFamily: "'JetBrains Mono'", fontSize: '9px', marginBottom: 2 }}>
              {typeof n === 'object' ? n.text : n}
            </p>
            {typeof n === 'object' && n.ts && (
              <p style={{ color: '#1a4a5a', fontFamily: "'Share Tech Mono'", fontSize: '8px' }}>{n.ts}</p>
            )}
          </div>
        ))}
      </div>
    </div>
  )
}

function SystemLog({ errors }) {
  return (
    <div>
      <SectionHeader label="SYSTEM LOG" />
      <div style={{ padding: '0 16px 12px' }}>
        {(!errors || errors.length === 0) ? (
          <p style={{ color: '#1a4a5a', fontFamily: "'JetBrains Mono'", fontSize: '9px' }}>No errors</p>
        ) : errors.map((e, i) => (
          <p key={i} style={{ color: '#ff3d3d', fontFamily: "'JetBrains Mono'", fontSize: '9px', marginBottom: 3, wordBreak: 'break-word' }}>
            {e}
          </p>
        ))}
      </div>
    </div>
  )
}

function WhatsAppPanel({ status, qr }) {
  const [qrDataUrl, setQrDataUrl] = useState(null)

  useEffect(() => {
    if (qr) {
      QRCode.toDataURL(qr, { width: 188, margin: 1, color: { dark: '#c8e8f0', light: '#050d1a' } })
        .then(url => setQrDataUrl(url))
        .catch(() => setQrDataUrl(null))
    } else {
      setQrDataUrl(null)
    }
  }, [qr])

  return (
    <div>
      <SectionHeader label="WHATSAPP BRIDGE" />
      <div style={{ padding: '0 16px 12px' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: qrDataUrl ? 10 : 0 }}>
          <StatusDot status={status} />
          <span style={{
            color: status === 'online' ? '#1db954' : '#ff3d3d',
            fontFamily: "'Share Tech Mono'", fontSize: '10px',
            letterSpacing: '0.2em', textTransform: 'uppercase',
          }}>
            {status}
          </span>
          {status === 'online' && (
            <span style={{ color: '#1a4a5a', fontFamily: "'JetBrains Mono'", fontSize: '9px', marginLeft: 2 }}>
              Connected
            </span>
          )}
        </div>
        {qrDataUrl && status === 'offline' && (
          <div>
            <p style={{ color: '#3a6070', fontFamily: "'Share Tech Mono'", fontSize: '8px', letterSpacing: '0.12em', marginBottom: 6 }}>
              SCAN TO CONNECT
            </p>
            <img src={qrDataUrl} alt="WhatsApp QR" style={{ width: '100%', borderRadius: 4, display: 'block' }} />
          </div>
        )}
      </div>
    </div>
  )
}

function MmaPanel({ mmaStatus, androidDevices }) {
  const [connectQr, setConnectQr] = useState(null)

  useEffect(() => {
    if (androidDevices.length === 0) {
      fetch('http://localhost:5050/connect/qr')
        .then(r => r.json())
        .then(d => { if (d.ok) setConnectQr(d.qr_base64) })
        .catch(() => {})
    } else {
      setConnectQr(null)
    }
  }, [androidDevices.length])

  return (
    <div>
      <SectionHeader label="PHONE" />
      <div style={{ padding: '0 16px 12px' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: androidDevices.length > 0 ? 10 : 0 }}>
          <StatusDot status={mmaStatus} />
          <span style={{
            color: mmaStatus === 'online' ? '#1db954' : '#ff3d3d',
            fontFamily: "'Share Tech Mono'", fontSize: '10px',
            letterSpacing: '0.2em', textTransform: 'uppercase',
          }}>
            {mmaStatus}
          </span>
          <span style={{ color: '#1a4a5a', fontFamily: "'JetBrains Mono'", fontSize: '9px', marginLeft: 2 }}>
            {mmaStatus === 'offline' ? 'MMA not running' : 'Online'}
          </span>
        </div>

        {androidDevices.length > 0 && (
          <div style={{ marginTop: 4 }}>
            {androidDevices.map((name, i) => (
              <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 7, marginBottom: 5 }}>
                <span style={{
                  display: 'inline-block', width: 6, height: 6, borderRadius: '50%',
                  background: '#1db954', boxShadow: '0 0 5px #1db954',
                  flexShrink: 0,
                }} />
                <span style={{
                  color: '#c8f0ff', fontFamily: "'JetBrains Mono'", fontSize: '9px',
                  overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                }}>
                  {name}
                </span>
                <span style={{
                  color: '#1db954', fontFamily: "'Share Tech Mono'", fontSize: '8px',
                  letterSpacing: '0.15em', marginLeft: 'auto', flexShrink: 0,
                }}>
                  ONLINE
                </span>
              </div>
            ))}
          </div>
        )}

        {androidDevices.length === 0 && (
          <div style={{ marginTop: 6 }}>
            <p style={{ color: '#3a6070', fontFamily: "'Share Tech Mono'", fontSize: '8px', letterSpacing: '0.12em', marginBottom: 8 }}>
              SCAN TO CONNECT PHONE
            </p>
            {connectQr ? (
              <img
                src={`data:image/png;base64,${connectQr}`}
                alt="Connect QR"
                style={{ width: '100%', borderRadius: 4, display: 'block' }}
              />
            ) : (
              <p style={{ color: '#1a3a4a', fontFamily: "'JetBrains Mono'", fontSize: '9px' }}>
                Loading QR…
              </p>
            )}
            <p style={{ color: '#1a4a5a', fontFamily: "'JetBrains Mono'", fontSize: '8px', marginTop: 6, lineHeight: 1.4 }}>
              Open iZACH app → Settings → Scan QR Code
            </p>
          </div>
        )}
      </div>
    </div>
  )
}

const LINK_TYPES = ['class', 'meeting']

function CalendarPanel({ events = [], onCalendarUpdate }) {
  const [expanded, setExpanded] = useState(null)
  const [editing, setEditing]   = useState(null)
  const [saving, setSaving]     = useState(false)

  function startEdit(ev) {
    const start = ev.start ? new Date(ev.start) : null
    setEditing({
      id: ev.id,
      title: ev.title,
      date: start ? start.toISOString().slice(0, 10) : '',
      time: start ? start.toTimeString().slice(0, 5) : '',
      link: ev.link || '',
      event_type: ev.event_type || 'other',
    })
  }

  async function saveEdit() {
    if (!editing) return
    setSaving(true)
    try {
      await fetch(`${BASE}/calendar/events/${editing.id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          title: editing.title,
          date: editing.date,
          time: editing.time,
          link: LINK_TYPES.includes(editing.event_type) ? editing.link : null,
        }),
      })
      // refresh list
      const r = await fetch(`${BASE}/calendar/events`)
      const d = await r.json()
      if (d.ok && onCalendarUpdate) onCalendarUpdate(d.events || [])
      setEditing(null)
      setExpanded(null)
    } catch {}
    setSaving(false)
  }

  async function deleteEvent(id) {
    await fetch(`${BASE}/calendar/events/${id}`, { method: 'DELETE' })
    const r = await fetch(`${BASE}/calendar/events`)
    const d = await r.json()
    if (d.ok && onCalendarUpdate) onCalendarUpdate(d.events || [])
    setEditing(null)
    setExpanded(null)
  }

  function fmtDateTime(iso) {
    if (!iso) return '—'
    try {
      const d = new Date(iso)
      const date = d.toLocaleDateString('en-IN', { day: '2-digit', month: 'short' })
      const time = d.toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit', hour12: true })
      return `${date}, ${time}`
    } catch { return iso }
  }

  const typeColor = { class: '#00e5ff', meeting: '#1db954', social: '#ff9800', appointment: '#ff4081', other: '#3a6070' }

  return (
    <div>
      <SectionHeader label="CALENDAR — NEXT 3 DAYS" />
      <div style={{ padding: '0 16px 12px' }}>
        {events.length === 0 ? (
          <p style={{ color: '#1a4a5a', fontFamily: "'JetBrains Mono'", fontSize: '9px' }}>No events in next 3 days</p>
        ) : events.map(ev => {
          const isOpen = expanded === ev.id
          const isEditing = editing && editing.id === ev.id
          const color = typeColor[ev.event_type] || typeColor.other
          return (
            <div key={ev.id} style={{
              marginBottom: 6,
              border: `1px solid ${isOpen ? color + '55' : '#0d2a3a'}`,
              borderRadius: 4,
              overflow: 'hidden',
              transition: 'border-color 0.2s',
            }}>
              {/* Row */}
              <div
                onClick={() => { setExpanded(isOpen ? null : ev.id); setEditing(null) }}
                style={{
                  display: 'flex', alignItems: 'center', gap: 7,
                  padding: '6px 8px', cursor: 'pointer',
                  background: isOpen ? 'rgba(0,229,255,0.04)' : 'transparent',
                }}
              >
                <span style={{
                  width: 5, height: 5, borderRadius: '50%', flexShrink: 0,
                  background: color, boxShadow: `0 0 4px ${color}88`,
                }} />
                <div style={{ flex: 1, overflow: 'hidden' }}>
                  <p style={{
                    color: '#c8e8f0', fontFamily: "'JetBrains Mono'", fontSize: '9px',
                    whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis',
                  }}>{ev.title}</p>
                  <p style={{ color: '#3a6070', fontFamily: "'Share Tech Mono'", fontSize: '8px', marginTop: 1 }}>
                    {fmtDateTime(ev.start)}
                  </p>
                </div>
                <span style={{ color: '#1a4a5a', fontSize: '8px' }}>{isOpen ? '▲' : '▼'}</span>
              </div>

              {/* Expanded detail / edit */}
              {isOpen && (
                <div style={{ padding: '8px', borderTop: `1px solid #0d2a3a`, background: '#060f1e' }}>
                  {!isEditing ? (
                    <>
                      <p style={{ color: '#3a6070', fontFamily: "'Share Tech Mono'", fontSize: '8px', letterSpacing: '0.1em', marginBottom: 4 }}>
                        {ev.event_type.toUpperCase()}
                      </p>
                      {ev.link && (
                        <p style={{ color: '#00e5ff', fontFamily: "'JetBrains Mono'", fontSize: '8px', wordBreak: 'break-all', marginBottom: 6 }}>
                          {ev.link}
                        </p>
                      )}
                      <div style={{ display: 'flex', gap: 6, marginTop: 6 }}>
                        <button onClick={() => startEdit(ev)} style={btnStyle('#00e5ff')}>Edit</button>
                        <button onClick={() => deleteEvent(ev.id)} style={btnStyle('#ff3d3d')}>Delete</button>
                      </div>
                    </>
                  ) : (
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                      <input
                        value={editing.title}
                        onChange={e => setEditing(p => ({ ...p, title: e.target.value }))}
                        placeholder="Title"
                        style={inputStyle}
                      />
                      <input
                        type="date"
                        value={editing.date}
                        onChange={e => setEditing(p => ({ ...p, date: e.target.value }))}
                        style={inputStyle}
                      />
                      <input
                        type="time"
                        value={editing.time}
                        onChange={e => setEditing(p => ({ ...p, time: e.target.value }))}
                        style={inputStyle}
                      />
                      {LINK_TYPES.includes(editing.event_type) && (
                        <input
                          value={editing.link}
                          onChange={e => setEditing(p => ({ ...p, link: e.target.value }))}
                          placeholder="Link (Meet/Zoom)"
                          style={inputStyle}
                        />
                      )}
                      <div style={{ display: 'flex', gap: 6, marginTop: 2 }}>
                        <button onClick={saveEdit} disabled={saving} style={btnStyle('#1db954')}>
                          {saving ? '...' : 'Save'}
                        </button>
                        <button onClick={() => setEditing(null)} style={btnStyle('#3a6070')}>Cancel</button>
                      </div>
                    </div>
                  )}
                </div>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}

const btnStyle = (color) => ({
  background: 'transparent',
  border: `1px solid ${color}`,
  borderRadius: 3,
  color: color,
  fontFamily: "'Share Tech Mono'",
  fontSize: '8px',
  letterSpacing: '0.1em',
  padding: '3px 8px',
  cursor: 'pointer',
})

const inputStyle = {
  background: '#0a1628',
  border: '1px solid #0d2a3a',
  borderRadius: 3,
  color: '#c8e8f0',
  fontFamily: "'JetBrains Mono'",
  fontSize: '9px',
  padding: '4px 6px',
  width: '100%',
  boxSizing: 'border-box',
}

// ── TERMINAL PANEL ────────────────────────────────────────────────────────────

function ShellInput() {
  const [cmd, setCmd] = React.useState('')
  const [busy, setBusy] = React.useState(false)

  async function submit(e) {
    e.preventDefault()
    const trimmed = cmd.trim()
    if (!trimmed || busy) return
    setBusy(true)
    try {
      await fetch(`${BASE}/shell/run`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ command: trimmed }),
      })
      setCmd('')
    } catch {}
    setBusy(false)
  }

  return (
    <form onSubmit={submit} style={{ display: 'flex', gap: 4, padding: '6px 10px 4px' }}>
      <span style={{ fontFamily: "'JetBrains Mono'", fontSize: 8, color: '#38bdf8', alignSelf: 'center' }}>PS&gt;</span>
      <input
        value={cmd}
        onChange={e => setCmd(e.target.value)}
        placeholder="type command…"
        disabled={busy}
        style={{
          flex: 1, background: '#050d1a', border: '1px solid #1e3a5f',
          borderRadius: 3, color: '#c8e8f0', fontFamily: "'JetBrains Mono'",
          fontSize: 8, padding: '3px 5px', outline: 'none',
        }}
      />
      <button type="submit" disabled={busy || !cmd.trim()} style={{
        background: busy ? '#0a1628' : '#1e3a5f', border: '1px solid #38bdf8',
        borderRadius: 3, color: '#38bdf8', fontSize: 8, cursor: 'pointer', padding: '2px 7px',
        fontFamily: "'JetBrains Mono'",
      }}>run</button>
    </form>
  )
}

function TerminalPanel({ shellOutput, onClear }) {
  if (!shellOutput) return null

  const { command, lines, done, exitCode, truncated } = shellOutput
  const statusColor = !done ? '#38bdf8' : exitCode === 0 ? '#22c55e' : '#f87171'
  const statusLabel = !done ? 'running…' : exitCode === 0 ? `exit 0` : `exit ${exitCode}`

  return (
    <div style={{ padding: '8px 10px' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 4 }}>
        <span style={{ color: '#38bdf8', fontSize: 9, fontFamily: "'JetBrains Mono'", letterSpacing: 1 }}>TERMINAL</span>
        <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
          <span style={{ color: statusColor, fontSize: 8, fontFamily: "'JetBrains Mono'" }}>{statusLabel}</span>
          {done && (
            <button onClick={onClear} style={{
              background: 'none', border: '1px solid #1e3a5f', borderRadius: 2,
              color: '#4a90a4', fontSize: 8, cursor: 'pointer', padding: '1px 5px',
            }}>clear</button>
          )}
        </div>
      </div>

      {/* Command */}
      <div style={{
        fontFamily: "'JetBrains Mono'", fontSize: 8, color: '#7dd3fc',
        background: '#050d1a', borderRadius: 3, padding: '3px 6px',
        marginBottom: 4, wordBreak: 'break-all',
      }}>
        PS&gt; {command}
      </div>

      {/* Output */}
      <div style={{
        fontFamily: "'JetBrains Mono'", fontSize: 8, color: '#c8e8f0',
        background: '#050d1a', borderRadius: 3, padding: '4px 6px',
        maxHeight: 160, overflowY: 'auto', whiteSpace: 'pre-wrap', wordBreak: 'break-all',
        lineHeight: 1.5,
      }}>
        {lines.length === 0 && !done
          ? <span style={{ color: '#4a90a4' }}>waiting for output…</span>
          : lines.join('')
        }
        {truncated && <div style={{ color: '#f87171' }}>[output truncated]</div>}
      </div>
    </div>
  )
}

// ── SHELL CONFIRM MODAL ───────────────────────────────────────────────────────

function ShellConfirmModal({ shellConfirm, onDismiss }) {
  if (!shellConfirm) return null
  const { id, command } = shellConfirm

  async function handleRun() {
    onDismiss()
    await fetch(`${BASE}/shell/confirm`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ id }),
    }).catch(() => {})
  }

  async function handleCancel() {
    onDismiss()
    await fetch(`${BASE}/shell/cancel`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ id }),
    }).catch(() => {})
  }

  return (
    <div style={{
      position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.7)',
      display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 9999,
    }}>
      <div style={{
        background: '#0a1628', border: '1px solid #1e3a5f', borderRadius: 8,
        padding: '18px 20px', maxWidth: 420, width: '90%',
        boxShadow: '0 0 32px rgba(0,120,200,0.2)',
      }}>
        <div style={{ color: '#f59e0b', fontSize: 11, fontFamily: "'JetBrains Mono'", marginBottom: 10 }}>
          CONFIRM COMMAND EXECUTION
        </div>
        <div style={{
          fontFamily: "'JetBrains Mono'", fontSize: 9, color: '#7dd3fc',
          background: '#050d1a', borderRadius: 4, padding: '6px 10px',
          marginBottom: 14, wordBreak: 'break-all', whiteSpace: 'pre-wrap',
        }}>
          PS&gt; {command}
        </div>
        <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
          <button onClick={handleCancel} style={{
            background: 'none', border: '1px solid #1e3a5f', borderRadius: 4,
            color: '#4a90a4', fontSize: 9, cursor: 'pointer', padding: '4px 12px',
            fontFamily: "'JetBrains Mono'",
          }}>Cancel</button>
          <button onClick={handleRun} style={{
            background: '#1e3a5f', border: '1px solid #38bdf8', borderRadius: 4,
            color: '#38bdf8', fontSize: 9, cursor: 'pointer', padding: '4px 12px',
            fontFamily: "'JetBrains Mono'",
          }}>Run</button>
        </div>
      </div>
    </div>
  )
}

// ─────────────────────────────────────────────────────────────────────────────

export default function RightPanel({ waStatus, mmaStatus, spotifyTrack, notifications, whatsappQr, androidDevices = [], calendarEvents = [], onCalendarUpdate, shellConfirm, setShellConfirm, shellOutput, setShellOutput }) {
  return (
    <>
      <ShellConfirmModal shellConfirm={shellConfirm} onDismiss={() => setShellConfirm(null)} />
      <div style={{
        display: 'flex', flexDirection: 'column',
        height: '100%', overflowY: 'auto', overflowX: 'hidden',
        background: '#0a1628', borderLeft: '1px solid #0d2a3a',
      }}>
        <SpotifyPanel track={spotifyTrack} />
        <Divider />
        <CalendarPanel events={calendarEvents} onCalendarUpdate={onCalendarUpdate} />
        <Divider />
        <MmaPanel mmaStatus={mmaStatus} androidDevices={androidDevices} />
        <Divider />
        <WhatsAppPanel status={waStatus} qr={whatsappQr} />
        <Divider />
        <NotificationsPanel notifications={notifications} />
        <Divider />
        <div style={{ padding: '6px 10px 2px' }}>
          <span style={{ color: '#38bdf8', fontSize: 9, fontFamily: "'JetBrains Mono'", letterSpacing: 1 }}>TERMINAL</span>
        </div>
        <ShellInput />
        {shellOutput && (
          <TerminalPanel shellOutput={shellOutput} onClear={() => setShellOutput(null)} />
        )}
        <Divider />
        <SystemLog errors={[]} />
      </div>
    </>
  )
}