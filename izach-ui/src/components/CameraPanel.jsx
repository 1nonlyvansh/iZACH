import React, { useState, useEffect } from 'react'

const FACE_COLORS = {
  scanning:  '#00e5ff',
  enrolling: '#ffb300',
  success:   '#1db954',
  failed:    '#ff3d3d',
  idle:      '#00e5ff',
}

function FaceMappingOverlay({ state }) {
  const color = FACE_COLORS[state] || '#00e5ff'
  const isEnroll = state === 'enrolling'

  return (
    <div style={{ position: 'absolute', inset: 0, pointerEvents: 'none' }}>

      {/* SVG face landmarks + grid */}
      <svg
        viewBox="0 0 100 100"
        style={{ position: 'absolute', inset: 0, width: '100%', height: '100%' }}
      >
        {/* Horizontal + vertical crosshair lines */}
        <line x1="20" y1="50" x2="80" y2="50" stroke={color} strokeWidth="0.25" className="face-grid" />
        <line x1="50" y1="15" x2="50" y2="85" stroke={color} strokeWidth="0.25" className="face-grid" />

        {/* Outer face oval */}
        <ellipse
          cx="50" cy="49" rx="24" ry="31"
          fill="none"
          stroke={color}
          strokeWidth="0.8"
          strokeDasharray={isEnroll ? '3 1.5' : '5 2'}
          className={isEnroll ? 'enroll-oval' : 'face-oval'}
        />

        {/* Eye sockets */}
        <ellipse cx="40" cy="42" rx="4" ry="2.5" fill="none" stroke={color} strokeWidth="0.6" opacity="0.8" className="face-grid" />
        <ellipse cx="60" cy="42" rx="4" ry="2.5" fill="none" stroke={color} strokeWidth="0.6" opacity="0.8" className="face-grid" />

        {/* Pupil dots */}
        <circle cx="40" cy="42" r="1.2" fill={color} opacity="0.7" />
        <circle cx="60" cy="42" r="1.2" fill={color} opacity="0.7" />

        {/* Nose bridge */}
        <path d="M 48 46 L 47 51 L 53 51 L 52 46" fill="none" stroke={color} strokeWidth="0.5" opacity="0.6" className="face-grid" />

        {/* Mouth */}
        <path d="M 42 57 Q 50 62 58 57" fill="none" stroke={color} strokeWidth="0.7" opacity="0.7" className="face-grid" />

        {/* Cheek dots */}
        <circle cx="32" cy="50" r="0.8" fill={color} opacity="0.4" />
        <circle cx="68" cy="50" r="0.8" fill={color} opacity="0.4" />

        {/* Chin point */}
        <circle cx="50" cy="78" r="0.8" fill={color} opacity="0.4" />

        {/* Forehead top point */}
        <circle cx="50" cy="20" r="0.8" fill={color} opacity="0.4" />

        {/* Corner bracket measurement lines */}
        {[
          ['M 26 20 L 20 20 L 20 26', ''],
          ['M 74 20 L 80 20 L 80 26', ''],
          ['M 26 80 L 20 80 L 20 74', ''],
          ['M 74 80 L 80 80 L 80 74', ''],
        ].map(([d], i) => (
          <path key={i} d={d} fill="none" stroke={color} strokeWidth="0.9" opacity="0.6" />
        ))}

        {/* Enrolling spinner ring */}
        {isEnroll && (
          <circle
            cx="50" cy="49" r="36"
            fill="none"
            stroke={color}
            strokeWidth="0.4"
            strokeDasharray="8 4"
            opacity="0.4"
            className="enroll-spinner"
            style={{ transformOrigin: '50px 49px' }}
          />
        )}
      </svg>

      {/* Moving scan line */}
      <div
        className="face-scan-line"
        style={{
          position: 'absolute',
          left: '18%', right: '18%',
          height: '1.5px',
          background: `linear-gradient(90deg, transparent, ${color}, transparent)`,
          boxShadow: `0 0 6px ${color}, 0 0 12px ${color}55`,
        }}
      />

      {/* State label at bottom */}
      <div style={{
        position: 'absolute', bottom: 7, left: '50%', transform: 'translateX(-50%)',
        background: 'rgba(0,8,18,0.85)',
        border: `1px solid ${color}`,
        color,
        fontFamily: "'Share Tech Mono'",
        fontSize: '8px', letterSpacing: '0.2em',
        padding: '2px 10px', borderRadius: 2, whiteSpace: 'nowrap',
      }}>
        {isEnroll ? '◉ CAPTURING FACE DATA' : '▶ SCANNING BIOMETRICS'}
      </div>
    </div>
  )
}

