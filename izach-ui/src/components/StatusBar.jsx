import React, { useState, useEffect } from 'react'

const CACHE_ITEMS = [
  {
    id: 'temp',
    label: 'Temp Files',
    desc: '/temp/ directory files',
    warning: null,
    defaultChecked: true,
  },
  {
    id: 'realtime',
    label: 'Realtime Data Cache',
    desc: 'In-memory price / weather / news cache',
    warning: null,
    defaultChecked: true,
  },
  {
    id: 'msglog',
    label: 'Message Log',
    desc: 'In-memory UI chat history (this session)',
    warning: null,
    defaultChecked: false,
  },
  {
    id: 'screenshots',
    label: 'Screenshots',
    desc: 'All JPEG files in /screenshots/',
    warning: 'Permanently deletes all captured screenshots. Cannot be undone.',
    defaultChecked: false,
  },
  {
    id: 'context',
    label: 'Context History',
    desc: 'iZACH conversation memory & entity store',
    warning: 'Clears all conversation context. iZACH will forget recent session history.',
    defaultChecked: false,
  },
  {
    id: 'wwebjs_cache',
    label: 'WhatsApp Browser Cache',
    desc: '.wwebjs_cache/ — Puppeteer browser data',
    warning: 'This may force WhatsApp to show the QR code again and require re-login.',
    defaultChecked: false,
  },
  {
    id: 'spotify_cache',
    label: 'Spotify OAuth Token',
    desc: '.cache/ — Spotify authentication token',
    warning: 'Spotify will require full browser re-authentication after this.',
    defaultChecked: false,
  },
]

