import React, { useState } from 'react'

export default function CameraPanel() {
  const [camOn, setCamOn]             = useState(false)
  const [gestureLabel, setGestureLabel] = useState('')
  const [gestureMode, setGestureMode] = useState('desktop')

  function toggleMode() {
    setGestureMode(prev => prev === 'desktop' ? 'music' : 'desktop')
  }

  function switchCamera() {
    // Camera switching handled by Python side
    // Future: call POST /vision/switch_camera
    console.log('[CameraPanel] Camera switch requested')
  }

  const CORNERS = ['tl', 'tr', 'bl', 'br']
  function cornerStyle(pos) {
    return {
      position: 'absolute',
      width: 14,
      height: 14,
      top:    pos.startsWith('t') ? 6 : 'auto',
      bottom: pos.startsWith('b') ? 6 : 'auto',
      left:   pos.endsWith('l')   ? 6 : 'auto',
      right:  pos.endsWith('r')   ? 6 : 'auto',
      borderTop:    pos.startsWith('t') ? '1.5px solid rgba(0,229,255,0.55)' : 'none',
      borderBottom: pos.startsWith('b') ? '1.5px solid rgba(0,229,255,0.55)' : 'none',
      borderLeft:   pos.endsWith('l')   ? '1.5px solid rgba(0,229,255,0.55)' : 'none',
      borderRight:  pos.endsWith('r')   ? '1.5px solid rgba(0,229,255,0.55)' : 'none',
    }
  }

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
        </div>

        <div className="flex items-center gap-1">
          {/* Gesture mode toggle */}
          <button
            onClick={toggleMode}
            style={{
              background: gestureMode === 'music' ? 'rgba(255,179,0,0.1)' : 'rgba(0,229,255,0.06)',
              color: gestureMode === 'music' ? '#ffb300' : '#3a6070',
              border: `1px solid ${gestureMode === 'music' ? 'rgba(255,179,0,0.3)' : '#0d2a3a'}`,
              fontFamily: "'Share Tech Mono'",
              fontSize: '9px',
              padding: '2px 6px',
              borderRadius: 3,
              cursor: 'pointer',
              letterSpacing: '0.1em',
            }}
          >
            {gestureMode === 'music' ? '♪ MUSIC' : '⊞ DESK'}
          </button>

          {/* Camera switch */}
          <button
            onClick={switchCamera}
            title="Switch camera"
            style={{
              background: 'rgba(0,229,255,0.05)',
              color: '#00e5ff',
              border: '1px solid #1a4a5a',
              fontFamily: "'Share Tech Mono'",
              fontSize: '9px',
              padding: '2px 6px',
              borderRadius: 3,
              cursor: 'pointer',
            }}
          >
            ⟳ CAM
          </button>
        </div>
      </div>

      {/* Camera viewport — strict 16:9 */}
      <div className="px-3 pt-2 flex-shrink-0">
        <div
          style={{
            position: 'relative',
            width: '100%',
            paddingTop: '56.25%', /* 16:9 */
            background: '#000',
            overflow: 'hidden',
          }}
        >
          {/* Video element sits absolutely inside the padded box */}
          {camOn && (
            <img
              src="http://localhost:5050/vision/stream"
              alt="camera"
              style={{
                position: 'absolute',
                inset: 0,
                width: '100%',
                height: '100%',
                objectFit: 'cover',
              }}
            />
          )}

          {/* Offline / error overlay */}
          {!camOn && (
            <div
              style={{
                position: 'absolute',
                inset: 0,
                display: 'flex',
                flexDirection: 'column',
                alignItems: 'center',
                justifyContent: 'center',
                background: '#050d1a',
              }}
            >
              <svg
                width="28" height="28" viewBox="0 0 24 24"
                fill="none" stroke="#1a4a5a" strokeWidth="1.2"
                style={{ marginBottom: 6, opacity: 0.5 }}
              >
                <path d="M23 7l-7 5 7 5V7z" />
                <rect x="1" y="5" width="15" height="14" rx="2" ry="2" />
              </svg>
              <p
                style={{
                  color: '#1a4a5a',
                  fontFamily: "'Share Tech Mono'",
                  fontSize: '9px',
                  letterSpacing: '0.15em',
                  textAlign: 'center',
                  padding: '0 8px',
                }}
              >
                {'CAMERA OFFLINE'}
              </p>
            </div>
          )}

          {/* HUD corner brackets */}
          {CORNERS.map(pos => (
            <div key={pos} style={cornerStyle(pos)} />
          ))}

          {/* Gesture label overlay */}
          {gestureLabel && (
            <div
              style={{
                position: 'absolute',
                bottom: 6,
                left: '50%',
                transform: 'translateX(-50%)',
                background: 'rgba(0,229,255,0.15)',
                border: '1px solid rgba(0,229,255,0.35)',
                color: '#00e5ff',
                fontFamily: "'JetBrains Mono'",
                fontSize: '9px',
                padding: '2px 8px',
                borderRadius: 3,
                whiteSpace: 'nowrap',
              }}
            >
              ▶ {gestureLabel}
            </div>
          )}

          {/* Live indicator when camera is on */}
          {camOn && (
            <div
              style={{
                position: 'absolute',
                top: 6,
                right: 6,
                display: 'flex',
                alignItems: 'center',
                gap: 4,
                background: 'rgba(5,13,26,0.7)',
                border: '1px solid rgba(255,61,61,0.4)',
                borderRadius: 3,
                padding: '2px 6px',
              }}
            >
              <span
                style={{
                  width: 5,
                  height: 5,
                  borderRadius: '50%',
                  background: '#ff3d3d',
                  boxShadow: '0 0 4px #ff3d3d',
                  animation: 'statusPulseRed 1.5s infinite',
                  display: 'inline-block',
                }}
              />
              <span style={{ color: '#ff3d3d', fontFamily: "'Share Tech Mono'", fontSize: '8px' }}>
                LIVE
              </span>
            </div>
          )}
        </div>
      </div>

      {/* Controls */}
      <div className="px-3 pt-2 pb-1 flex gap-2">
        <button
          onClick={() => setCamOn(prev => !prev)}
          style={{
            flex: 1,
            padding: '5px 0',
            background: camOn ? 'rgba(255,61,61,0.08)' : 'rgba(0,229,255,0.07)',
            color: camOn ? '#ff3d3d' : '#00e5ff',
            border: `1px solid ${camOn ? 'rgba(255,61,61,0.3)' : 'rgba(0,229,255,0.2)'}`,
            borderRadius: 3,
            fontFamily: "'Share Tech Mono'",
            fontSize: '9px',
            letterSpacing: '0.15em',
            cursor: 'pointer',
            transition: 'all 0.2s',
          }}
        >
          {camOn ? '⏹ CAM OFF' : '▶ CAM ON'}
        </button>
      </div>

      {/* Camera list (shown only if multiple cameras available)
      {cameras.length > 1 && (
        <div className="px-3 pb-2">
          <p
            style={{
              color: '#1a4a5a',
              fontFamily: "'Share Tech Mono'",
              fontSize: '8px',
              letterSpacing: '0.12em',
              marginBottom: 4,
            }}
          >
            AVAILABLE CAMERAS
          </p>
          {cameras.map((cam, i) => (
            <button
              key={cam.deviceId || i}
              onClick={() => {
                setCamIdx(i)
                if (camOn) startCamera(cam.deviceId)
              }}
              style={{
                display: 'block',
                width: '100%',
                textAlign: 'left',
                padding: '3px 6px',
                marginBottom: 2,
                background: i === camIdx ? 'rgba(0,229,255,0.07)' : 'transparent',
                color: i === camIdx ? '#00e5ff' : '#3a6070',
                border: `1px solid ${i === camIdx ? 'rgba(0,229,255,0.2)' : 'transparent'}`,
                borderRadius: 3,
                fontFamily: "'JetBrains Mono'",
                fontSize: '9px',
                cursor: 'pointer',
                overflow: 'hidden',
                whiteSpace: 'nowrap',
                textOverflow: 'ellipsis',
              }}
            >
              {i === camIdx ? '◆ ' : '◇ '}
              {cam.label || `Camera ${i + 1}`}
            </button>
          ))}
        </div>
      )} */}
    </div>
  )
}