function ResultOverlay({ state }) {
  const isSuccess = state === 'success'
  const color  = isSuccess ? '#1db954' : '#ff3d3d'
  const bg     = isSuccess ? 'rgba(0,18,6,0.88)' : 'rgba(18,0,0,0.88)'
  const label  = isSuccess ? 'SUCCESS' : 'NOT MATCHED'
  const sub    = isSuccess ? 'IDENTITY CONFIRMED' : 'ACCESS DENIED'
  const icon   = isSuccess ? '✓' : '✗'

  return (
    <div
      className="face-result"
      style={{
        position: 'absolute', inset: 0,
        background: bg,
        display: 'flex', flexDirection: 'column',
        alignItems: 'center', justifyContent: 'center',
        border: `2px solid ${color}`,
        boxShadow: `inset 0 0 24px ${color}33`,
      }}
    >
      {/* Icon ring */}
      <div style={{
        width: 44, height: 44, borderRadius: '50%',
        border: `2px solid ${color}`,
        boxShadow: `0 0 12px ${color}66`,
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        marginBottom: 8,
        fontSize: '22px', color,
      }}>
        {icon}
      </div>
      <p style={{
        color, fontFamily: "'Share Tech Mono'",
        fontSize: '12px', letterSpacing: '0.25em', marginBottom: 3,
      }}>
        {label}
      </p>
      <p style={{
        color, fontFamily: "'JetBrains Mono'",
        fontSize: '8px', letterSpacing: '0.15em', opacity: 0.65,
      }}>
        {sub}
      </p>
    </div>
  )
}