function CacheModal({ onClose }) {
  const [selected, setSelected] = useState(() =>
    Object.fromEntries(CACHE_ITEMS.map(i => [i.id, i.defaultChecked]))
  )
  const [clearing, setClearing] = useState(false)
  const [sizes, setSizes] = useState({})

  useEffect(() => {
    fetch('http://localhost:5050/cache/sizes')
      .then(r => r.json())
      .then(d => { if (d.ok) setSizes(d.sizes) })
      .catch(() => {})
  }, [])

  const toggle = id => setSelected(s => ({ ...s, [id]: !s[id] }))
  const anySelected = Object.values(selected).some(Boolean)
  const selectedItems = CACHE_ITEMS.filter(i => selected[i.id])
  const hasWarnings = selectedItems.some(i => i.warning)

  const doClean = async () => {
    setClearing(true)
    try {
      const targets = Object.entries(selected).filter(([, v]) => v).map(([k]) => k)
      const r = await fetch('http://localhost:5050/cache/clear', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ targets }),
      })
      const d = await r.json()
      if (d.ok) {
        const summary = d.cleared.join(', ')
        const warn = d.errors.length ? `\nErrors: ${d.errors.join(', ')}` : ''
        alert(`Cleared: ${summary}${warn}`)
        onClose()
      } else {
        alert(`Error: ${d.error}`)
      }
    } catch {
      alert('Backend offline.')
    } finally {
      setClearing(false)
    }
  }

  return (
    <div
      style={{
        position: 'fixed', inset: 0, zIndex: 9999,
        background: 'rgba(0,0,0,0.75)',
        display: 'flex', alignItems: 'center', justifyContent: 'center',
      }}
      onClick={e => { if (e.target === e.currentTarget) onClose() }}
    >
      <div style={{
        background: '#050d1a',
        border: '1px solid #0d3a4a',
        borderRadius: 6,
        width: 420,
        maxHeight: '80vh',
        display: 'flex',
        flexDirection: 'column',
        overflow: 'hidden',
        fontFamily: "'Share Tech Mono'",
      }}>
        {/* Header */}
        <div style={{
          padding: '14px 18px 10px',
          borderBottom: '1px solid #0d2a3a',
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        }}>
          <span style={{ color: '#00e5ff', fontSize: 11, letterSpacing: '0.2em' }}>
            CACHE MANAGER
          </span>
          <button onClick={onClose} style={{
            background: 'none', border: 'none', color: '#1a4a5a',
            cursor: 'pointer', fontSize: 16, lineHeight: 1,
          }}>✕</button>
        </div>

        {/* Item list */}
        <div style={{ overflowY: 'auto', padding: '8px 0' }}>
          {CACHE_ITEMS.map(item => {
            const checked = selected[item.id]
            return (
              <div
                key={item.id}
                onClick={() => toggle(item.id)}
                style={{
                  padding: '10px 18px',
                  cursor: 'pointer',
                  borderBottom: '1px solid #0a1e2a',
                  background: checked ? '#071520' : 'transparent',
                  transition: 'background 0.1s',
                }}
              >
                <div style={{ display: 'flex', alignItems: 'flex-start', gap: 10 }}>
                  {/* Checkbox */}
                  <div style={{
                    width: 14, height: 14, marginTop: 1, flexShrink: 0,
                    border: `1px solid ${checked ? '#00e5ff' : '#1a4a5a'}`,
                    borderRadius: 2,
                    background: checked ? '#00e5ff22' : 'transparent',
                    display: 'flex', alignItems: 'center', justifyContent: 'center',
                  }}>
                    {checked && <span style={{ color: '#00e5ff', fontSize: 10, lineHeight: 1 }}>✓</span>}
                  </div>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ color: checked ? '#c8f0ff' : '#3a6070', fontSize: 10, letterSpacing: '0.08em' }}>
                      {item.label}
                    </div>
                    <div style={{ color: '#1a3a4a', fontSize: 9, marginTop: 2, letterSpacing: '0.05em', display: 'flex', gap: 6, alignItems: 'baseline' }}>
                      <span>{item.desc}</span>
                      {sizes[item.id] && (
                        <span style={{ color: '#2a5a70', fontStyle: 'normal' }}>
                          [{sizes[item.id]}]
                        </span>
                      )}
                    </div>
                    {item.warning && (
                      <div style={{
                        marginTop: 5,
                        padding: '4px 8px',
                        background: '#1a0a00',
                        border: '1px solid #3a1500',
                        borderRadius: 3,
                        color: '#ff6b35',
                        fontSize: 9,
                        letterSpacing: '0.04em',
                        lineHeight: 1.5,
                      }}>
                        ⚠ {item.warning}
                      </div>
                    )}
                  </div>
                </div>
              </div>
            )
          })}
        </div>

        {/* Footer */}
        <div style={{
          padding: '10px 18px',
          borderTop: '1px solid #0d2a3a',
          display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8,
        }}>
          <span style={{ color: '#1a4a5a', fontSize: 9, letterSpacing: '0.05em' }}>
            {anySelected
              ? `${selectedItems.length} selected${hasWarnings ? ' · ⚠ read warnings' : ''}`
              : 'select items to clear'}
          </span>
          <div style={{ display: 'flex', gap: 8 }}>
            <button onClick={onClose} style={{
              background: 'transparent', border: '1px solid #0d2a3a', borderRadius: 3,
              color: '#1a4a5a', fontFamily: "'Share Tech Mono'", fontSize: 9,
              letterSpacing: '0.1em', padding: '4px 12px', cursor: 'pointer',
            }}>
              CANCEL
            </button>
            <button
              disabled={!anySelected || clearing}
              onClick={doClean}
              style={{
                background: anySelected && !clearing ? '#00e5ff11' : 'transparent',
                border: `1px solid ${anySelected && !clearing ? '#00e5ff44' : '#0d2a3a'}`,
                borderRadius: 3,
                color: anySelected && !clearing ? '#00e5ff' : '#1a4a5a',
                fontFamily: "'Share Tech Mono'", fontSize: 9,
                letterSpacing: '0.1em', padding: '4px 12px',
                cursor: anySelected && !clearing ? 'pointer' : 'not-allowed',
                opacity: anySelected && !clearing ? 1 : 0.5,
              }}
            >
              {clearing ? 'CLEARING...' : 'CLEAR SELECTED'}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}

