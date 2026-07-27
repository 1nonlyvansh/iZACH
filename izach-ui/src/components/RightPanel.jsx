import React, { useState, useEffect } from 'react'
import QRCode from 'qrcode'
import RelationshipGraph from './RelationshipGraph.jsx'
import DevicesWidget from './DevicesWidget.jsx'

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
  const [qrDataUrl,    setQrDataUrl]    = useState(null)
  const [restarting,   setRestarting]   = useState(false)
  const [restartMsg,   setRestartMsg]   = useState('')

  useEffect(() => {
    if (qr && qr.length > 0) {
      setQrDataUrl(`data:image/png;base64,${qr}`)
    } else {
      setQrDataUrl(null)
    }
  }, [qr])

  async function restartBridge() {
    setRestarting(true)
    setRestartMsg('Restarting…')
    try {
      const r = await fetch(`${BASE}/whatsapp/restart-bridge`, { method: 'POST' }).then(r => r.json())
      setRestartMsg(r.ok ? 'Bridge restarting — wait ~10s' : (r.error || 'Failed'))
    } catch {
      setRestartMsg('Backend offline')
    }
    setTimeout(() => { setRestarting(false); setRestartMsg('') }, 10000)
  }

  const btnStyle = {
    padding: '4px 10px', background: 'rgba(0,148,255,0.08)',
    border: '1px solid rgba(0,148,255,0.25)', borderRadius: 4,
    color: 'rgba(0,148,255,0.7)', fontFamily: "'Share Tech Mono'",
    fontSize: '8px', letterSpacing: '0.12em', cursor: 'pointer',
    marginLeft: 'auto', flexShrink: 0,
    opacity: restarting ? 0.5 : 1,
  }

  return (
    <div>
      <SectionHeader label="WHATSAPP BRIDGE" />
      <div style={{ padding: '0 16px 12px' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: (qrDataUrl || restartMsg) ? 8 : 0 }}>
          <StatusDot status={status} />
          <span style={{
            color: status === 'online' ? '#1db954' : '#ff3d3d',
            fontFamily: "'Share Tech Mono'", fontSize: '10px',
            letterSpacing: '0.2em', textTransform: 'uppercase',
          }}>
            {status}
          </span>
          {status === 'online' && (
            <span style={{ color: '#1a4a5a', fontFamily: "'JetBrains Mono'", fontSize: '9px' }}>
              Connected
            </span>
          )}
          <button
            onClick={restartBridge}
            disabled={restarting}
            title="Restart bridge — fixes port-3000 / offline errors"
            style={btnStyle}
          >
            ↺ RESTART
          </button>
        </div>
        {restartMsg && (
          <p style={{ color: '#5a9ab0', fontFamily: "'Share Tech Mono'", fontSize: '8px', marginBottom: 6 }}>
            {restartMsg}
          </p>
        )}
        {qrDataUrl && status !== 'online' && (
          <div>
            <p style={{ color: '#3a6070', fontFamily: "'Share Tech Mono'", fontSize: '8px', letterSpacing: '0.12em', marginBottom: 6 }}>
              SCAN TO CONNECT
            </p>
            <img src={qrDataUrl} alt="WhatsApp QR" style={{ width: '100%', borderRadius: 4, display: 'block' }} />
          </div>
        )}
        {status === 'online' && (
          <p style={{ color: '#1a4a5a', fontFamily: "'JetBrains Mono'", fontSize: '8px', marginTop: 4 }}>
            To log out, go to Settings
          </p>
        )}
      </div>
    </div>
  )
}

function MmaPanel({ mmaStatus, androidDevices }) {
  const [connectQr, setConnectQr]       = useState(null)
  const [qrMode, setQrMode]             = useState('lan')      // 'lan' | 'tailscale'
  const [tailscaleIp, setTailscaleIp]   = useState(null)

  useEffect(() => {
    if (androidDevices.length !== 0) { setConnectQr(null); return }
    fetch(`http://localhost:5050/connect/qr?mode=${qrMode}`)
      .then(r => r.json())
      .then(d => {
        if (!d.ok) return
        setConnectQr(d.qr_base64)
        if (d.tailscale_ip) setTailscaleIp(d.tailscale_ip)
      })
      .catch(() => {})
  }, [androidDevices.length, qrMode])

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
            {tailscaleIp && (
              <div style={{ display: 'flex', gap: 4, marginBottom: 8 }}>
                {['lan', 'tailscale'].map(m => (
                  <button
                    key={m}
                    onClick={() => setQrMode(m)}
                    style={{
                      flex: 1,
                      padding: '3px 0',
                      background: qrMode === m ? '#0a2a3a' : 'transparent',
                      border: `1px solid ${qrMode === m ? '#1a6a8a' : '#0a2a3a'}`,
                      borderRadius: 3,
                      color: qrMode === m ? '#c8f0ff' : '#1a4a5a',
                      fontFamily: "'Share Tech Mono'",
                      fontSize: '8px',
                      letterSpacing: '0.1em',
                      cursor: 'pointer',
                      textTransform: 'uppercase',
                    }}
                  >
                    {m === 'lan' ? 'Local' : 'Remote'}
                  </button>
                ))}
              </div>
            )}
            <p style={{ color: '#3a6070', fontFamily: "'Share Tech Mono'", fontSize: '8px', letterSpacing: '0.12em', marginBottom: 8 }}>
              {qrMode === 'tailscale' ? `TAILSCALE · ${tailscaleIp}` : 'SCAN TO CONNECT PHONE'}
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
              {qrMode === 'tailscale'
                ? 'Requires Tailscale on both devices · works from any network'
                : 'Open iZACH app → Settings → Scan QR Code'}
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

// ── OCR WIDGET ────────────────────────────────────────────────────────────────

function OCRWidget() {
  const [enabled,  setEnabled]  = React.useState(false)
  const [mode,     setMode]     = React.useState('idle')   // idle | scanning | done
  const [text,     setText]     = React.useState('')
  const [copied,   setCopied]   = React.useState(false)
  const pollRef = React.useRef(null)

  const modeColor = { idle: '#3a6070', scanning: '#00e5ff', done: '#1db954' }

  async function toggle() {
    const next = !enabled
    setEnabled(next)
    setMode(next ? 'scanning' : 'idle')
    try {
      await fetch(`${BASE}/ocr/toggle`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ enabled: next }),
      })
      if (next) {
        pollRef.current = setInterval(async () => {
          const r = await fetch(`${BASE}/ocr/status`).then(x => x.json()).catch(() => null)
          if (r?.mode === 'done') {
            clearInterval(pollRef.current)
            setEnabled(false); setMode('done'); setText(r.last_text || '')
          }
        }, 1500)
      } else {
        clearInterval(pollRef.current)
      }
    } catch {}
  }

  async function scanUpload(e) {
    const file = e.target.files[0]; if (!file) return
    setMode('scanning')
    const b64 = await new Promise(res => {
      const fr = new FileReader()
      fr.onload = ev => res(ev.target.result.split(',')[1])
      fr.readAsDataURL(file)
    })
    e.target.value = ''
    try {
      const r = await fetch(`${BASE}/ocr/scan-image`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ image: b64, mime: file.type }),
      }).then(x => x.json())
      setText(r.text || ''); setMode('done')
    } catch { setMode('idle') }
  }

  function copy() {
    if (!text) return
    import('../utils/clipboard.js').then(({ copyToClipboard }) => {
      copyToClipboard(text).then(ok => {
        if (ok) {
          setCopied(true)
          setTimeout(() => setCopied(false), 1500)
        }
      })
    })
  }

  async function save() {
    if (!text) return
    await fetch(`${BASE}/ocr/save`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text }),
    }).catch(() => {})
  }

  React.useEffect(() => () => clearInterval(pollRef.current), [])

  return (
    <div>
      <SectionHeader label="DOCUMENT OCR" />
      <div style={{ padding: '0 16px 12px' }}>

        {/* Status + toggle */}
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 8 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            <div style={{
              width: 6, height: 6, borderRadius: '50%',
              background: modeColor[mode],
              boxShadow: mode === 'scanning' ? '0 0 6px #00e5ff' : 'none',
              transition: 'all 0.3s',
            }} />
            <span style={{ fontFamily: "'Share Tech Mono'", fontSize: 9, letterSpacing: '0.2em', color: modeColor[mode] }}>
              {mode.toUpperCase()}
            </span>
          </div>
          {/* Toggle switch */}
          <div onClick={toggle} style={{
            width: 32, height: 16, borderRadius: 8, cursor: 'pointer', position: 'relative',
            background: enabled ? 'rgba(0,229,255,0.2)' : 'rgba(13,42,58,0.8)',
            border: `1px solid ${enabled ? '#00e5ff55' : '#0d2a3a'}`,
            transition: 'all 0.2s',
          }}>
            <div style={{
              position: 'absolute', top: 2, left: enabled ? 14 : 2,
              width: 10, height: 10, borderRadius: '50%',
              background: enabled ? '#00e5ff' : '#1a4a5a',
              transition: 'left 0.2s',
            }} />
          </div>
        </div>

        {/* Upload + cam scan buttons */}
        <div style={{ display: 'flex', gap: 4, marginBottom: 8 }}>
          <label style={{
            flex: 1, textAlign: 'center', padding: '4px 0',
            background: 'rgba(0,148,255,0.07)', border: '1px solid #0d2a3a',
            borderRadius: 3, color: '#3a6070', fontFamily: "'Share Tech Mono'",
            fontSize: 8, letterSpacing: '0.15em', cursor: 'pointer',
          }}>
            ⊡ UPLOAD
            <input type="file" accept="image/*" style={{ display: 'none' }} onChange={scanUpload} />
          </label>
          <button onClick={toggle} style={{
            flex: 1, padding: '4px 0',
            background: enabled ? 'rgba(0,229,255,0.1)' : 'rgba(0,148,255,0.07)',
            border: `1px solid ${enabled ? '#00e5ff44' : '#0d2a3a'}`,
            borderRadius: 3, color: enabled ? '#00e5ff' : '#3a6070',
            fontFamily: "'Share Tech Mono'", fontSize: 8, letterSpacing: '0.15em', cursor: 'pointer',
          }}>
            ◎ CAM SCAN
          </button>
        </div>

        {/* Extracted text */}
        <textarea
          readOnly value={text}
          placeholder="Scan or upload a document…"
          style={{
            width: '100%', height: 80, background: '#050d1a',
            border: '1px solid #0d2a3a', borderRadius: 3,
            color: '#60b8d0', fontFamily: "'JetBrains Mono'", fontSize: 8,
            lineHeight: 1.6, padding: '5px 7px', resize: 'none',
            outline: 'none', boxSizing: 'border-box', marginBottom: 6,
          }}
        />

        {/* Action buttons */}
        <div style={{ display: 'flex', gap: 4 }}>
          {[
            { label: copied ? 'COPIED ✓' : 'COPY', fn: copy, color: copied ? '#1db954' : '#3a6070' },
            { label: 'SAVE',  fn: save,           color: '#3a6070' },
            { label: 'CLEAR', fn: () => { setText(''); setMode('idle') }, color: '#ff3d3d55' },
          ].map(({ label, fn, color }) => (
            <button key={label} onClick={fn} style={{
              flex: 1, padding: '3px 0',
              background: 'transparent', border: `1px solid ${color}`,
              borderRadius: 3, color, fontFamily: "'Share Tech Mono'",
              fontSize: 7, letterSpacing: '0.1em', cursor: 'pointer',
            }}>{label}</button>
          ))}
        </div>
      </div>
    </div>
  )
}