export default function CameraPanel({ faceState = 'idle' }) {
  const [camOn, setCamOn]             = useState(false)
  const [gestureLabel, setGestureLabel] = useState('')
  const [gestureMode, setGestureMode] = useState('desktop')

  // Auto-enable camera when face auth starts
  useEffect(() => {
    if (faceState === 'scanning' || faceState === 'enrolling') {
      setCamOn(true)
    }
  }, [faceState])

  function toggleMode() {
    setGestureMode(prev => prev === 'desktop' ? 'music' : 'desktop')
  }

  const CORNERS = ['tl', 'tr', 'bl', 'br']
  function cornerStyle(pos) {
    const isActive = faceState !== 'idle'
    const c = isActive ? (FACE_COLORS[faceState] || '#00e5ff') : 'rgba(0,229,255,0.55)'
    return {
      position: 'absolute',
      width: 14, height: 14,
      top:    pos.startsWith('t') ? 6 : 'auto',
      bottom: pos.startsWith('b') ? 6 : 'auto',
      left:   pos.endsWith('l')   ? 6 : 'auto',
      right:  pos.endsWith('r')   ? 6 : 'auto',
      borderTop:    pos.startsWith('t') ? `1.5px solid ${c}` : 'none',
      borderBottom: pos.startsWith('b') ? `1.5px solid ${c}` : 'none',
      borderLeft:   pos.endsWith('l')   ? `1.5px solid ${c}` : 'none',
      borderRight:  pos.endsWith('r')   ? `1.5px solid ${c}` : 'none',
      transition: 'border-color 0.3s ease',
    }
  }

  const isFaceActive   = faceState === 'scanning' || faceState === 'enrolling'
  const isFaceResult   = faceState === 'success'  || faceState === 'failed'
  const borderColor    = isFaceActive || isFaceResult
    ? FACE_COLORS[faceState] : 'transparent'

  return (
    <div className="flex flex-col h-full">

      {/* Sub-header */}
      <div
        className="flex items-center justify-between px-3 py-2 flex-shrink-0"
        style={{ borderBottom: '1px solid #0d2a3a' }}
      >
        <div className="flex items-center gap-2">
          <span style={{ color: '#00e5ff' }}>*</span>
          <span
            className="text-xs tracking-[0.2em]"
            style={{ color: '#00e5ff', fontFamily: "'Share Tech Mono'" }}
          >
            VISION
          </span>
          {/* Face state badge */}
          {faceState !== 'idle' && (
            <span style={{
              color: FACE_COLORS[faceState],
              fontFamily: "'Share Tech Mono'",
              fontSize: '8px', letterSpacing: '0.15em',
              border: `1px solid ${FACE_COLORS[faceState]}`,
              padding: '1px 5px', borderRadius: 2,
            }}>
              {faceState.toUpperCase()}
            </span>
          )}
        </div>

        <div className="flex items-center gap-1">
          <button
            onClick={toggleMode}
            style={{
              background: gestureMode === 'music' ? 'rgba(255,179,0,0.1)' : 'rgba(0,229,255,0.06)',
              color: gestureMode === 'music' ? '#ffb300' : '#3a6070',
              border: `1px solid ${gestureMode === 'music' ? 'rgba(255,179,0,0.3)' : '#0d2a3a'}`,
              fontFamily: "'Share Tech Mono'",
              fontSize: '9px', padding: '2px 6px',
              borderRadius: 3, cursor: 'pointer', letterSpacing: '0.1em',
            }}
          >
            {gestureMode === 'music' ? '♪ MUSIC' : '⊞ DESK'}
          </button>

          <button
            title="Switch camera"
            style={{
              background: 'rgba(0,229,255,0.05)', color: '#00e5ff',
              border: '1px solid #1a4a5a', fontFamily: "'Share Tech Mono'",
              fontSize: '9px', padding: '2px 6px',
              borderRadius: 3, cursor: 'pointer',
            }}
          >
            ⟳ CAM
          </button>
        </div>
      </div>

      {/* Camera viewport */}
      <div className="px-3 pt-2 flex-shrink-0">
        <div
          style={{
            position: 'relative', width: '100%', paddingTop: '56.25%',
            background: '#000', overflow: 'hidden',
            border: isFaceActive || isFaceResult
              ? `1.5px solid ${borderColor}`
              : '1px solid transparent',
            boxShadow: isFaceActive || isFaceResult
              ? `0 0 10px ${borderColor}44`
              : 'none',
            transition: 'border-color 0.3s ease, box-shadow 0.3s ease',
            borderRadius: 2,
          }}
        >
          {/* Live stream */}
          {camOn && (
            <img
              src="http://localhost:5050/vision/stream"
              alt="camera"
              style={{ position: 'absolute', inset: 0, width: '100%', height: '100%', objectFit: 'cover' }}
            />
          )}

          {/* Camera offline placeholder */}
          {!camOn && (
            <div style={{
              position: 'absolute', inset: 0,
              display: 'flex', flexDirection: 'column',
              alignItems: 'center', justifyContent: 'center',
              background: '#050d1a',
            }}>
              <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="#1a4a5a" strokeWidth="1.2" style={{ marginBottom: 6, opacity: 0.5 }}>
                <path d="M23 7l-7 5 7 5V7z" />
                <rect x="1" y="5" width="15" height="14" rx="2" ry="2" />
              </svg>
              <p style={{ color: '#1a4a5a', fontFamily: "'Share Tech Mono'", fontSize: '9px', letterSpacing: '0.15em' }}>
                CAMERA OFFLINE
              </p>
            </div>
          )}

          {/* HUD corner brackets */}
          {CORNERS.map(pos => (
            <div key={pos} style={cornerStyle(pos)} />
          ))}

          {/* Face mapping overlay (scanning / enrolling) */}
          {isFaceActive && <FaceMappingOverlay state={faceState} />}

          {/* Result overlay (success / failed) */}
          {isFaceResult && <ResultOverlay state={faceState} />}

          {/* Gesture label */}
          {gestureLabel && !isFaceActive && !isFaceResult && (
            <div style={{
              position: 'absolute', bottom: 6, left: '50%', transform: 'translateX(-50%)',
              background: 'rgba(0,229,255,0.15)',
              border: '1px solid rgba(0,229,255,0.35)',
              color: '#00e5ff', fontFamily: "'JetBrains Mono'",
              fontSize: '9px', padding: '2px 8px',
              borderRadius: 3, whiteSpace: 'nowrap',
            }}>
              ▶ {gestureLabel}
            </div>
          )}

          {/* LIVE indicator */}
          {camOn && (
            <div style={{
              position: 'absolute', top: 6, right: 6,
              display: 'flex', alignItems: 'center', gap: 4,
              background: 'rgba(5,13,26,0.7)',
              border: '1px solid rgba(255,61,61,0.4)',
              borderRadius: 3, padding: '2px 6px',
            }}>
              <span style={{
                width: 5, height: 5, borderRadius: '50%',
                background: '#ff3d3d', boxShadow: '0 0 4px #ff3d3d',
                animation: 'statusPulseRed 1.5s infinite',
                display: 'inline-block',
              }} />
              <span style={{ color: '#ff3d3d', fontFamily: "'Share Tech Mono'", fontSize: '8px' }}>
                LIVE
              </span>
            </div>
          )}
        </div>
      </div>

      {/* CAM ON/OFF control */}
      <div className="px-3 pt-2 pb-1 flex gap-2">
        <button
          onClick={() => setCamOn(prev => !prev)}
          style={{
            flex: 1, padding: '5px 0',
            background: camOn ? 'rgba(255,61,61,0.08)' : 'rgba(0,229,255,0.07)',
            color: camOn ? '#ff3d3d' : '#00e5ff',
            border: `1px solid ${camOn ? 'rgba(255,61,61,0.3)' : 'rgba(0,229,255,0.2)'}`,
            borderRadius: 3, fontFamily: "'Share Tech Mono'",
            fontSize: '9px', letterSpacing: '0.15em',
            cursor: 'pointer', transition: 'all 0.2s',
          }}
        >
          {camOn ? '⏹ CAM OFF' : '▶ CAM ON'}
        </button>
      </div>
    </div>
  )
}