export default function StatusBar({ cpuUsage, ramUsage }) {
  const [timeStr, setTimeStr] = useState('')
  const [dateStr, setDateStr] = useState('')
  const [showCacheModal, setShowCacheModal] = useState(false)

  useEffect(() => {
    function tick() {
      const now = new Date()
      setTimeStr(now.toTimeString().slice(0, 8))
      setDateStr(now.toISOString().slice(0, 10))
    }
    tick()
    const t = setInterval(tick, 1000)
    return () => clearInterval(t)
  }, [])

  const segments = [
    { label: 'SYSTEM TIME', value: `${dateStr}  ${timeStr}` },
    { label: 'CPU',         value: `${cpuUsage || 0}%` },
    { label: 'RAM',         value: `${ramUsage || 0}%` },
  ]

  const btnStyle = {
    background: 'transparent',
    border: '1px solid #0d2a3a',
    borderRadius: 3,
    color: '#1a4a5a',
    fontFamily: "'Share Tech Mono'",
    fontSize: '8px',
    letterSpacing: '0.1em',
    padding: '2px 8px',
    cursor: 'pointer',
  }

  return (
    <>
      {showCacheModal && <CacheModal onClose={() => setShowCacheModal(false)} />}

      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          height: 26,
          padding: '0 16px',
          background: '#050d1a',
          borderTop: '1px solid #0d2a3a',
          flexShrink: 0,
        }}
      >
        {/* Left — system stats */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 0 }}>
          {segments.map(({ label, value }, i) => (
            <React.Fragment key={label}>
              <span style={{ fontFamily: "'Share Tech Mono'", fontSize: '9px', letterSpacing: '0.1em', color: '#1a4a5a' }}>
                [ {label} ]
              </span>
              <span style={{
                fontFamily: "'Share Tech Mono'", fontSize: '9px', letterSpacing: '0.1em',
                color: '#3a6070', marginLeft: 6, marginRight: i < segments.length - 1 ? 14 : 0,
              }}>
                {value}
              </span>
            </React.Fragment>
          ))}
        </div>

        {/* Right — buttons */}
        <button
          onClick={async () => {
            const choice = window.confirm(
              'Click OK to overwrite the existing report.\nClick Cancel to save a new file with today\'s date.'
            )
            const mode = choice ? 'overwrite' : 'new'
            try {
              const r = await fetch(`http://localhost:5050/analyze?mode=${mode}`, { method: 'POST' })
              const d = await r.json()
              alert(d.ok ? `Report saved: ${d.message}` : `Error: ${d.error}`)
            } catch {
              alert('Backend offline.')
            }
          }}
          style={btnStyle}
          onMouseEnter={e => e.currentTarget.style.color = '#00e5ff'}
          onMouseLeave={e => e.currentTarget.style.color = '#1a4a5a'}
        >
          ANALYZE LOGS
        </button>

        <button
          onClick={() => setShowCacheModal(true)}
          style={btnStyle}
          onMouseEnter={e => e.currentTarget.style.color = '#00e5ff'}
          onMouseLeave={e => e.currentTarget.style.color = '#1a4a5a'}
        >
          CLEAR CACHE
        </button>

        <button
          onClick={async () => {
            try {
              const r = await fetch('http://localhost:5050/obsidian/sync', { method: 'POST' })
              const d = await r.json()
              alert(d.ok ? 'Obsidian vault synced.' : `Error: ${d.error}`)
            } catch {
              alert('Backend offline.')
            }
          }}
          style={btnStyle}
          onMouseEnter={e => e.currentTarget.style.color = '#00e5ff'}
          onMouseLeave={e => e.currentTarget.style.color = '#1a4a5a'}
        >
          SYNC OBSIDIAN
        </button>

        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <span style={{
            width: 5, height: 5, borderRadius: '50%',
            background: '#00e5ff', boxShadow: '0 0 5px #00e5ff',
            display: 'inline-block', animation: 'statusPulse 2s infinite',
          }} />
          <span className="glow-text" style={{ fontFamily: "'Share Tech Mono'", fontSize: '9px', letterSpacing: '0.2em' }}>
            A.I LINK ACTIVE
          </span>
        </div>
      </div>
    </>
  )
}