// ── FITNESS WIDGET ────────────────────────────────────────────────────────────

function FitnessWidget() {
  const [data,    setData]    = useState(null)
  const [loading, setLoading] = useState(false)
  const [codeRow, setCodeRow] = useState(false)
  const [authCode, setAuthCode] = useState('')

  const refresh = async () => {
    try {
      const r = await fetch(`${BASE}/fitness/summary`)
      setData(await r.json())
    } catch {}
  }

  useEffect(() => { refresh() }, [])

  const startAuth = async () => {
    try {
      const r = await fetch(`${BASE}/fitness/auth/start`)
      const d = await r.json()
      if (d.error) { alert(d.error); return }
      window.open(d.url, '_blank')
      setCodeRow(true)
    } catch { alert('Cannot reach backend') }
  }

  const completeAuth = async () => {
    if (!authCode.trim()) return
    setLoading(true)
    try {
      const r = await fetch(`${BASE}/fitness/auth/complete`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ code: authCode }),
      })
      const d = await r.json()
      if (d.error) { alert(d.error); return }
      setCodeRow(false); setAuthCode('')
      refresh()
    } catch { alert('Cannot reach backend') }
    setLoading(false)
  }

  const pct = data?.steps ? Math.min(100, Math.round(data.steps / 10000 * 100)) : 0
  const connected = data?.connected

  const metric = (val, label, color) => (
    <div style={{
      flex: 1, background: 'rgba(0,10,28,0.7)',
      border: '1px solid rgba(0,148,255,0.1)', borderRadius: 4,
      padding: '8px 4px', textAlign: 'center',
    }}>
      <div style={{ fontSize: 15, color, fontFamily: "'Share Tech Mono'" }}>{val ?? '—'}</div>
      <div style={{ fontSize: 7, color: 'rgba(0,148,255,0.4)', letterSpacing: '0.3em', marginTop: 3 }}>{label}</div>
    </div>
  )

  return (
    <div>
      <SectionHeader label="GOOGLE FIT" />
      <div style={{ padding: '0 16px 10px' }}>

        {/* Status row */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
          <div style={{
            width: 7, height: 7, borderRadius: '50%',
            background: connected ? '#1db954' : 'rgba(0,148,255,0.2)',
            boxShadow: connected ? '0 0 6px #1db954' : 'none',
          }} />
          <span style={{ fontSize: 8, letterSpacing: '0.25em', color: connected ? '#1db954' : 'rgba(0,148,255,0.4)', fontFamily: "'Share Tech Mono'" }}>
            {connected ? 'CONNECTED' : 'NOT CONNECTED'}
          </span>
          {connected && (
            <button onClick={refresh} style={{
              marginLeft: 'auto', background: 'none', border: 'none',
              color: 'rgba(0,200,255,0.5)', cursor: 'pointer', fontSize: 12,
            }}>↻</button>
          )}
        </div>

        {/* Connect button */}
        {!connected && (
          <button onClick={startAuth} style={{
            width: '100%', padding: '6px 0', marginBottom: 6,
            background: 'rgba(0,148,255,0.1)', border: '1px solid rgba(0,148,255,0.3)',
            borderRadius: 3, color: 'rgba(0,200,255,0.8)',
            fontFamily: "'Share Tech Mono'", fontSize: 9, letterSpacing: '0.15em', cursor: 'pointer',
          }}>⊕ CONNECT GOOGLE FIT</button>
        )}

        {/* Auth code row */}
        {codeRow && (
          <div style={{ marginBottom: 8 }}>
            <div style={{ fontSize: 7, color: 'rgba(0,148,255,0.4)', letterSpacing: '0.2em', marginBottom: 4 }}>PASTE AUTH CODE:</div>
            <div style={{ display: 'flex', gap: 5 }}>
              <input value={authCode} onChange={e => setAuthCode(e.target.value)}
                placeholder="4/0AX…"
                style={{
                  flex: 1, background: 'rgba(0,10,28,0.8)', border: '1px solid rgba(0,148,255,0.2)',
                  borderRadius: 2, color: 'rgba(0,200,255,0.8)',
                  fontFamily: "'Share Tech Mono'", fontSize: 8, padding: '4px 6px', outline: 'none',
                }} />
              <button onClick={completeAuth} disabled={loading} style={{
                padding: '4px 10px', background: 'rgba(0,148,255,0.15)',
                border: '1px solid rgba(0,148,255,0.35)', borderRadius: 2,
                color: 'rgba(0,200,255,0.8)', fontFamily: "'Share Tech Mono'",
                fontSize: 8, cursor: 'pointer',
              }}>OK</button>
            </div>
          </div>
        )}

        {/* Metrics */}
        {connected && data && (
          <>
            <div style={{ fontSize: 7, color: 'rgba(0,148,255,0.35)', letterSpacing: '0.3em', marginBottom: 8 }}>
              TODAY — {data.date || '—'}
            </div>
            <div style={{ display: 'flex', gap: 6, marginBottom: 10 }}>
              {metric((data.steps || 0).toLocaleString(), 'STEPS',      'rgba(0,200,255,0.9)')}
              {metric(Math.round(data.calories || 0),    'KCAL',       'rgba(255,140,80,0.9)')}
              {metric(data.active_minutes || 0,          'ACTIVE MIN', 'rgba(80,220,120,0.9)')}
            </div>

            {/* Step progress bar */}
            <div style={{ marginBottom: 10 }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 7, color: 'rgba(0,148,255,0.4)', letterSpacing: '0.15em', marginBottom: 4 }}>
                <span>STEP GOAL (10K)</span><span>{pct}%</span>
              </div>
              <div style={{ height: 3, background: 'rgba(0,148,255,0.08)', borderRadius: 2, overflow: 'hidden' }}>
                <div style={{ height: '100%', width: pct + '%', background: '#00c8ff', borderRadius: 2, transition: 'width 0.6s ease' }} />
              </div>
            </div>

            {/* Recent sessions */}
            {data.sessions?.length > 0 && (
              <div>
                <div style={{ fontSize: 7, color: 'rgba(0,148,255,0.32)', letterSpacing: '0.35em', marginBottom: 6 }}>RECENT WORKOUTS</div>
                {data.sessions.map((s, i) => (
                  <div key={i} style={{
                    display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                    padding: '5px 0', borderBottom: '1px solid rgba(0,148,255,0.06)',
                  }}>
                    <div>
                      <div style={{ fontSize: 9, color: 'rgba(0,200,255,0.7)', letterSpacing: '0.1em' }}>{s.activity}</div>
                      <div style={{ fontSize: 7, color: 'rgba(0,148,255,0.4)', letterSpacing: '0.1em' }}>{s.date}</div>
                    </div>
                    <span style={{ fontSize: 10, color: 'rgba(0,200,255,0.5)' }}>{s.duration_min}m</span>
                  </div>
                ))}
              </div>
            )}
          </>
        )}
      </div>
    </div>
  )
}

