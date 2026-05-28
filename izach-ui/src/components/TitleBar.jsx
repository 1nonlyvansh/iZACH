import React from 'react'

const AGENT_META = {
  whatsapp: { label: 'WHATSAPP', color: '#25D366' },
  spotify:  { label: 'SPOTIFY',  color: '#1DB954' },
  calendar: { label: 'CALENDAR', color: '#4285F4' },
  system:   { label: 'SYSTEM',   color: '#F59E0B' },
  research: { label: 'RESEARCH', color: '#00e5ff' },
  file:     { label: 'FILE',     color: '#8B5CF6' },
  memory:   { label: 'MEMORY',   color: '#EC4899' },
  vision:   { label: 'VISION',   color: '#14B8A6' },
}

export default function TitleBar({ activePage = 'home', onNav, activeAgent = null, camVisible = false, onToggleCam, dndActive = false, onToggleDnd, busyActive = false, busyReason = 'manual', onToggleBusy }) {
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

          {/* DND toggle */}
          <button
            onClick={onToggleDnd}
            title={dndActive ? 'DND ON — click to disable' : 'Enable Do Not Disturb'}
            style={{
              padding: '2px 10px',
              background: dndActive ? 'rgba(200,40,40,0.18)' : 'transparent',
              border: `1px solid ${dndActive ? 'rgba(255,80,80,0.5)' : 'transparent'}`,
              borderRadius: 3,
              color: dndActive ? '#ff6060' : '#3a6070',
              fontFamily: "'Share Tech Mono'",
              fontSize: 9,
              letterSpacing: '0.15em',
              cursor: 'pointer',
              transition: 'all 0.15s',
              display: 'flex', alignItems: 'center', gap: 4,
            }}
            onMouseEnter={e => { if (!dndActive) e.currentTarget.style.color = '#c8e8f0' }}
            onMouseLeave={e => { if (!dndActive) e.currentTarget.style.color = '#3a6070' }}
          >
            🌙 DND
          </button>

          {/* Busy mode toggle */}
          <button
            onClick={() => onToggleBusy?.(busyActive ? 'manual' : busyReason)}
            title={busyActive ? `BUSY (${busyReason.toUpperCase()}) — click to turn off` : 'Enable Busy Mode'}
            style={{
              padding: '2px 10px',
              background: busyActive ? 'rgba(255,140,0,0.18)' : 'transparent',
              border: `1px solid ${busyActive ? 'rgba(255,160,30,0.5)' : 'transparent'}`,
              borderRadius: 3,
              color: busyActive ? '#ffaa30' : '#3a6070',
              fontFamily: "'Share Tech Mono'",
              fontSize: 9,
              letterSpacing: '0.15em',
              cursor: 'pointer',
              transition: 'all 0.15s',
              display: 'flex', alignItems: 'center', gap: 4,
            }}
            onMouseEnter={e => { if (!busyActive) e.currentTarget.style.color = '#c8e8f0' }}
            onMouseLeave={e => { if (!busyActive) e.currentTarget.style.color = '#3a6070' }}
          >
            🔶 {busyActive ? busyReason.slice(0, 4).toUpperCase() : 'BUSY'}
          </button>

          {/* Optics toggle */}
          <button
            onClick={onToggleCam}
            title={camVisible ? 'OPTICS OFF' : 'OPTICS ON'}
            style={{
              padding: '2px 10px',
              background: camVisible ? 'rgba(0,229,255,0.12)' : 'transparent',
              border: `1px solid ${camVisible ? 'rgba(0,229,255,0.4)' : 'transparent'}`,
              borderRadius: 3,
              color: camVisible ? '#00e5ff' : '#3a6070',
              fontFamily: "'Share Tech Mono'",
              fontSize: 9,
              letterSpacing: '0.15em',
              cursor: 'pointer',
              transition: 'all 0.15s',
              display: 'flex', alignItems: 'center', gap: 4,
            }}
            onMouseEnter={e => { if (!camVisible) e.currentTarget.style.color = '#c8e8f0' }}
            onMouseLeave={e => { if (!camVisible) e.currentTarget.style.color = '#3a6070' }}
          >
            ⊡ OPTICS
          </button>
        </div>
      </div>

      {/* Center — agent pill when active, static label when idle */}
      <div style={{ WebkitAppRegion: 'drag', minWidth: 280, display: 'flex', justifyContent: 'center' }}>
        {activeAgent && AGENT_META[activeAgent.domain] ? (
          <div
            key={activeAgent.domain}
            style={{
              display: 'flex', alignItems: 'center', gap: 8,
              padding: '2px 14px', borderRadius: 3,
              border: `1px solid ${AGENT_META[activeAgent.domain].color}55`,
              background: `${AGENT_META[activeAgent.domain].color}11`,
              animation: 'agentPillIn 0.2s ease',
            }}
          >
            {/* Animated dot */}
            <div style={{
              width: 5, height: 5, borderRadius: '50%',
              background: AGENT_META[activeAgent.domain].color,
              boxShadow: `0 0 6px ${AGENT_META[activeAgent.domain].color}`,
              animation: 'statusPulse 1s infinite',
            }} />
            <span style={{
              fontFamily: "'Share Tech Mono'",
              fontSize: 10,
              letterSpacing: '0.25em',
              color: AGENT_META[activeAgent.domain].color,
            }}>
              {AGENT_META[activeAgent.domain].label}
            </span>
            <span style={{
              fontFamily: "'Share Tech Mono'",
              fontSize: 9,
              letterSpacing: '0.1em',
              color: `${AGENT_META[activeAgent.domain].color}88`,
            }}>
              AGENT
            </span>
          </div>
        ) : (
          <p style={{ color: '#1a4a5a', fontFamily: "'Share Tech Mono'", fontSize: 10, letterSpacing: '0.3em' }}>
            INTENT ZENITH ADAPTIVE COGNITIVE HANDLER
          </p>
        )}
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