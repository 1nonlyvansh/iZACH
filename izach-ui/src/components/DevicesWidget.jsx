import React, { useState, useEffect, useCallback } from 'react'

const BASE = 'http://localhost:5050'

// ── Registered nodes ─────────────────────────────────────────
// Add more nodes here as the setup grows
const NODES = [
  { id: 'alliednode 2', label: 'AlliedNode 2', ip: '192.168.0.137' },
]

function vitalColor(v) {
  if (v > 85) return '#ff3d3d'
  if (v > 65) return '#ffb300'
  return '#00e5ff'
}

function MiniBar({ value, color }) {
  return (
    <div style={{ height: 3, background: '#0d2a3a', borderRadius: 2, overflow: 'hidden', flex: 1 }}>
      <div style={{
        height: '100%', width: `${Math.min(100, value || 0)}%`,
        background: color, borderRadius: 2,
        transition: 'width 0.6s ease',
        boxShadow: `0 0 4px ${color}66`,
      }} />
    </div>
  )
}

function VitalRow({ label, value }) {
  const color = vitalColor(value)
  return (
    <div style={{ marginBottom: 6 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 2 }}>
        <span style={{ color: '#3a6070', fontFamily: "'JetBrains Mono'", fontSize: '9px' }}>{label}</span>
        <span style={{ color, fontFamily: "'Share Tech Mono'", fontSize: '9px' }}>{value ?? '—'}%</span>
      </div>
      <MiniBar value={value} color={color} />
    </div>
  )
}

function SliderRow({ label, value, onChange, onRelease }) {
  return (
    <div style={{ marginBottom: 8 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 3 }}>
        <span style={{ color: '#3a6070', fontFamily: "'JetBrains Mono'", fontSize: '9px' }}>{label}</span>
        <span style={{ color: '#00e5ff', fontFamily: "'Share Tech Mono'", fontSize: '9px' }}>{value}%</span>
      </div>
      <input
        type="range" min="0" max="100" value={value}
        onChange={e => onChange(Number(e.target.value))}
        onMouseUp={e => onRelease(Number(e.target.value))}
        onTouchEnd={e => onRelease(Number(e.target.value))}
        style={{ width: '100%', accentColor: '#00e5ff', cursor: 'pointer', height: 3 }}
      />
    </div>
  )
}