// ── LOCATION WIDGET ───────────────────────────────────────────────────────────

function LocationWidget() {
  const [loc,        setLoc]        = useState(null)
  const [labelInput, setLabelInput] = useState('')

  const refresh = async () => {
    try {
      const r = await fetch(`${BASE}/location/status`)
      setLoc(await r.json())
    } catch {}
  }

  const toggle = async () => {
    const running = loc?.engine_running
    try {
      await fetch(`${BASE}/location/toggle`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ enabled: !running }),
      })
      refresh()
    } catch {}
  }

  const saveLabel = async () => {
    const label = labelInput.trim()
    if (!label || !loc?.pc?.ssid) return
    try {
      await fetch(`${BASE}/location/label-ssid`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ssid: loc.pc.ssid, label }),
      })
      setLabelInput('')
      refresh()
    } catch {}
  }

  // Fetch once on mount — no background polling
  useEffect(() => { refresh() }, [])

  const phone  = loc?.phone || {}
  const pc     = loc?.pc    || {}
  const active = phone.active && phone.lat
  const ago    = phone.ts ? Math.round((Date.now() / 1000 - phone.ts) / 60) : null

  const running = loc?.engine_running

  return (
    <div>
      <SectionHeader label="LOCATION" />
      <div style={{ padding: '0 16px 10px' }}>

        {/* Engine toggle */}
        <button onClick={toggle} style={{
          width: '100%', padding: '6px 0', marginBottom: 10,
          background: running ? 'rgba(255,50,50,0.07)' : 'rgba(0,148,255,0.08)',
          border: `1px solid ${running ? 'rgba(255,80,80,0.35)' : 'rgba(0,148,255,0.3)'}`,
          borderRadius: 3,
          color: running ? 'rgba(255,100,100,0.8)' : 'rgba(0,200,255,0.8)',
          fontFamily: "'Share Tech Mono'", fontSize: 9, letterSpacing: '0.2em', cursor: 'pointer',
          transition: 'all 0.2s',
        }}>
          {running ? '■ STOP TRACKING' : '▶ START TRACKING'}
        </button>

        {/* Phone GPS */}
        <div style={{ marginBottom: 10 }}>
          <div style={{ fontSize: 7, color: 'rgba(0,148,255,0.32)', letterSpacing: '0.35em', marginBottom: 6 }}>PHONE GPS</div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 5 }}>
            <div style={{
              width: 7, height: 7, borderRadius: '50%', flexShrink: 0,
              background: active ? '#1db954' : 'rgba(0,148,255,0.2)',
              boxShadow: active ? '0 0 6px #1db954' : 'none',
            }} />
            <span style={{ fontSize: 8, letterSpacing: '0.2em', color: active ? '#1db954' : 'rgba(0,148,255,0.4)', fontFamily: "'Share Tech Mono'" }}>
              {active ? 'ACTIVE' : 'NO SIGNAL'}
            </span>
            <button onClick={refresh} style={{ marginLeft: 'auto', background: 'none', border: 'none', color: 'rgba(0,200,255,0.5)', cursor: 'pointer', fontSize: 12 }}>↻</button>
          </div>

          {active && (
            <>
              <div style={{ fontSize: 10, color: 'rgba(0,200,255,0.75)', letterSpacing: '0.1em', marginBottom: 3 }}>
                {phone.place_name || 'Locating…'}
              </div>
              {phone.place_type && (
                <div style={{ fontSize: 7, color: 'rgba(0,148,255,0.45)', letterSpacing: '0.2em', marginBottom: 5 }}>
                  ▸ {phone.place_type.toUpperCase()}
                </div>
              )}
              <div style={{ display: 'flex', gap: 12, fontSize: 7, color: 'rgba(0,148,255,0.35)', letterSpacing: '0.1em' }}>
                <span>LAT {phone.lat?.toFixed(4)}</span>
                <span>LON {phone.lon?.toFixed(4)}</span>
                <span>±{Math.round(phone.accuracy || 0)}m</span>
              </div>
              <div style={{ fontSize: 7, color: 'rgba(0,148,255,0.25)', letterSpacing: '0.1em', marginTop: 3 }}>
                LAST PING: {ago === null ? '—' : ago < 1 ? 'just now' : `${ago}m ago`}
              </div>
            </>
          )}

          {!active && (
            <div style={{ fontSize: 8, color: 'rgba(0,148,255,0.3)', letterSpacing: '0.1em', marginTop: 4 }}>
              Open <span style={{ color: 'rgba(0,200,255,0.5)' }}>location_companion.html</span> on your phone
            </div>
          )}
        </div>

        <Divider />

        {/* PC network location */}
        <div style={{ marginTop: 8, marginBottom: 10 }}>
          <div style={{ fontSize: 7, color: 'rgba(0,148,255,0.32)', letterSpacing: '0.35em', marginBottom: 6 }}>PC NETWORK</div>
          <div style={{ fontSize: 10, color: 'rgba(0,200,255,0.65)', letterSpacing: '0.1em' }}>
            {pc.city ? `${pc.city}, ${pc.country || ''}` : '—'}
          </div>
          <div style={{ fontSize: 7, color: 'rgba(0,148,255,0.35)', letterSpacing: '0.2em', marginTop: 3 }}>
            WIFI: {pc.ssid || '—'}
          </div>
          {pc.label && (
            <div style={{ fontSize: 8, color: 'rgba(0,200,255,0.5)', letterSpacing: '0.15em', marginTop: 3 }}>
              ▸ {pc.label}
            </div>
          )}
        </div>

        {/* Label SSID */}
        <div style={{ fontSize: 7, color: 'rgba(0,148,255,0.32)', letterSpacing: '0.35em', marginBottom: 5 }}>LABEL THIS WIFI</div>
        <div style={{ display: 'flex', gap: 5 }}>
          <input
            value={labelInput}
            onChange={e => setLabelInput(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && saveLabel()}
            placeholder="Home / College / Gym…"
            style={{
              flex: 1, background: 'rgba(0,10,28,0.8)', border: '1px solid rgba(0,148,255,0.15)',
              borderRadius: 2, color: 'rgba(0,200,255,0.8)',
              fontFamily: "'Share Tech Mono'", fontSize: 8, padding: '4px 6px', outline: 'none',
            }}
          />
          <button onClick={saveLabel} style={{
            padding: '4px 10px', background: 'rgba(0,148,255,0.12)',
            border: '1px solid rgba(0,148,255,0.3)', borderRadius: 2,
            color: 'rgba(0,200,255,0.8)', fontFamily: "'Share Tech Mono'",
            fontSize: 8, cursor: 'pointer',
          }}>SAVE</button>
        </div>
      </div>
    </div>
  )
}

// ── SMART HOME WIDGET ─────────────────────────────────────────────────────────

