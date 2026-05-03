import React, { useState, useEffect } from 'react'

export default function StatusBar({ cpuUsage, ramUsage }) {
  const [timeStr, setTimeStr] = useState('')
  const [dateStr, setDateStr] = useState('')

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

  return (
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
            <span
              style={{
                fontFamily: "'Share Tech Mono'",
                fontSize: '9px',
                letterSpacing: '0.1em',
                color: '#1a4a5a',
              }}
            >
              [ {label} ]
            </span>
            <span
              style={{
                fontFamily: "'Share Tech Mono'",
                fontSize: '9px',
                letterSpacing: '0.1em',
                color: '#3a6070',
                marginLeft: 6,
                marginRight: i < segments.length - 1 ? 14 : 0,
              }}
            >
              {value}
            </span>
          </React.Fragment>
        ))}
      </div>

      {/* Right — link status */}

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
        style={{
          background: 'transparent',
          border: '1px solid #0d2a3a',
          borderRadius: 3,
          color: '#1a4a5a',
          fontFamily: "'Share Tech Mono'",
          fontSize: '8px',
          letterSpacing: '0.1em',
          padding: '2px 8px',
          cursor: 'pointer',
        }}
        onMouseEnter={e => e.currentTarget.style.color = '#00e5ff'}
        onMouseLeave={e => e.currentTarget.style.color = '#1a4a5a'}
      >
        ANALYZE LOGS
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
        style={{
          background: 'transparent',
          border: '1px solid #0d2a3a',
          borderRadius: 3,
          color: '#1a4a5a',
          fontFamily: "'Share Tech Mono'",
          fontSize: '8px',
          letterSpacing: '0.1em',
          padding: '2px 8px',
          cursor: 'pointer',
        }}
        onMouseEnter={e => e.currentTarget.style.color = '#00e5ff'}
        onMouseLeave={e => e.currentTarget.style.color = '#1a4a5a'}
      >
        SYNC OBSIDIAN
      </button>

      <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
        <span
          style={{
            width: 5,
            height: 5,
            borderRadius: '50%',
            background: '#00e5ff',
            boxShadow: '0 0 5px #00e5ff',
            display: 'inline-block',
            animation: 'statusPulse 2s infinite',
          }}
        />
        <span
          className="glow-text"
          style={{
            fontFamily: "'Share Tech Mono'",
            fontSize: '9px',
            letterSpacing: '0.2em',
          }}
        >
          A.I LINK ACTIVE
        </span>
      </div>
    </div>
  )
}