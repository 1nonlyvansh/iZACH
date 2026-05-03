import React from 'react'

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
  const map = { prev: 'previous', playpause: 'playpause', next: 'next' }
  try {
    await fetch(`${BASE}/command`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text: map[action] }),
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

export default function RightPanel({ waStatus, mmaStatus, spotifyTrack, notifications }) {
  return (
    <div style={{
      display: 'flex', flexDirection: 'column',
      height: '100%', overflowY: 'auto', overflowX: 'hidden',
      background: '#0a1628', borderLeft: '1px solid #0d2a3a',
    }}>
      <SpotifyPanel track={spotifyTrack} />
      <Divider />
      <StatusPanel label="MMA REMOTE AGENT" status={mmaStatus}
        detail={mmaStatus === 'offline' ? 'MMA not running' : 'Online'} />
      <Divider />
      <StatusPanel label="WHATSAPP BRIDGE" status={waStatus}
        detail={waStatus === 'offline' ? '' : 'Connected'} />
      <Divider />
      <NotificationsPanel notifications={notifications} />
      <Divider />
      <SystemLog errors={[]} />
    </div>
  )
}