function SmartHomeWidget() {
  const [data,       setData]       = React.useState({})
  const [cmd,        setCmd]        = React.useState('')
  const [msg,        setMsg]        = React.useState({ text: '', ok: true })
  const [acTemp,     setAcTemp]     = React.useState({})      // {deviceId: tempValue}
  const [acStatus,   setAcStatus]   = React.useState({})      // {deviceId: statusString}
  const [stToken,    setStToken]    = React.useState('')
  const [tvIp,       setTvIp]       = React.useState('')
  const [castName,   setCastName]   = React.useState('')
  const [projId,     setProjId]     = React.useState('')
  const [authUrl,    setAuthUrl]    = React.useState('')
  const [authCode,   setAuthCode]   = React.useState('')
  const [showAuth,   setShowAuth]   = React.useState(false)
  const [showNest,   setShowNest]   = React.useState(false)

  const flash = (text, ok = true) => {
    setMsg({ text, ok })
    setTimeout(() => setMsg({ text: '', ok: true }), 4000)
  }

  const refresh = async () => {
    try {
      const r = await fetch(`${BASE}/smarthome/status`)
      const d = await r.json()
      setData(d)
      const s = d.settings || {}
      if (s.smartthings_token && !stToken) setStToken(s.smartthings_token)
      if (s.samsung_tv_ip    && !tvIp)    setTvIp(s.samsung_tv_ip)
      if (s.cast_friendly_name && !castName) setCastName(s.cast_friendly_name)
      if (s.project_id       && !projId)  setProjId(s.project_id)
    } catch {}
  }

  useEffect(() => { refresh() }, [])

  // ── Samsung AC ─────────────────────────────────────────────────
  const acOn  = async (id) => { const d = await _stPost(`smartthings/ac/onoff`, {device_id:id,on:true});  flash(d.message||d.error||'', d.success) }
  const acOff = async (id) => { const d = await _stPost(`smartthings/ac/onoff`, {device_id:id,on:false}); flash(d.message||d.error||'', d.success) }
  const acSetTemp = async (id, mode) => {
    const temp = parseFloat(acTemp[id] || 24)
    const d = await _stPost(`smartthings/ac/temperature`, {device_id:id, temp_c:temp, mode})
    flash(d.message||d.error||'', d.success)
  }
  const acSetMode = async (id, mode) => {
    const d = await _stPost(`smartthings/ac/mode`, {device_id:id, mode})
    flash(d.message||d.error||'', d.success)
  }
  const acSetFan = async (id, speed) => {
    const d = await _stPost(`smartthings/ac/fan`, {device_id:id, speed})
    flash(d.message||d.error||'', d.success)
  }
  const acGetStatus = async (id) => {
    try {
      const r = await fetch(`${BASE}/smarthome/smartthings/devices/${id}/status`)
      const d = await r.json()
      const parts = []
      if (d.power)        parts.push(d.power.toUpperCase())
      if (d.ac_mode)      parts.push(d.ac_mode)
      if (d.current_temp) parts.push(`${d.current_temp}°`)
      if (d.cool_setpoint) parts.push(`→${d.cool_setpoint}°`)
      if (d.fan_speed)    parts.push(`FAN:${d.fan_speed}`)
      setAcStatus(prev => ({...prev, [id]: parts.join(' · ') || 'No data'}))
    } catch {}
  }

  // ── Samsung TV ─────────────────────────────────────────────────
  const tvCtrl = async (action, value) => {
    const d = await _stPost(`samsung/tv/control`, {action, value, ip: tvIp})
    flash(d.message||d.error||'', d.success !== false)
  }

  // ── Chromecast ─────────────────────────────────────────────────
  const castCtrl = async (action, value) => {
    const d = await _stPost(`cast/control`, {action, value, friendly_name: castName})
    flash(d.message||d.error||'', d.success)
    if (d.success) setTimeout(refresh, 1500)
  }

  // ── NL command ─────────────────────────────────────────────────
  const sendCmd = async () => {
    if (!cmd.trim()) return
    flash('Sending…')
    const d = await _stPost(`command`, {command: cmd})
    flash(d.message||d.error||'Done', d.success !== false)
    setCmd('')
    if (d.success) setTimeout(refresh, 1500)
  }

  // ── Nest ───────────────────────────────────────────────────────
  const nestAuthStart = async () => {
    try {
      const r = await fetch(`${BASE}/smarthome/auth/start`)
      const d = await r.json()
      if (d.error) { flash(d.error, false); return }
      setAuthUrl(d.url); setShowAuth(true)
      flash('Open URL in browser, paste code')
    } catch { flash('Backend error', false) }
  }
  const nestAuthComplete = async () => {
    if (!authCode.trim()) { flash('Paste code first', false); return }
    const d = await _stPost(`auth/complete`, {code: authCode.trim()})
    if (d.success) { flash('Nest connected!'); setShowAuth(false); setAuthCode(''); refresh() }
    else flash(d.error||'Auth failed', false)
  }
  const nestDisconnect = async () => {
    await fetch(`${BASE}/smarthome/auth/disconnect`, {method:'POST'})
    flash('Nest disconnected'); refresh()
  }

  // ── Settings ───────────────────────────────────────────────────
  const saveSettings = async () => {
    await fetch(`${BASE}/smarthome/settings`, {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({
        smartthings_token:   stToken,
        samsung_tv_ip:       tvIp,
        cast_friendly_name:  castName,
        project_id:          projId,
      }),
    })
    flash('Settings saved — refreshing…')
    setTimeout(refresh, 500)
  }

  // ── Helper ─────────────────────────────────────────────────────
  async function _stPost(path, body) {
    try {
      const r = await fetch(`${BASE}/smarthome/${path}`, {
        method:'POST', headers:{'Content-Type':'application/json'},
        body: JSON.stringify(body),
      })
      return await r.json()
    } catch { return {success:false, error:'Backend error'} }
  }

  const sdm   = data.sdm         || {}
  const cast  = data.cast        || {}
  const st    = data.smartthings || {}
  const stDev = (st.devices || []).filter(d => d.category === 'ac')
  const tvInfo = data.samsung_tv || {}

  const S = {
    lbl:   { fontFamily:"'Share Tech Mono'", fontSize:8, color:'rgba(0,148,255,0.4)', letterSpacing:'.15em', textTransform:'uppercase', marginBottom:4 },
    row:   { display:'flex', gap:4, flexWrap:'wrap', marginBottom:4 },
    btn:   { flex:1, minWidth:0, background:'rgba(0,148,255,0.08)', border:'1px solid rgba(0,148,255,0.18)', borderRadius:4, color:'rgba(0,148,255,0.8)', fontFamily:"'Share Tech Mono'", fontSize:8, padding:'4px 3px', cursor:'pointer' },
    rbtn:  { flex:'0 0 auto', background:'rgba(255,80,80,0.07)', border:'1px solid rgba(255,80,80,0.2)', borderRadius:4, color:'rgba(255,100,60,0.75)', fontFamily:"'Share Tech Mono'", fontSize:8, padding:'4px 6px', cursor:'pointer' },
    inp:   { background:'rgba(0,10,28,0.8)', border:'1px solid rgba(0,148,255,0.18)', borderRadius:3, color:'rgba(0,200,255,0.85)', fontFamily:"'Share Tech Mono'", fontSize:8, padding:'3px 6px', outline:'none', width:'100%', boxSizing:'border-box' },
    card:  { background:'rgba(0,148,255,0.04)', border:'1px solid rgba(0,148,255,0.1)', borderRadius:5, padding:'7px 9px', marginBottom:5 },
    badge: (ok) => ({ fontFamily:"'Share Tech Mono'", fontSize:7, padding:'1px 6px', borderRadius:3,
      background: ok ? 'rgba(0,200,83,0.1)' : 'rgba(255,80,80,0.08)',
      color:      ok ? '#00c853' : 'rgba(255,80,80,0.55)',
      border:    `1px solid ${ok ? 'rgba(0,200,83,0.25)' : 'rgba(255,80,80,0.18)'}` }),
    sep:   { height:1, margin:'6px 0', background:'rgba(0,148,255,0.07)' },
  }

  return (
    <div>
      <SectionHeader label="SMART HOME" />
      <div style={{ padding: '0 14px 12px' }}>

        {/* NL Command */}
        <div style={{ marginBottom: 8 }}>
          <div style={S.lbl}>COMMAND</div>
          <div style={{ display:'flex', gap:4 }}>
            <input style={{ ...S.inp, flex:1 }} value={cmd} onChange={e => setCmd(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && sendCmd()}
              placeholder="Set AC 22° · TV channel 5 · Volume up…" />
            <button style={{ ...S.btn, flex:'0 0 auto', padding:'3px 8px' }} onClick={sendCmd}>▶</button>
            <button style={{ ...S.btn, flex:'0 0 auto', padding:'3px 8px' }} onClick={refresh}>↻</button>
          </div>
          {msg.text && <div style={{ fontFamily:"'Share Tech Mono'", fontSize:8, marginTop:3,
            color: msg.ok ? 'rgba(0,200,83,0.8)' : 'rgba(255,80,80,0.7)' }}>{msg.text}</div>}
        </div>

        <div style={S.sep} />

        {/* Samsung AC */}
        <div style={{ marginBottom: 8 }}>
          <div style={{ display:'flex', alignItems:'center', justifyContent:'space-between', marginBottom:6 }}>
            <div style={S.lbl}>SAMSUNG AC</div>
            <span style={S.badge(st.connected)}>{st.connected ? 'CONNECTED' : 'NO TOKEN'}</span>
          </div>
          {!st.connected
            ? <div style={{ fontFamily:"'Share Tech Mono'", fontSize:7, color:'rgba(0,148,255,0.25)', textAlign:'center' }}>Set SmartThings token in Settings</div>
            : stDev.length === 0
              ? <div style={{ fontFamily:"'Share Tech Mono'", fontSize:7, color:'rgba(0,148,255,0.25)', textAlign:'center' }}>No AC found in SmartThings</div>
              : stDev.map(d => (
                <div key={d.id} style={S.card}>
                  <div style={{ fontFamily:"'Share Tech Mono'", fontSize:9, color:'rgba(0,148,255,0.85)', fontWeight:600, marginBottom:4 }}>{d.label}</div>
                  {acStatus[d.id] && <div style={{ fontFamily:"'Share Tech Mono'", fontSize:7, color:'rgba(0,200,255,0.6)', marginBottom:4 }}>{acStatus[d.id]}</div>}
                  {/* Temp */}
                  <div style={{ display:'flex', gap:4, marginBottom:4 }}>
                    <input type="number" style={{ ...S.inp, width:55, flex:'none' }} min="16" max="32" step="0.5"
                      value={acTemp[d.id] ?? 24}
                      onChange={e => setAcTemp(prev => ({...prev, [d.id]: e.target.value}))}
                      placeholder="°C" />
                    <button style={S.btn} onClick={() => acSetTemp(d.id,'cool')}>❄ COOL</button>
                    <button style={S.btn} onClick={() => acSetTemp(d.id,'heat')}>🔥 HEAT</button>
                  </div>
                  {/* On/Off + mode */}
                  <div style={S.row}>
                    <button style={S.btn} onClick={() => acOn(d.id)}>ON</button>
                    <button style={S.rbtn} onClick={() => acOff(d.id)}>OFF</button>
                    <button style={S.btn} onClick={() => acSetMode(d.id,'auto')}>AUTO</button>
                    <button style={S.btn} onClick={() => acSetMode(d.id,'dry')}>DRY</button>
                    <button style={S.btn} onClick={() => acSetMode(d.id,'wind')}>FAN</button>
                  </div>
                  {/* Fan speed */}
                  <div style={S.row}>
                    {['auto','low','medium','high','turbo'].map(sp => (
                      <button key={sp} style={{ ...S.btn, fontSize:7 }} onClick={() => acSetFan(d.id, sp)}>{sp.toUpperCase()}</button>
                    ))}
                  </div>
                  <button style={{ ...S.btn, width:'100%', marginTop:2 }} onClick={() => acGetStatus(d.id)}>↻ LIVE STATUS</button>
                </div>
              ))
          }
        </div>

        <div style={S.sep} />

        {/* Samsung TV */}
        <div style={{ marginBottom: 8 }}>
          <div style={{ display:'flex', alignItems:'center', justifyContent:'space-between', marginBottom:4 }}>
            <div style={S.lbl}>SAMSUNG TV</div>
            <span style={S.badge(tvIp && tvInfo.connected)}>
              {tvIp ? (tvInfo.connected ? tvInfo.name || 'ONLINE' : 'OFFLINE') : 'NO IP'}
            </span>
          </div>
          <div style={S.row}>
            <button style={S.btn} onClick={() => tvCtrl('power')}>⏻ POWER</button>
            <button style={S.btn} onClick={() => tvCtrl('mute')}>🔇 MUTE</button>
            <button style={S.btn} onClick={() => tvCtrl('channel_up')}>CH+</button>
            <button style={S.btn} onClick={() => tvCtrl('channel_down')}>CH—</button>
          </div>
          <div style={S.row}>
            <button style={S.btn} onClick={() => tvCtrl('volume_down')}>🔉</button>
            <button style={S.btn} onClick={() => tvCtrl('volume_up')}>🔊</button>
            <button style={S.btn} onClick={() => tvCtrl('key','KEY_HOME')}>HOME</button>
            <button style={S.btn} onClick={() => tvCtrl('key','KEY_RETURN')}>BACK</button>
            <button style={S.btn} onClick={() => tvCtrl('key','KEY_MENU')}>MENU</button>
          </div>
          <div style={{ display:'flex', gap:4 }}>
            <input type="number" style={{ ...S.inp, width:60, flex:'none' }} placeholder="Ch#"
              onKeyDown={e => { if (e.key==='Enter') tvCtrl('set_channel', e.currentTarget.value) }} />
            <button style={S.btn} onClick={(e) => tvCtrl('set_channel', e.currentTarget.previousSibling.value)}>GO</button>
          </div>
        </div>

        <div style={S.sep} />

        {/* Chromecast */}
        <div style={{ marginBottom: 8 }}>
          <div style={S.lbl}>GOOGLE CHROMECAST</div>
          {(cast.devices||[]).length === 0
            ? <div style={{ fontFamily:"'Share Tech Mono'", fontSize:7, color:'rgba(0,148,255,0.25)', textAlign:'center', marginBottom:4 }}>No Chromecast found</div>
            : (cast.devices||[]).map(d => (
              <div key={d.name} style={{ ...S.card, marginBottom:4 }}>
                <div style={{ fontFamily:"'Share Tech Mono'", fontSize:8, color:'rgba(0,148,255,0.8)' }}>{d.name}</div>
                <div style={{ fontFamily:"'Share Tech Mono'", fontSize:7, color:'rgba(0,148,255,0.4)', marginTop:2 }}>
                  VOL {d.volume}% · {d.is_idle ? 'IDLE' : 'ACTIVE'}{d.is_muted ? ' · MUTED' : ''}
                </div>
              </div>
            ))
          }
          <div style={S.row}>
            {[['⏯','play_pause'],['⏹','stop'],['🔇','mute'],['🔉','volume_down'],['🔊','volume_up']].map(([icon, act]) => (
              <button key={act} style={S.btn} onClick={() => castCtrl(act)}>{icon}</button>
            ))}
          </div>
        </div>

        <div style={S.sep} />

        {/* Nest (collapsed toggle) */}
        <div style={{ marginBottom: 8 }}>
          <div style={{ display:'flex', alignItems:'center', gap:6, cursor:'pointer', marginBottom: showNest ? 6 : 0 }}
            onClick={() => setShowNest(!showNest)}>
            <div style={S.lbl}>NEST / SDM</div>
            <span style={{ fontFamily:"'Share Tech Mono'", fontSize:8, color:'rgba(0,148,255,0.25)' }}>{showNest ? '▼' : '▶'}</span>
            <span style={S.badge(sdm.connected)}>{sdm.connected ? 'CONNECTED' : 'NOT CONNECTED'}</span>
          </div>
          {showNest && (
            <div>
              <div style={S.row}>
                <button style={S.btn} onClick={nestAuthStart}>CONNECT</button>
                <button style={S.rbtn} onClick={nestDisconnect}>DISCONNECT</button>
              </div>
              {showAuth && (
                <div style={{ marginTop: 4 }}>
                  <div style={{ fontFamily:"'Share Tech Mono'", fontSize:7, color:'rgba(0,148,255,0.45)', wordBreak:'break-all', marginBottom:4, maxHeight:50, overflowY:'auto' }}>{authUrl}</div>
                  <a href={authUrl} target="_blank" rel="noreferrer" style={{ fontFamily:"'Share Tech Mono'", fontSize:7, color:'rgba(0,200,255,0.55)' }}>Open in browser →</a>
                  <div style={{ display:'flex', gap:4, marginTop:4 }}>
                    <input style={{ ...S.inp, flex:1 }} value={authCode} onChange={e => setAuthCode(e.target.value)} placeholder="Paste code…" />
                    <button style={{ ...S.btn, flex:'0 0 auto', padding:'3px 8px' }} onClick={nestAuthComplete}>OK</button>
                  </div>
                </div>
              )}
            </div>
          )}
        </div>

        <div style={S.sep} />

        {/* Settings */}
        <div>
          <div style={S.lbl}>SETTINGS</div>
          {[
            ['SmartThings Token', stToken, setStToken, 'Personal Access Token…', 'password'],
            ['Samsung TV Local IP', tvIp, setTvIp, '192.168.x.x', 'text'],
            ['Default Chromecast Name', castName, setCastName, 'Living Room TV', 'text'],
            ['Nest SDM Project ID', projId, setProjId, 'enterprises/… (optional)', 'text'],
          ].map(([lbl, val, setter, ph, type]) => (
            <div key={lbl} style={{ marginBottom: 5 }}>
              <div style={{ fontFamily:"'Share Tech Mono'", fontSize:7, color:'rgba(0,148,255,0.35)', marginBottom:2 }}>{lbl}</div>
              <input type={type} style={S.inp} value={val} onChange={e => setter(e.target.value)} placeholder={ph} />
            </div>
          ))}
          <button style={{ ...S.btn, width:'100%', marginTop:4 }} onClick={saveSettings}>SAVE ALL SETTINGS</button>
        </div>

      </div>
    </div>
  )
}

// ── PRINTER WIDGET ────────────────────────────────────────────────────────────

function PrinterWidget() {
  const [printerName,  setPrinterName]  = React.useState('Scanning…')
  const [printerStatus,setPrinterStatus]= React.useState('offline')
  const [jobCount,     setJobCount]     = React.useState(0)
  const [queue,        setQueue]        = React.useState([])   // [{name, path, preview}]
  const [prefs,        setPrefs]        = React.useState({ color_mode: 'color', dpi: 600, pages: 'all', margin_mm: 15 })
  const [printing,     setPrinting]     = React.useState(false)
  const [feedback,     setFeedback]     = React.useState('')
  const [preview,      setPreview]      = React.useState(null)
  const fileRef = React.useRef()

  const isOnline = ['ready', 'busy'].includes(printerStatus)

  async function loadStatus() {
    try {
      const r = await fetch(`${BASE}/print/status`).then(x => x.json())
      if (r.ok) {
        setPrinterName(r.name || 'No printer')
        setPrinterStatus(r.status || 'offline')
        setJobCount(r.jobs_count || 0)
      }
    } catch {}
  }

  async function savePref(key, value) {
    const next = { ...prefs, [key]: value }
    setPrefs(next)
    try {
      await fetch(`${BASE}/print/settings`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ [key]: value }),
      })
    } catch {}
  }

  async function addFiles(e) {
    const files = Array.from(e.target.files); if (!files.length) return
    e.target.value = ''
    for (const f of files) {
      const form = new FormData(); form.append('file', f)
      try {
        const r = await fetch(`${BASE}/upload`, { method: 'POST', body: form }).then(x => x.json())
        if (r.ok && r.path) {
          let pv = null
          try {
            const pr = await fetch(`${BASE}/print/preview`, {
              method: 'POST', headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ path: r.path }),
            }).then(x => x.json())
            pv = pr.preview || null
          } catch {}
          setQueue(q => [...q, { name: f.name, path: r.path, preview: pv }])
        }
      } catch {}
    }
  }

  function showPreview(item) {
    setPreview(item)
  }

  async function printAll() {
    if (!queue.length) return
    setPrinting(true); setFeedback('')
    try {
      const r = await fetch(`${BASE}/print/job`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ files: queue.map(f => f.path), overrides: prefs }),
      }).then(x => x.json())
      if (r.ok) { setFeedback(`✓ Sent ${queue.length} file(s)`); setQueue([]); setPreview(null) }
      else       { setFeedback('Print failed — check printer') }
    } catch { setFeedback('Backend error') }
    setPrinting(false)
  }

  React.useEffect(() => { loadStatus(); const t = setInterval(loadStatus, 30000); return () => clearInterval(t) }, [])

  const statusColor = isOnline ? '#1db954' : '#ff3d3d'
  const btnBase = { background: 'transparent', border: '1px solid #0d2a3a', borderRadius: 3, fontFamily: "'Share Tech Mono'", fontSize: 7, letterSpacing: '0.1em', cursor: 'pointer', padding: '2px 6px' }

  return (
    <div>
      <SectionHeader label="PRINTER" />
      <div style={{ padding: '0 16px 12px' }}>

        {/* Printer status */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 4 }}>
          <div style={{ width: 7, height: 7, borderRadius: '50%', background: statusColor, boxShadow: `0 0 5px ${statusColor}`, flexShrink: 0 }} />
          <span style={{ fontFamily: "'JetBrains Mono'", fontSize: 9, color: '#c8e8f0', flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
            {printerName}
          </span>
          <span style={{ fontFamily: "'Share Tech Mono'", fontSize: 7, color: statusColor, letterSpacing: '0.15em', flexShrink: 0 }}>
            {printerStatus.toUpperCase()}
          </span>
        </div>
        <div style={{ fontFamily: "'Share Tech Mono'", fontSize: 7, color: '#3a6070', letterSpacing: '0.15em', marginBottom: 8 }}>
          QUEUE: {jobCount} JOB{jobCount !== 1 ? 'S' : ''}
        </div>

        {/* Print settings */}
        <div style={{ background: '#050d1a', border: '1px solid #0d2a3a', borderRadius: 3, padding: '6px 8px', marginBottom: 8 }}>
          {/* Color mode */}
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 5 }}>
            <span style={{ fontFamily: "'Share Tech Mono'", fontSize: 7, color: '#3a6070', letterSpacing: '0.1em' }}>COLOR</span>
            <div style={{ display: 'flex', gap: 3 }}>
              {['color', 'bw'].map(m => (
                <button key={m} onClick={() => savePref('color_mode', m)} style={{
                  ...btnBase,
                  color: prefs.color_mode === m ? '#00e5ff' : '#3a6070',
                  borderColor: prefs.color_mode === m ? '#00e5ff44' : '#0d2a3a',
                  background: prefs.color_mode === m ? 'rgba(0,229,255,0.08)' : 'transparent',
                }}>{m === 'color' ? 'COLOR' : 'B&W'}</button>
              ))}
            </div>
          </div>
          {/* DPI */}
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 5 }}>
            <span style={{ fontFamily: "'Share Tech Mono'", fontSize: 7, color: '#3a6070', letterSpacing: '0.1em' }}>DPI</span>
            <div style={{ display: 'flex', gap: 3 }}>
              {[120, 300, 600].map(d => (
                <button key={d} onClick={() => savePref('dpi', d)} style={{
                  ...btnBase,
                  color: prefs.dpi === d ? '#00e5ff' : '#3a6070',
                  borderColor: prefs.dpi === d ? '#00e5ff44' : '#0d2a3a',
                  background: prefs.dpi === d ? 'rgba(0,229,255,0.08)' : 'transparent',
                }}>{d}</button>
              ))}
            </div>
          </div>
          {/* Pages */}
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
            <span style={{ fontFamily: "'Share Tech Mono'", fontSize: 7, color: '#3a6070', letterSpacing: '0.1em' }}>PAGES</span>
            <div style={{ display: 'flex', gap: 3 }}>
              {['all', 'odd', 'even'].map(p => (
                <button key={p} onClick={() => savePref('pages', p)} style={{
                  ...btnBase,
                  color: prefs.pages === p ? '#00e5ff' : '#3a6070',
                  borderColor: prefs.pages === p ? '#00e5ff44' : '#0d2a3a',
                  background: prefs.pages === p ? 'rgba(0,229,255,0.08)' : 'transparent',
                }}>{p.toUpperCase()}</button>
              ))}
            </div>
          </div>
        </div>

        {/* File queue */}
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 4 }}>
          <span style={{ fontFamily: "'Share Tech Mono'", fontSize: 7, color: '#3a6070', letterSpacing: '0.15em' }}>
            QUEUE · {queue.length} FILE{queue.length !== 1 ? 'S' : ''}
          </span>
          <label style={{
            padding: '2px 8px', background: 'rgba(0,229,255,0.07)',
            border: '1px solid #0d2a3a', borderRadius: 3,
            color: '#3a6070', fontFamily: "'Share Tech Mono'",
            fontSize: 7, letterSpacing: '0.1em', cursor: 'pointer',
          }}>
            + ADD
            <input ref={fileRef} type="file" multiple
              accept=".pdf,.docx,.doc,.txt,.jpg,.jpeg,.png"
              style={{ display: 'none' }} onChange={addFiles} />
          </label>
        </div>

        {/* File list */}
        <div style={{
          minHeight: 32, maxHeight: 90, overflowY: 'auto',
          background: '#050d1a', border: '1px solid #0d2a3a',
          borderRadius: 3, marginBottom: 6,
        }}>
          {queue.length === 0 ? (
            <div style={{ padding: '8px', fontFamily: "'Share Tech Mono'", fontSize: 7, color: '#1a4a5a', letterSpacing: '0.1em', textAlign: 'center' }}>
              NO FILES QUEUED
            </div>
          ) : queue.map((f, i) => (
            <div key={i} onClick={() => showPreview(f)} style={{
              display: 'flex', alignItems: 'center', gap: 5,
              padding: '4px 6px', borderBottom: '1px solid #050d1a',
              cursor: 'pointer',
            }}
              onMouseEnter={e => e.currentTarget.style.background = '#0a1628'}
              onMouseLeave={e => e.currentTarget.style.background = 'transparent'}
            >
              <span style={{ fontFamily: "'JetBrains Mono'", fontSize: 8, color: '#60b8d0', flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                {f.name}
              </span>
              <button onClick={e => { e.stopPropagation(); setQueue(q => q.filter((_, j) => j !== i)); if (preview?.name === f.name) setPreview(null) }} style={{
                background: 'none', border: 'none', color: '#ff3d3d55',
                cursor: 'pointer', fontSize: 10, padding: '0 2px',
              }}>✕</button>
            </div>
          ))}
        </div>

        {/* Preview */}
        {preview && (
          <div style={{ background: '#050d1a', border: '1px solid #0d2a3a', borderRadius: 3, padding: 6, marginBottom: 6, textAlign: 'center' }}>
            {preview.preview && preview.preview.length > 100 && !preview.preview.startsWith('pdf:') && !preview.preview.startsWith('docx:') ? (
              <img src={`data:image/png;base64,${preview.preview}`}
                style={{ maxWidth: '100%', maxHeight: 100, borderRadius: 2, border: '1px solid #0d2a3a' }} />
            ) : (
              <div style={{ padding: '8px 0', fontFamily: "'Share Tech Mono'", fontSize: 8, color: '#3a6070', letterSpacing: '0.1em', lineHeight: 1.8 }}>
                <div style={{ fontSize: 18, marginBottom: 4 }}>
                  {preview.name.endsWith('.pdf') ? '📄' : preview.name.match(/\.(jpg|jpeg|png)$/i) ? '🖼' : '📝'}
                </div>
                {preview.name}
                {preview.preview?.startsWith('pdf:') && ` · ${preview.preview.split(':')[1]} pages`}
              </div>
            )}
          </div>
        )}

        {/* Feedback */}
        {feedback && (
          <div style={{ fontFamily: "'Share Tech Mono'", fontSize: 7, color: feedback.startsWith('✓') ? '#1db954' : '#ff3d3d', letterSpacing: '0.1em', marginBottom: 6, textAlign: 'center' }}>
            {feedback}
          </div>
        )}

        {/* Print + clear buttons */}
        <div style={{ display: 'flex', gap: 4 }}>
          <button onClick={printAll} disabled={printing || !queue.length} style={{
            flex: 1, padding: '5px 0',
            background: queue.length ? 'rgba(0,229,255,0.1)' : 'transparent',
            border: `1px solid ${queue.length ? '#00e5ff44' : '#0d2a3a'}`,
            borderRadius: 3, color: queue.length ? '#00e5ff' : '#1a4a5a',
            fontFamily: "'Share Tech Mono'", fontSize: 8, letterSpacing: '0.15em',
            cursor: queue.length ? 'pointer' : 'default',
          }}>
            {printing ? '⎙ PRINTING…' : '⎙ PRINT ALL'}
          </button>
          <button onClick={() => { setQueue([]); setPreview(null); setFeedback('') }} style={{
            padding: '5px 10px', background: 'transparent',
            border: '1px solid #ff3d3d33', borderRadius: 3,
            color: '#ff3d3d55', fontFamily: "'Share Tech Mono'",
            fontSize: 8, cursor: 'pointer',
          }}>✕</button>
        </div>
      </div>
    </div>
  )
}