function NodeCard({ node }) {
  const [expanded, setExpanded] = useState(false)
  const [vitals,   setVitals]   = useState(null)
  const [online,   setOnline]   = useState(undefined)
  const [volume,   setVolume]   = useState(50)
  const [bright,   setBright]   = useState(50)
  const [busy,     setBusy]     = useState(null)

  const fetchVitals = useCallback(async () => {
    try {
      const r = await fetch(`${BASE}/nodes/vitals?node=${encodeURIComponent(node.id)}`)
      const d = await r.json()
      if (d.ok) { setVitals(d.vitals); setOnline(true) }
      else setOnline(false)
    } catch { setOnline(false) }
  }, [node.id])

  useEffect(() => {
    fetchVitals()
    const t = setInterval(fetchVitals, 12000)
    return () => clearInterval(t)
  }, [fetchVitals])

  useEffect(() => {
    if (expanded) fetchVitals()
  }, [expanded, fetchVitals])

  async function control(action, value = null) {
    setBusy(action)
    try {
      await fetch(`${BASE}/nodes/control`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ node: node.id, action, value }),
      })
    } catch {}
    setBusy(null)
  }

  const dot = online === undefined ? '#3a6070' : online ? '#00e5ff' : '#ff3d3d'
  const statusText = online === undefined ? '···' : online ? 'ONLINE' : 'OFFLINE'
  const statusColor = online ? '#00e5ff' : '#ff3d3d'

  return (
    <div style={{ margin: '0 10px 6px' }}>
      {/* ── Node row ─────────────────────────────── */}
      <div
        onClick={() => setExpanded(e => !e)}
        style={{
          display: 'flex', alignItems: 'center', gap: 8,
          padding: '7px 10px', borderRadius: expanded ? '4px 4px 0 0' : 4,
          cursor: 'pointer',
          background: expanded ? '#0d2a3a' : 'rgba(13,42,58,0.4)',
          border: `1px solid ${expanded ? '#1a4a5a' : '#0d2a3a'}`,
          borderBottom: expanded ? '1px solid #050d1a' : undefined,
          transition: 'all 0.2s ease',
          userSelect: 'none',
        }}
      >
        <div style={{
          width: 7, height: 7, borderRadius: '50%', flexShrink: 0,
          background: dot,
          boxShadow: online ? `0 0 7px ${dot}` : 'none',
          transition: 'all 0.4s ease',
        }} />
        <span style={{ color: '#c8e8f0', fontFamily: "'JetBrains Mono'", fontSize: '10px', flex: 1 }}>
          {node.label}
        </span>
        <span style={{ color: statusColor, fontFamily: "'Share Tech Mono'", fontSize: '8px', letterSpacing: '0.1em' }}>
          {statusText}
        </span>
        <span style={{ color: '#3a6070', fontSize: '9px', marginLeft: 4 }}>
          {expanded ? '▲' : '▼'}
        </span>
      </div>

      {/* ── Dropdown ─────────────────────────────── */}
      <div style={{
        overflow: 'hidden',
        maxHeight: expanded ? '500px' : '0px',
        opacity: expanded ? 1 : 0,
        transition: 'max-height 0.35s cubic-bezier(0.22,1,0.36,1), opacity 0.2s ease',
      }}>
        <div style={{
          background: '#050d1a',
          border: '1px solid #1a4a5a', borderTop: 'none',
          borderRadius: '0 0 4px 4px',
          padding: '10px 10px 8px',
        }}>

          {/* Vitals */}
          <div style={{ marginBottom: 8 }}>
            <span style={{
              color: '#1a4a5a', fontFamily: "'Share Tech Mono'",
              fontSize: '8px', letterSpacing: '0.15em',
            }}>VITALS</span>
            <div style={{ marginTop: 7 }}>
              {vitals ? (
                <>
                  <VitalRow label="CPU" value={vitals.cpu_percent} />
                  <VitalRow label="RAM" value={vitals.ram_percent} />
                  <VitalRow label="DISK" value={vitals.disk_percent} />
                  <div style={{ color: '#1a4a5a', fontFamily: "'JetBrains Mono'", fontSize: '8px', marginTop: 3 }}>
                    RAM {vitals.ram_used_gb}/{vitals.ram_total_gb} GB
                    &nbsp;·&nbsp;
                    Disk {vitals.disk_used_gb}/{vitals.disk_total_gb} GB
                  </div>
                </>
              ) : (
                <div style={{ color: '#1a4a5a', fontFamily: "'JetBrains Mono'", fontSize: '9px' }}>
                  {online ? 'Loading...' : 'Device offline — no data'}
                </div>
              )}
            </div>
          </div>

          <div style={{ height: 1, background: '#0d2a3a', margin: '8px 0' }} />

          {/* Volume + Brightness */}
          <SliderRow
            label="VOLUME"
            value={volume}
            onChange={setVolume}
            onRelease={v => control('volume', v)}
          />
          <SliderRow
            label="BRIGHTNESS"
            value={bright}
            onChange={setBright}
            onRelease={v => control('brightness', v)}
          />

          <div style={{ height: 1, background: '#0d2a3a', margin: '8px 0' }} />

          {/* Media */}
          <div style={{ marginBottom: 8 }}>
            <span style={{
              color: '#1a4a5a', fontFamily: "'Share Tech Mono'",
              fontSize: '8px', letterSpacing: '0.15em',
            }}>MEDIA</span>
            <div style={{ display: 'flex', gap: 5, marginTop: 6 }}>
              {[['⏮', 'media_prev'], ['⏯', 'media_play_pause'], ['⏭', 'media_next']].map(([icon, action]) => (
                <button key={action} onClick={() => control(action)}
                  disabled={busy === action}
                  style={{
                    flex: 1, background: '#0d2a3a',
                    border: '1px solid #1a4a5a', borderRadius: 4,
                    color: busy === action ? '#1a4a5a' : '#00e5ff',
                    fontSize: '13px', cursor: 'pointer', padding: '5px 0',
                    transition: 'all 0.15s',
                  }}>
                  {icon}
                </button>
              ))}
            </div>
          </div>

          <div style={{ height: 1, background: '#0d2a3a', margin: '8px 0' }} />

          {/* Power */}
          <div>
            <span style={{
              color: '#1a4a5a', fontFamily: "'Share Tech Mono'",
              fontSize: '8px', letterSpacing: '0.15em',
            }}>POWER</span>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 4, marginTop: 6 }}>
              {[
                ['Lock',     'lock',     '#4a90a4'],
                ['Sleep',    'sleep',    '#4a90a4'],
                ['Restart',  'restart',  '#ffb300'],
                ['Shutdown', 'shutdown', '#ff3d3d'],
              ].map(([label, action, color]) => (
                <button
                  key={action}
                  onClick={() => control(action)}
                  disabled={busy === action}
                  style={{
                    background: 'transparent',
                    border: `1px solid ${color}55`,
                    borderRadius: 4, color: busy === action ? '#1a4a5a' : color,
                    fontSize: '9px', cursor: 'pointer', padding: '6px 4px',
                    fontFamily: "'JetBrains Mono'",
                    transition: 'background 0.15s, color 0.15s',
                  }}
                  onMouseEnter={e => { e.currentTarget.style.background = `${color}22` }}
                  onMouseLeave={e => { e.currentTarget.style.background = 'transparent' }}
                >
                  {busy === action ? '···' : label}
                </button>
              ))}
            </div>
          </div>

        </div>
      </div>
    </div>
  )
}

export default function DevicesWidget() {
  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '10px 16px 8px' }}>
        <span style={{ color: '#00e5ff' }}>*</span>
        <span style={{
          color: '#00e5ff', fontFamily: "'Share Tech Mono'",
          fontSize: '10px', letterSpacing: '0.2em',
        }}>DEVICES</span>
        <div style={{ flex: 1, height: 1, background: '#0d2a3a' }} />
      </div>
      {NODES.map(n => <NodeCard key={n.id} node={n} />)}
    </div>
  )
}
