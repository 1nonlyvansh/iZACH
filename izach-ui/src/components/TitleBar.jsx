import React from 'react'

export default function TitleBar({ activePage = 'home', onNav }) {
  const api = window.electronAPI

  return (
    <div
      className="flex items-center justify-between px-4 h-9 select-none flex-shrink-0"
      style={{
        background: 'linear-gradient(90deg, #050d1a, #071020)',
        borderBottom: '1px solid #0d2a3a',
        WebkitAppRegion: 'drag',
      }}
    >
      {/* Left — branding */}
      <div className="flex items-center gap-3" style={{ WebkitAppRegion: 'no-drag' }}>
        <div className="flex items-center gap-1.5">
          <div style={{ width: 6, height: 6, borderRadius: '50%', background: '#00e5ff', boxShadow: '0 0 6px #00e5ff', animation: 'statusPulse 2s infinite' }} />
          <span className="glow-text" style={{ fontFamily: "'Share Tech Mono'", fontSize: 12, letterSpacing: '0.25em' }}>iZACH</span>
        </div>
        <span style={{ color: '#3a6070', fontSize: 11, letterSpacing: '0.15em' }}>NEURAL INTERFACE</span>

        {/* Nav buttons */}
        <div style={{ display: 'flex', gap: 4, marginLeft: 12 }}>
          {[
            { id: 'home',     label: 'HOME'     },
            { id: 'settings', label: 'SETTINGS' },
          ].map(({ id, label }) => (
            <button
              key={id}
              onClick={() => onNav?.(id)}
              style={{
                padding: '2px 10px',
                background: activePage === id ? 'rgba(0,229,255,0.12)' : 'transparent',
                border: `1px solid ${activePage === id ? 'rgba(0,229,255,0.4)' : 'transparent'}`,
                borderRadius: 3,
                color: activePage === id ? '#00e5ff' : '#3a6070',
                fontFamily: "'Share Tech Mono'",
                fontSize: 9,
                letterSpacing: '0.15em',
                cursor: 'pointer',
                transition: 'all 0.15s',
              }}
              onMouseEnter={e => { if (activePage !== id) e.currentTarget.style.color = '#c8e8f0' }}
              onMouseLeave={e => { if (activePage !== id) e.currentTarget.style.color = '#3a6070' }}
            >
              {label}
            </button>
          ))}
        </div>
      </div>

      {/* Center */}
      <div style={{ WebkitAppRegion: 'drag' }}>
        <p style={{ color: '#1a4a5a', fontFamily: "'Share Tech Mono'", fontSize: 10, letterSpacing: '0.3em' }}>
          INTELLIGENT ZENITH ADAPTIVE COGNITIVE HANDLER
        </p>
      </div>

      {/* Window controls */}
      <div className="flex items-center gap-1" style={{ WebkitAppRegion: 'no-drag' }}>
        {[
          { label: '—', action: 'minimize', hover: { background: '#0d2a3a' } },
          { label: '□', action: 'maximize', hover: { background: '#0d2a3a' } },
          { label: '✕', action: 'close',    hover: { background: '#3d0000', color: '#ff3d3d' } },
        ].map(({ label, action, hover }) => (
          <button
            key={action}
            onClick={() => api?.[action]?.()}
            style={{ width: 28, height: 28, display: 'flex', alignItems: 'center', justifyContent: 'center', borderRadius: 4, fontSize: 12, color: '#3a6070', background: 'transparent', border: 'none', cursor: 'pointer', transition: 'all 0.15s' }}
            onMouseEnter={e => Object.assign(e.currentTarget.style, hover)}
            onMouseLeave={e => Object.assign(e.currentTarget.style, { background: 'transparent', color: '#3a6070' })}
          >
            {label}
          </button>
        ))}
      </div>
    </div>
  )
}