// ─────────────────────────────────────────────────────────────────────────────
// Right panel modular widget system
// ─────────────────────────────────────────────────────────────────────────────

const RP_ALL_WIDGETS = [
  { id: 'spotify',   label: 'SPOTIFY',          defaultOn: true  },
  { id: 'fitness',   label: 'GOOGLE FIT',        defaultOn: true  },
  { id: 'location',  label: 'LOCATION',          defaultOn: true  },
  { id: 'smarthome', label: 'SMART HOME',        defaultOn: true  },
  { id: 'printer',   label: 'PRINTER',           defaultOn: true  },
  { id: 'ocr',       label: 'DOCUMENT OCR',      defaultOn: true  },
  { id: 'devices',   label: 'DEVICES',           defaultOn: true  },
  { id: 'calendar',  label: 'CALENDAR',          defaultOn: true  },
  { id: 'phone',     label: 'PHONE',             defaultOn: true  },
  { id: 'whatsapp',  label: 'WHATSAPP',          defaultOn: true  },
  { id: 'notifs',    label: 'NOTIFICATIONS',     defaultOn: false },
  { id: 'relgraph',  label: 'RELATIONSHIP',      defaultOn: false },
  { id: 'terminal',  label: 'TERMINAL',          defaultOn: true  },
  { id: 'syslog',    label: 'SYSTEM LOG',        defaultOn: false },
]

const RP_LS_ORDER     = 'rp_widget_order_v1'
const RP_LS_ENABLED   = 'rp_widget_enabled_v1'
const RP_LS_COLLAPSED = 'rp_widget_collapsed_v1'

function rpLoadOrder() {
  try {
    const saved = JSON.parse(localStorage.getItem(RP_LS_ORDER) || '[]')
    const allIds = RP_ALL_WIDGETS.map(w => w.id)
    const savedSet = new Set(saved)
    return [...saved.filter(id => allIds.includes(id)), ...allIds.filter(id => !savedSet.has(id))]
  } catch { return RP_ALL_WIDGETS.map(w => w.id) }
}

function rpLoadEnabled() {
  try {
    const saved = JSON.parse(localStorage.getItem(RP_LS_ENABLED) || '{}')
    const out = {}
    RP_ALL_WIDGETS.forEach(w => { out[w.id] = w.id in saved ? saved[w.id] : w.defaultOn })
    return out
  } catch {
    const out = {}
    RP_ALL_WIDGETS.forEach(w => { out[w.id] = w.defaultOn })
    return out
  }
}

function rpLoadCollapsed() {
  try { return JSON.parse(localStorage.getItem(RP_LS_COLLAPSED) || '{}') }
  catch { return {} }
}

// Collapsible widget wrapper for right panel
function RpWidget({ id, label, collapsed, onToggle, children }) {
  return (
    <div style={{ flexShrink: 0 }}>
      <div
        onClick={() => onToggle(id)}
        style={{
          display: 'flex', alignItems: 'center', gap: 5,
          padding: '8px 12px 4px', cursor: 'pointer', userSelect: 'none',
        }}
        title={collapsed ? 'Expand' : 'Collapse'}
      >
        <span style={{ color: '#00e5ff', fontSize: 9, flexShrink: 0 }}>*</span>
        <span style={{
          color: '#00e5ff', fontFamily: "'Share Tech Mono'",
          fontSize: '10px', letterSpacing: '0.2em', flexShrink: 0,
        }}>
          {label}
        </span>
        <div style={{ flex: 1, height: 1, background: '#0d2a3a', marginLeft: 5 }} />
        <span style={{ color: '#1a4a5a', fontSize: 9, flexShrink: 0, marginLeft: 4 }}>
          {collapsed ? '›' : '‹'}
        </span>
      </div>
      {!collapsed && children}
    </div>
  )
}

// Settings / reorder panel for right panel
function RpSettings({ order, enabled, onSave, onClose }) {
  const [localOrder,   setLocalOrder]   = React.useState([...order])
  const [localEnabled, setLocalEnabled] = React.useState({ ...enabled })
  const dragIdx     = React.useRef(null)
  const dragOverIdx = React.useRef(null)

  function onDragStart(e, i) { dragIdx.current = i; e.dataTransfer.effectAllowed = 'move'; e.currentTarget.style.opacity = '0.5' }
  function onDragEnd(e)       { e.currentTarget.style.opacity = '1' }
  function onDragOver(e, i)   { e.preventDefault(); dragOverIdx.current = i }
  function onDrop(e) {
    e.preventDefault()
    const from = dragIdx.current, to = dragOverIdx.current
    if (from === null || to === null || from === to) return
    const next = [...localOrder]; const [moved] = next.splice(from, 1); next.splice(to, 0, moved)
    setLocalOrder(next); dragIdx.current = null; dragOverIdx.current = null
  }

  const idToLabel = Object.fromEntries(RP_ALL_WIDGETS.map(w => [w.id, w.label]))

  return (
    <div style={{ flex: 1, overflowY: 'auto', padding: '10px 0' }}>
      <div style={{ padding: '0 10px 8px', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <span style={{ color: '#00e5ff', fontFamily: "'Share Tech Mono'", fontSize: '9px', letterSpacing: '0.2em' }}>PANEL WIDGETS</span>
        <button onClick={() => { onSave(localOrder, localEnabled); onClose() }} style={{ background: 'rgba(0,229,255,0.1)', border: '1px solid rgba(0,229,255,0.35)', borderRadius: 3, color: '#00e5ff', fontFamily: "'Share Tech Mono'", fontSize: 7, padding: '3px 8px', cursor: 'pointer' }}>SAVE</button>
      </div>
      <div style={{ padding: '0 10px 8px', fontSize: 7, color: '#1a4a5a', fontFamily: "'Share Tech Mono'", letterSpacing: '0.12em' }}>
        DRAG TO REORDER · TOGGLE SHOW/HIDE
      </div>
      {localOrder.map((id, i) => (
        <div
          key={id} draggable
          onDragStart={e => onDragStart(e, i)} onDragEnd={onDragEnd}
          onDragOver={e => onDragOver(e, i)} onDrop={onDrop}
          style={{ display: 'flex', alignItems: 'center', gap: 7, padding: '6px 10px', borderBottom: '1px solid #0d2a3a', cursor: 'grab', userSelect: 'none', transition: 'background 0.1s' }}
          onMouseEnter={e => { e.currentTarget.style.background = 'rgba(0,229,255,0.04)' }}
          onMouseLeave={e => { e.currentTarget.style.background = 'transparent' }}
        >
          <span style={{ color: '#1a4a5a', fontSize: 11, flexShrink: 0 }}>⠿</span>
          <span style={{ flex: 1, color: localEnabled[id] ? '#c8e8f0' : '#1a4a5a', fontFamily: "'Share Tech Mono'", fontSize: 8, letterSpacing: '0.1em', transition: 'color 0.2s' }}>
            {idToLabel[id] || id}
          </span>
          <div onClick={() => setLocalEnabled(p => ({ ...p, [id]: !p[id] }))} style={{ width: 26, height: 13, borderRadius: 7, cursor: 'pointer', position: 'relative', flexShrink: 0, background: localEnabled[id] ? 'rgba(0,229,255,0.2)' : 'rgba(13,42,58,0.8)', border: `1px solid ${localEnabled[id] ? '#00e5ff55' : '#0d2a3a'}`, transition: 'all 0.2s' }}>
            <div style={{ position: 'absolute', top: 2, left: localEnabled[id] ? 11 : 2, width: 7, height: 7, borderRadius: '50%', background: localEnabled[id] ? '#00e5ff' : '#1a4a5a', transition: 'left 0.2s' }} />
          </div>
        </div>
      ))}
      <div style={{ padding: '10px 10px 4px', display: 'flex', justifyContent: 'center' }}>
        <button onClick={onClose} style={{ background: 'transparent', border: '1px solid #0d2a3a', borderRadius: 3, color: '#3a6070', fontFamily: "'Share Tech Mono'", fontSize: 7, padding: '3px 12px', cursor: 'pointer' }}>CANCEL</button>
      </div>
    </div>
  )
}

export default function RightPanel({ waStatus, mmaStatus, spotifyTrack, notifications, whatsappQr, androidDevices = [], calendarEvents = [], onCalendarUpdate, shellConfirm, setShellConfirm, shellOutput, setShellOutput }) {
  const [panelCollapsed, setPanelCollapsed] = React.useState(false)
  const [settingsOpen,   setSettingsOpen]   = React.useState(false)

  const [widgetOrder,     setWidgetOrder]     = React.useState(rpLoadOrder)
  const [widgetEnabled,   setWidgetEnabled]   = React.useState(rpLoadEnabled)
  const [widgetCollapsed, setWidgetCollapsed] = React.useState(rpLoadCollapsed)

  const toggleWidget = (id) => {
    const next = { ...widgetCollapsed, [id]: !widgetCollapsed[id] }
    setWidgetCollapsed(next)
    localStorage.setItem(RP_LS_COLLAPSED, JSON.stringify(next))
  }

  const saveSettings = (order, enabled) => {
    setWidgetOrder(order); setWidgetEnabled(enabled)
    localStorage.setItem(RP_LS_ORDER,   JSON.stringify(order))
    localStorage.setItem(RP_LS_ENABLED, JSON.stringify(enabled))
  }

  const renderWidget = (id) => {
    if (!widgetEnabled[id]) return null
    const collapsed = !!widgetCollapsed[id]
    const label = (RP_ALL_WIDGETS.find(w => w.id === id) || {}).label || id

    const content = (() => {
      switch (id) {
        case 'spotify':   return <SpotifyPanel track={spotifyTrack} />
        case 'fitness':   return <FitnessWidget />
        case 'location':  return <LocationWidget />
        case 'smarthome': return <SmartHomeWidget />
        case 'printer':   return <PrinterWidget />
        case 'ocr':       return <OCRWidget />
        case 'devices':   return <DevicesWidget />
        case 'calendar':  return <CalendarPanel events={calendarEvents} onCalendarUpdate={onCalendarUpdate} />
        case 'phone':     return <MmaPanel mmaStatus={mmaStatus} androidDevices={androidDevices} />
        case 'whatsapp':  return <WhatsAppPanel status={waStatus} qr={whatsappQr} />
        case 'notifs':    return <NotificationsPanel notifications={notifications} />
        case 'relgraph':  return <RelationshipGraph />
        case 'terminal':  return (
          <>
            <ShellInput />
            {shellOutput && <TerminalPanel shellOutput={shellOutput} onClear={() => setShellOutput(null)} />}
          </>
        )
        case 'syslog':    return <SystemLog errors={[]} />
        default: return null
      }
    })()

    if (!content) return null

    return (
      <React.Fragment key={id}>
        <RpWidget id={id} label={label} collapsed={collapsed} onToggle={toggleWidget}>
          {content}
        </RpWidget>
        <Divider />
      </React.Fragment>
    )
  }

  return (
    <>
      <ShellConfirmModal shellConfirm={shellConfirm} onDismiss={() => setShellConfirm(null)} />
      <div style={{
        width: panelCollapsed ? 36 : 220,
        transition: 'width 0.28s cubic-bezier(0.22,1,0.36,1)',
        height: '100%', overflow: 'hidden',
        background: '#0a1628', borderLeft: '1px solid #0d2a3a',
        display: 'flex', flexDirection: 'column', flexShrink: 0,
      }}>
        {/* Panel header */}
        <div style={{
          display: 'flex', alignItems: 'center', gap: 6,
          padding: '10px 8px', borderBottom: '1px solid #0d2a3a',
          flexShrink: 0, minWidth: 36,
        }}>
          {!panelCollapsed && (
            <>
              <span style={{ color: '#00e5ff', fontFamily: "'Share Tech Mono'", fontSize: '10px', letterSpacing: '0.18em', flex: 1, whiteSpace: 'nowrap' }}>
                MODULES
              </span>
              <button
                onClick={() => setSettingsOpen(s => !s)}
                title="Widget settings"
                style={{ background: 'transparent', border: 'none', color: settingsOpen ? '#00e5ff' : 'rgba(0,229,255,0.35)', fontSize: '12px', cursor: 'pointer', padding: '2px 4px', flexShrink: 0, transition: 'color 0.15s' }}
                onMouseEnter={e => { e.currentTarget.style.color = '#00e5ff' }}
                onMouseLeave={e => { if (!settingsOpen) e.currentTarget.style.color = 'rgba(0,229,255,0.35)' }}
              >⚙</button>
            </>
          )}
          <button
            onClick={() => setPanelCollapsed(!panelCollapsed)}
            title={panelCollapsed ? 'Expand panel' : 'Collapse panel'}
            style={{ background: 'transparent', border: 'none', color: 'rgba(0,229,255,0.5)', fontFamily: "'Share Tech Mono'", fontSize: '14px', cursor: 'pointer', lineHeight: 1, padding: '2px 4px', flexShrink: 0, transition: 'color 0.15s' }}
            onMouseEnter={e => { e.currentTarget.style.color = '#00e5ff' }}
            onMouseLeave={e => { e.currentTarget.style.color = 'rgba(0,229,255,0.5)' }}
          >
            {panelCollapsed ? '‹' : '›'}
          </button>
        </div>

        {/* Content */}
        <div style={{
          flex: 1, overflowY: 'auto', overflowX: 'hidden',
          opacity: panelCollapsed ? 0 : 1,
          pointerEvents: panelCollapsed ? 'none' : 'auto',
          transition: 'opacity 0.18s ease',
          display: 'flex', flexDirection: 'column',
        }}>
          {settingsOpen
            ? <RpSettings order={widgetOrder} enabled={widgetEnabled} onSave={saveSettings} onClose={() => setSettingsOpen(false)} />
            : widgetOrder.map(id => renderWidget(id))
          }
        </div>
      </div>
    </>
  )
}