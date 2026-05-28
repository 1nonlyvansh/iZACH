import React, { useState, useEffect, useCallback } from 'react'

function SectionHeader({ label }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '12px 20px 8px' }}>
      <span style={{ color: '#00e5ff' }}>*</span>
      <span style={{ color: '#00e5ff', fontFamily: "'Share Tech Mono'", fontSize: '10px', letterSpacing: '0.2em' }}>
        {label}
      </span>
      <div style={{ flex: 1, height: 1, background: '#0d2a3a' }} />
    </div>
  )
}

function Row({ children }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '0 20px 10px' }}>
      {children}
    </div>
  )
}

function Input({ value, onChange, placeholder, style = {} }) {
  return (
    <input
      value={value}
      onChange={e => onChange(e.target.value)}
      placeholder={placeholder}
      style={{
        flex: 1,
        padding: '7px 10px',
        background: '#071020',
        border: '1px solid #0d2a3a',
        borderRadius: 4,
        color: '#c8e8f0',
        fontFamily: "'JetBrains Mono'",
        fontSize: '11px',
        outline: 'none',
        caretColor: '#00e5ff',
        ...style,
      }}
      onFocus={e => e.target.style.borderColor = '#00e5ff'}
      onBlur={e  => e.target.style.borderColor = '#0d2a3a'}
    />
  )
}

function Btn({ label, onClick, color = '#00e5ff', danger }) {
  const bg     = danger ? 'rgba(255,61,61,0.08)' : 'rgba(0,229,255,0.07)'
  const border = danger ? 'rgba(255,61,61,0.3)'   : 'rgba(0,229,255,0.25)'
  const col    = danger ? '#ff3d3d'               : color
  return (
    <button
      onClick={onClick}
      style={{
        padding: '6px 14px',
        background: bg,
        border: `1px solid ${border}`,
        borderRadius: 4,
        color: col,
        fontFamily: "'Share Tech Mono'",
        fontSize: '10px',
        letterSpacing: '0.1em',
        cursor: 'pointer',
        flexShrink: 0,
        transition: 'all 0.15s',
      }}
      onMouseEnter={e => e.currentTarget.style.opacity = '0.8'}
      onMouseLeave={e => e.currentTarget.style.opacity = '1'}
    >
      {label}
    </button>
  )
}

function Toggle({ label, checked, onChange }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '6px 20px' }}>
      <span style={{ color: '#c8e8f0', fontFamily: "'JetBrains Mono'", fontSize: '11px' }}>{label}</span>
      <div
        onClick={() => onChange(!checked)}
        style={{
          width: 40, height: 20,
          borderRadius: 10,
          background: checked ? '#00e5ff33' : '#0d2a3a',
          border: `1px solid ${checked ? '#00e5ff' : '#1a4a5a'}`,
          cursor: 'pointer',
          position: 'relative',
          transition: 'all 0.2s',
          flexShrink: 0,
        }}
      >
        <div style={{
          position: 'absolute',
          top: 2, left: checked ? 20 : 2,
          width: 14, height: 14,
          borderRadius: '50%',
          background: checked ? '#00e5ff' : '#3a6070',
          boxShadow: checked ? '0 0 6px #00e5ff' : 'none',
          transition: 'all 0.2s',
        }} />
      </div>
    </div>
  )
}

// ── Memory Section ────────────────────────────────────────────
function MemorySection({ entries, onAdd, onDelete }) {
  const [newKey,   setNewKey]   = useState('')
  const [newValue, setNewValue] = useState('')

  function handleAdd() {
    if (!newKey.trim() || !newValue.trim()) return
    onAdd(newKey.trim(), newValue.trim())
    setNewKey('')
    setNewValue('')
  }

  return (
    <div>
      <SectionHeader label="PERSONAL MEMORY" />

      {/* Add new entry */}
      <Row>
        <Input value={newKey}   onChange={setNewKey}   placeholder="Key (e.g. my name)" />
        <Input value={newValue} onChange={setNewValue} placeholder="Value (e.g. Vansh)" />
        <Btn label="ADD" onClick={handleAdd} />
      </Row>

      {/* Existing entries */}
      <div style={{ padding: '0 20px', maxHeight: 200, overflowY: 'auto' }}>
        {entries.length === 0 ? (
          <p style={{ color: '#1a4a5a', fontFamily: "'JetBrains Mono'", fontSize: '10px', padding: '4px 0' }}>
            No memory entries yet.
          </p>
        ) : entries.map(({ key, value, added }) => (
          <div
            key={key}
            style={{
              display: 'flex', alignItems: 'center', gap: 10,
              padding: '6px 8px', marginBottom: 4,
              background: 'rgba(0,229,255,0.03)',
              border: '1px solid #0d2a3a',
              borderRadius: 4,
            }}
          >
            <div style={{ flex: 1, overflow: 'hidden' }}>
              <span style={{ color: '#00e5ff', fontFamily: "'Share Tech Mono'", fontSize: '10px' }}>{key}</span>
              <span style={{ color: '#3a6070', margin: '0 8px', fontSize: '10px' }}>→</span>
              <span style={{ color: '#c8e8f0', fontFamily: "'JetBrains Mono'", fontSize: '10px' }}>{value}</span>
            </div>
            {added && (
              <span style={{ color: '#1a4a5a', fontFamily: "'JetBrains Mono'", fontSize: '9px', flexShrink: 0 }}>
                {added}
              </span>
            )}
            <Btn label="✕" danger onClick={() => onDelete(key)} />
          </div>
        ))}
      </div>
    </div>
  )
}

const BASE = 'http://localhost:5050'

function SelectField({ label, value, onChange, options }) {
  return (
    <div style={{ padding: '4px 20px 10px' }}>
      <p style={{ color: '#3a6070', fontFamily: "'Share Tech Mono'", fontSize: '9px', letterSpacing: '0.1em', marginBottom: 6 }}>
        {label}
      </p>
      <select
        value={value}
        onChange={e => onChange(e.target.value)}
        style={{
          width: '100%', padding: '7px 10px',
          background: '#071020', border: '1px solid #0d2a3a',
          borderRadius: 4, color: '#c8e8f0',
          fontFamily: "'JetBrains Mono'", fontSize: '11px',
          outline: 'none', cursor: 'pointer',
        }}
      >
        {options.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
      </select>
    </div>
  )
}

// ── Briefing Section ──────────────────────────────────────────
// ── Security Section — Voice Auth + Face Auth ─────────────────
// ── Guided Voice Enrollment wizard ───────────────────────────
function VoiceEnrollWizard({ onDone, onCancel }) {
  const TOTAL   = 5
  // enrollStep: null = idle/countdown, 1-5 = active step
  const [step,      setStep]      = useState(0)   // 0 = not started, 1-5 = phrase step
  const [phase,     setPhase]     = useState('')   // 'ready' | 'recording' | 'step_done' | 'processing' | 'done' | 'failed'
  const [phrase,    setPhrase]    = useState('')
  const [hint,      setHint]      = useState('')
  const [done,      setDone]      = useState([])   // completed step indices
  const [countdown, setCountdown] = useState(0)
  const timerRef                  = React.useRef(null)

  // Countdown tick during 'ready' phase
  React.useEffect(() => {
    if (phase === 'ready' && countdown > 0) {
      timerRef.current = setTimeout(() => setCountdown(c => c - 1), 1000)
    }
    return () => clearTimeout(timerRef.current)
  }, [phase, countdown])

  // WS listener
  React.useEffect(() => {
    const ws = new WebSocket(`ws://localhost:5051`)
    ws.onmessage = e => {
      try {
        const d = JSON.parse(e.data)
        if (d.type !== 'voice_enroll') return

        if (d.state === 'start') {
          setStep(0); setDone([]); setPhase('start')
        }
        if (d.state === 'ready') {
          setStep(d.step)
          setPhrase(d.phrase)
          setHint(d.hint || '')
          setPhase('ready')
          setCountdown(d.prep ?? 2)
        }
        if (d.state === 'recording') {
          setPhase('recording')
          setCountdown(d.seconds ?? 4)
        }
        if (d.state === 'step_done') {
          setDone(prev => [...prev, d.step])
          setPhase('step_done')
        }
        if (d.state === 'processing') {
          setPhase('processing')
        }
        if (d.state === 'done') {
          setPhase('done')
          setTimeout(() => onDone(), 1800)
        }
        if (d.state === 'failed') {
          setPhase('failed')
          setHint(d.reason || 'Unknown error')
        }
      } catch {}
    }
    return () => ws.close()
  }, [onDone])

  // Countdown tick during recording
  React.useEffect(() => {
    if (phase === 'recording' && countdown > 0) {
      timerRef.current = setTimeout(() => setCountdown(c => c - 1), 1000)
    }
    return () => clearTimeout(timerRef.current)
  }, [phase, countdown])

  const micColor = phase === 'recording' ? '#ff3d3d' : '#00e5ff'

  return (
    <div style={{
      background: '#071020',
      border: '1px solid rgba(0,229,255,0.25)',
      borderRadius: 8,
      padding: '20px 22px',
      display: 'flex',
      flexDirection: 'column',
      gap: 16,
    }}>

      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span style={{ color: '#00e5ff', fontSize: 14 }}>◎</span>
          <span style={{ color: '#00e5ff', fontFamily: "'Share Tech Mono'", fontSize: '11px', letterSpacing: '0.2em' }}>
            VOICE ENROLLMENT
          </span>
        </div>
        {phase !== 'recording' && phase !== 'processing' && (
          <button
            onClick={onCancel}
            style={{ background: 'none', border: 'none', color: '#3a6070', cursor: 'pointer', fontSize: '12px' }}
          >✕</button>
        )}
      </div>

      {/* Progress steps */}
      <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
        {Array.from({ length: TOTAL }, (_, i) => {
          const n       = i + 1
          const isDone  = done.includes(n)
          const isActive = step === n && phase !== 'done'
          return (
            <React.Fragment key={n}>
              <div style={{
                width: 28, height: 28,
                borderRadius: '50%',
                border: `1.5px solid ${isDone ? '#1db954' : isActive ? '#00e5ff' : '#1a4a5a'}`,
                background: isDone ? 'rgba(29,185,84,0.12)' : isActive ? 'rgba(0,229,255,0.1)' : 'transparent',
                display: 'flex', alignItems: 'center', justifyContent: 'center',
                transition: 'all 0.3s',
                flexShrink: 0,
              }}>
                {isDone
                  ? <span style={{ color: '#1db954', fontSize: 13 }}>✓</span>
                  : <span style={{ color: isActive ? '#00e5ff' : '#1a4a5a', fontFamily: "'Share Tech Mono'", fontSize: '10px' }}>{n}</span>
                }
              </div>
              {i < TOTAL - 1 && (
                <div style={{
                  flex: 1, height: 1,
                  background: done.includes(n) ? '#1db954' : '#0d2a3a',
                  transition: 'background 0.4s',
                }} />
              )}
            </React.Fragment>
          )
        })}
      </div>

      {/* Main content area */}
      <div style={{
        background: 'rgba(0,229,255,0.03)',
        border: '1px solid #0d2a3a',
        borderRadius: 6,
        padding: '18px 16px',
        minHeight: 110,
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        gap: 12,
        textAlign: 'center',
      }}>

        {/* start / idle */}
        {(phase === '' || phase === 'start') && (
          <p style={{ color: '#3a6070', fontFamily: "'JetBrains Mono'", fontSize: '10px', lineHeight: 1.6 }}>
            Starting guided enrollment…<br />
            <span style={{ color: '#1a4a5a', fontSize: '9px' }}>You'll read 5 short phrases aloud</span>
          </p>
        )}

        {/* ready — countdown before recording */}
        {phase === 'ready' && (
          <>
            <p style={{ color: '#3a6070', fontFamily: "'Share Tech Mono'", fontSize: '9px', letterSpacing: '0.15em' }}>
              PHRASE {step} OF {TOTAL} — READ ALOUD:
            </p>
            <p style={{
              color: '#c8e8f0',
              fontFamily: "'JetBrains Mono'",
              fontSize: '12px',
              lineHeight: 1.6,
              maxWidth: 340,
            }}>
              "{phrase}"
            </p>
            {hint && <p style={{ color: '#ffb300', fontFamily: "'Share Tech Mono'", fontSize: '9px' }}>{hint}</p>}
            <div style={{
              width: 40, height: 40,
              borderRadius: '50%',
              border: '2px solid #00e5ff',
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              color: '#00e5ff', fontFamily: "'Share Tech Mono'", fontSize: '16px',
              boxShadow: '0 0 12px rgba(0,229,255,0.3)',
            }}>
              {countdown}
            </div>
          </>
        )}

        {/* recording */}
        {phase === 'recording' && (
          <>
            <p style={{ color: '#3a6070', fontFamily: "'Share Tech Mono'", fontSize: '9px', letterSpacing: '0.15em' }}>
              PHRASE {step} OF {TOTAL} — SPEAK NOW:
            </p>
            <p style={{
              color: '#00e5ff',
              fontFamily: "'JetBrains Mono'",
              fontSize: '12px',
              lineHeight: 1.6,
              maxWidth: 340,
            }}>
              "{phrase}"
            </p>
            {/* Pulsing mic + countdown */}
            <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
              <div style={{
                width: 10, height: 10, borderRadius: '50%',
                background: '#ff3d3d', boxShadow: '0 0 8px #ff3d3d',
                animation: 'statusPulseRed 0.8s infinite',
              }} />
              <span style={{ color: '#ff3d3d', fontFamily: "'Share Tech Mono'", fontSize: '11px' }}>
                REC — {countdown}s
              </span>
            </div>
          </>
        )}

        {/* step_done between phrases */}
        {phase === 'step_done' && (
          <p style={{ color: '#1db954', fontFamily: "'Share Tech Mono'", fontSize: '10px', letterSpacing: '0.1em' }}>
            ✓ Captured · loading next phrase…
          </p>
        )}

        {/* processing */}
        {phase === 'processing' && (
          <>
            <div style={{ display: 'flex', gap: 5 }}>
              {[0,1,2].map(i => (
                <div key={i} style={{
                  width: 6, height: 6, borderRadius: '50%',
                  background: '#00e5ff',
                  animation: `blink 1s ${i * 0.2}s infinite`,
                }} />
              ))}
            </div>
            <p style={{ color: '#3a6070', fontFamily: "'Share Tech Mono'", fontSize: '9px', letterSpacing: '0.15em' }}>
              COMPUTING VOICE PROFILE…
            </p>
          </>
        )}

        {/* done */}
        {phase === 'done' && (
          <>
            <div style={{ fontSize: 28, color: '#1db954' }}>✓</div>
            <p style={{ color: '#1db954', fontFamily: "'Share Tech Mono'", fontSize: '11px', letterSpacing: '0.15em' }}>
              VOICE ENROLLED
            </p>
            <p style={{ color: '#3a6070', fontFamily: "'JetBrains Mono'", fontSize: '9px' }}>
              iZACH will recognise your voice from now on
            </p>
          </>
        )}

        {/* failed */}
        {phase === 'failed' && (
          <>
            <div style={{ fontSize: 22, color: '#ff3d3d' }}>✗</div>
            <p style={{ color: '#ff3d3d', fontFamily: "'Share Tech Mono'", fontSize: '10px' }}>ENROLLMENT FAILED</p>
            <p style={{ color: '#3a6070', fontFamily: "'JetBrains Mono'", fontSize: '9px' }}>{hint}</p>
            <Btn label="TRY AGAIN" onClick={onCancel} />
          </>
        )}
      </div>
    </div>
  )
}


function SecuritySection() {
  const base = BASE
  const [voiceStatus,    setVoiceStatus]    = useState({ enrolled: false, meta: {} })
  const [faceStatus,     setFaceStatus]     = useState({ enrolled: false })
  const [enrollingVoice, setEnrollingVoice] = useState(false)  // show wizard
  const [faceBusy,       setFaceBusy]       = useState(false)
  const [faceMsg,        setFaceMsg]        = useState('')

  const fetchStatuses = useCallback(async () => {
    try {
      const [vr, fr] = await Promise.all([
        fetch(`${base}/voice/status`).then(r => r.json()),
        fetch(`${base}/face/status`).then(r => r.json()),
      ])
      if (vr.ok)  setVoiceStatus(vr)
      if (fr.enrolled !== undefined) setFaceStatus(fr)
    } catch {}
  }, [base])

  useEffect(() => { fetchStatuses() }, [fetchStatuses])

  // Face auth WS events
  useEffect(() => {
    const ws = new WebSocket(`ws://localhost:5051`)
    ws.onmessage = e => {
      try {
        const d = JSON.parse(e.data)
        if (d.type === 'face_verify') {
          if (d.state === 'enrolling') setFaceMsg('Look at the camera…')
          if (d.state === 'done')     { setFaceMsg('Enrolled!'); setFaceBusy(false); fetchStatuses() }
          if (d.state === 'failed')   { setFaceMsg('Failed. Try again.'); setFaceBusy(false) }
        }
      } catch {}
    }
    return () => ws.close()
  }, [fetchStatuses])

  async function startVoiceEnroll() {
    setEnrollingVoice(true)
    try {
      await fetch(`${base}/voice/enroll`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ label: 'owner' }),
      })
    } catch {
      setEnrollingVoice(false)
    }
  }

  function handleEnrollDone() {
    setEnrollingVoice(false)
    fetchStatuses()
  }

  async function deleteVoice() {
    await fetch(`${base}/voice/delete`, { method: 'DELETE' })
    fetchStatuses()
  }

  async function enrollFace() {
    setFaceBusy(true)
    setFaceMsg('Starting face enrollment…')
    try {
      await fetch(`${base}/face/enroll`, { method: 'POST' })
    } catch { setFaceBusy(false); setFaceMsg('Error connecting.') }
  }

  async function deleteFace() {
    await fetch(`${base}/face/delete`, { method: 'DELETE' })
    setFaceMsg('Face data removed.')
    fetchStatuses()
  }

  const dotStyle = enrolled => ({
    display: 'inline-block',
    width: 7, height: 7, borderRadius: '50%',
    background: enrolled ? '#00e5ff' : '#1a4a5a',
    marginRight: 6,
    boxShadow: enrolled ? '0 0 6px #00e5ff' : 'none',
  })

  const labelStyle = { color: '#3a6070', fontFamily: "'JetBrains Mono'", fontSize: '9px', letterSpacing: '0.12em', marginBottom: 2 }
  const msgStyle   = { color: '#5a9ab0', fontFamily: "'JetBrains Mono'", fontSize: '9px', minHeight: 14 }

  return (
    <div style={{ padding: '4px 20px 14px', display: 'flex', flexDirection: 'column', gap: 14 }}>

      {/* ── Voice Auth ───────────────────────────── */}
      {enrollingVoice ? (
        <VoiceEnrollWizard
          onDone={handleEnrollDone}
          onCancel={() => setEnrollingVoice(false)}
        />
      ) : (
        <div style={{
          background: 'rgba(0,229,255,0.03)',
          border: '1px solid #0d2a3a',
          borderRadius: 6,
          padding: '14px 16px',
          display: 'flex',
          flexDirection: 'column',
          gap: 10,
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            <span style={{ color: '#00e5ff', fontSize: 13 }}>◎</span>
            <span style={{ color: '#c8e8f0', fontFamily: "'Share Tech Mono'", fontSize: '10px', letterSpacing: '0.15em' }}>
              VOICE AUTH
            </span>
          </div>

          <div>
            <div style={labelStyle}>STATUS</div>
            <div style={{ color: voiceStatus.enrolled ? '#00e5ff' : '#3a6070', fontFamily: "'Share Tech Mono'", fontSize: '10px' }}>
              <span style={dotStyle(voiceStatus.enrolled)} />
              {voiceStatus.enrolled ? 'ENROLLED' : 'NOT ENROLLED'}
            </div>
            {voiceStatus.enrolled && voiceStatus.meta?.enrolled_at && (
              <div style={{ color: '#1a4a5a', fontFamily: "'JetBrains Mono'", fontSize: '8px', marginTop: 3 }}>
                since {voiceStatus.meta.enrolled_at}
                {voiceStatus.meta?.samples && ` · ${voiceStatus.meta.samples} samples`}
              </div>
            )}
          </div>

          <p style={{ ...labelStyle, lineHeight: 1.5 }}>
            {voiceStatus.enrolled
              ? 'Guides through 5 phrases for re-training. Say "enroll my voice" anytime.'
              : 'Guided setup: speak 5 phrases so iZACH learns your voice.'}
          </p>

          <div style={{ display: 'flex', gap: 6 }}>
            <Btn
              label={voiceStatus.enrolled ? 'RE-ENROLL VOICE' : 'ENROLL VOICE'}
              onClick={startVoiceEnroll}
            />
            {voiceStatus.enrolled && (
              <Btn label="DELETE" onClick={deleteVoice} danger />
            )}
          </div>
        </div>
      )}

      {/* ── Face Auth ────────────────────────────── */}
      <div style={{
        background: 'rgba(0,229,255,0.03)',
        border: '1px solid #0d2a3a',
        borderRadius: 6,
        padding: '14px 16px',
        display: 'flex',
        flexDirection: 'column',
        gap: 10,
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <span style={{ color: '#00e5ff', fontSize: 13 }}>⬡</span>
          <span style={{ color: '#c8e8f0', fontFamily: "'Share Tech Mono'", fontSize: '10px', letterSpacing: '0.15em' }}>
            FACE AUTH
          </span>
        </div>

        <div>
          <div style={labelStyle}>STATUS</div>
          <div style={{ color: faceStatus.enrolled ? '#00e5ff' : '#3a6070', fontFamily: "'Share Tech Mono'", fontSize: '10px' }}>
            <span style={dotStyle(faceStatus.enrolled)} />
            {faceStatus.enrolled ? 'ENROLLED' : 'NOT ENROLLED'}
          </div>
        </div>

        <p style={{ ...labelStyle, lineHeight: 1.5 }}>
          {faceStatus.enrolled
            ? 'Used for secure file deletion. Say "enroll my face" to re-train.'
            : 'Required for secure file deletion. Say "enroll my face" or click below.'}
        </p>

        <div style={{ display: 'flex', gap: 6 }}>
          <Btn
            label={faceBusy ? 'SCANNING…' : faceStatus.enrolled ? 'RE-ENROLL FACE' : 'ENROLL FACE'}
            onClick={enrollFace}
            color={faceBusy ? '#5a9ab0' : '#00e5ff'}
          />
          {faceStatus.enrolled && (
            <Btn label="DELETE" onClick={deleteFace} danger />
          )}
        </div>

        {faceMsg && <div style={msgStyle}>{faceMsg}</div>}
      </div>
    </div>
  )
}

function BriefingSection({ form, set }) {
  const items = [
    { key: 'briefing_greeting',      label: 'Greeting + Date' },
    { key: 'briefing_weather',       label: 'Weather' },
    { key: 'briefing_news',          label: 'Top News Headlines' },
    { key: 'briefing_gold_rate',     label: 'Live Gold Rate' },
    { key: 'briefing_silver_rate',   label: 'Live Silver Rate' },
    { key: 'briefing_battery_status',label: 'Battery Percentage' },
    { key: 'briefing_battery_health',label: 'Battery Health' },
    { key: 'briefing_ram',           label: 'RAM Usage' },
    { key: 'briefing_events',        label: "Today's Calendar Events" },
    { key: 'briefing_whatsapp',      label: 'Unread WhatsApp Messages' },
  ]

  return (
    <div>
      <SectionHeader label="DAILY BRIEFING AT STARTUP" />

      <Toggle
        label="Enable auto-briefing on startup"
        checked={form.briefing_enabled ?? false}
        onChange={v => set('briefing_enabled', v)}
      />

      {/* Time input */}
      <div style={{ padding: '4px 20px 10px' }}>
        <p style={{ color: '#3a6070', fontFamily: "'Share Tech Mono'", fontSize: '9px', letterSpacing: '0.1em', marginBottom: 6 }}>
          BRIEFING TIME
        </p>
        <input
          type="time"
          value={form.morning_briefing_time ?? '08:00'}
          onChange={e => set('morning_briefing_time', e.target.value)}
          style={{
            padding: '7px 10px',
            background: '#071020',
            border: '1px solid #0d2a3a',
            borderRadius: 4,
            color: '#c8e8f0',
            fontFamily: "'JetBrains Mono'",
            fontSize: '11px',
            outline: 'none',
            colorScheme: 'dark',
          }}
          onFocus={e => e.target.style.borderColor = '#00e5ff'}
          onBlur={e  => e.target.style.borderColor = '#0d2a3a'}
        />
        <p style={{ color: '#1a4a5a', fontFamily: "'JetBrains Mono'", fontSize: '9px', marginTop: 4 }}>
          Used when "Enable auto-briefing" is on
        </p>
      </div>

      {/* Checkboxes — what to include */}
      <div style={{ padding: '0 20px 4px' }}>
        <p style={{ color: '#3a6070', fontFamily: "'Share Tech Mono'", fontSize: '9px', letterSpacing: '0.1em', marginBottom: 4 }}>
          INCLUDE IN BRIEFING
        </p>
      </div>
      {items.map(({ key, label }) => (
        <Toggle key={key} label={label} checked={form[key] ?? false} onChange={v => set(key, v)} />
      ))}
    </div>
  )
}

// ── WhatsApp Logout Row ───────────────────────────────────────
function WhatsAppLogoutRow() {
  const [msg, setMsg] = useState('')
  const [busy, setBusy] = useState(false)

  async function doLogout() {
    setBusy(true)
    setMsg('')
    try {
      const r = await fetch(`${BASE}/whatsapp/logout`, { method: 'POST' }).then(r => r.json())
      setMsg(r.ok ? 'Logged out. Rescan QR to reconnect.' : (r.error || 'Logout failed.'))
    } catch {
      setMsg('Bridge not reachable.')
    }
    setBusy(false)
  }

  return (
    <div style={{ padding: '6px 20px 10px' }}>
      <p style={{ color: '#3a6070', fontFamily: "'Share Tech Mono'", fontSize: '9px', letterSpacing: '0.1em', marginBottom: 8 }}>
        WHATSAPP SESSION
      </p>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
        <Btn label={busy ? 'LOGGING OUT...' : 'LOG OUT WHATSAPP'} onClick={doLogout} danger />
        <span style={{ color: '#3a6070', fontFamily: "'JetBrains Mono'", fontSize: '9px' }}>
          Clears session — rescan QR to reconnect
        </span>
      </div>
      {msg && (
        <p style={{ color: '#5a9ab0', fontFamily: "'JetBrains Mono'", fontSize: '9px', marginTop: 6 }}>
          {msg}
        </p>
      )}
    </div>
  )
}

// ── Keys & ID Tab ─────────────────────────────────────────────
const KEY_GROUPS = [
  {
    section: 'GROQ — CHAT / COMMANDS',
    fields: [
      { key: 'GROQ_API_KEY', label: 'GROQ API KEY', hint: 'console.groq.com — primary LLM for chat, intent, agents', password: true },
    ],
  },
  {
    section: 'GROQ — WHATSAPP DND AUTOMATION',
    fields: [
      { key: 'GROQ_WA_KEY', label: 'GROQ WA KEY', hint: 'Dedicated key for N8N auto-replies — keeps WA quota separate from chat. Falls back to chat key if empty.', password: true },
    ],
  },
  {
    section: 'GOOGLE GEMINI',
    fields: [
      { key: 'GEMINI_KEY_1', label: 'GEMINI KEY 1', hint: 'aistudio.google.com — primary Gemini key', password: true },
      { key: 'GEMINI_KEY_2', label: 'GEMINI KEY 2', hint: 'Rotated when key 1 rate-limits', password: true },
      { key: 'GEMINI_KEY_3', label: 'GEMINI KEY 3', hint: 'Rotated when key 2 rate-limits', password: true },
    ],
  },
  {
    section: 'SPOTIFY',
    fields: [
      { key: 'SPOTIPY_CLIENT_ID',     label: 'CLIENT ID',       hint: 'developer.spotify.com → your app → Settings' },
      { key: 'SPOTIPY_CLIENT_SECRET', label: 'CLIENT SECRET',   hint: 'developer.spotify.com → your app → Settings', password: true },
      { key: 'SPOTIPY_REDIRECT_URI',  label: 'REDIRECT URI',    hint: 'Must match exactly what you set in Spotify dashboard' },
    ],
  },
  {
    section: 'VISION — OPENROUTER',
    fields: [
      { key: 'OPENROUTER_API_KEY', label: 'OPENROUTER API KEY', hint: 'openrouter.ai/keys — free tier vision fallback', password: true },
    ],
  },
  {
    section: 'VISION — EDAMAM (FOOD NUTRITION)',
    fields: [
      { key: 'EDAMAM_APP_ID',  label: 'EDAMAM APP ID',  hint: 'developer.edamam.com → Food Database API' },
      { key: 'EDAMAM_APP_KEY', label: 'EDAMAM APP KEY', hint: 'developer.edamam.com → Food Database API', password: true },
    ],
  },
]

function KeysTab() {
  const allKeys = KEY_GROUPS.flatMap(g => g.fields.map(f => f.key))
  const emptyMasked = Object.fromEntries(allKeys.map(k => [k, '']))

  const [masked, setMasked] = useState(emptyMasked)
  const [edits,  setEdits]  = useState({})
  const [msg,    setMsg]    = useState('')
  const [busy,   setBusy]   = useState(false)

  useEffect(() => {
    fetch(`${BASE}/api-keys`).then(r => r.json()).then(d => {
      if (d.ok) setMasked(prev => ({ ...prev, ...d.keys }))
    }).catch(() => {})
  }, [])

  function edit(k, v) { setEdits(e => ({ ...e, [k]: v })) }

  async function save() {
    const payload = Object.fromEntries(
      Object.entries(edits).filter(([, v]) => v && v.trim())
    )
    if (!Object.keys(payload).length) { setMsg('No changes.'); return }
    setBusy(true)
    try {
      const r = await fetch(`${BASE}/api-keys`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      }).then(r => r.json())
      if (r.ok) {
        setMsg('Saved — vision & AI modules reloaded.')
        setEdits({})
        const d = await fetch(`${BASE}/api-keys`).then(r => r.json())
        if (d.ok) setMasked(prev => ({ ...prev, ...d.keys }))
      } else {
        setMsg(r.error || 'Save failed.')
      }
    } catch { setMsg('Error connecting to backend.') }
    setBusy(false)
    setTimeout(() => setMsg(''), 5000)
  }

  const labelStyle = { color: '#3a6070', fontFamily: "'Share Tech Mono'", fontSize: '9px', letterSpacing: '0.1em', marginBottom: 4 }
  const hintStyle  = { color: '#1a4a5a', fontFamily: "'JetBrains Mono'", fontSize: '8px', marginTop: 3 }

  return (
    <div>
      <div style={{ padding: '10px 20px 6px' }}>
        <p style={{ color: '#3a6070', fontFamily: "'JetBrains Mono'", fontSize: '9px', margin: 0, lineHeight: 1.6 }}>
          Paste new value to update a key. Leave blank to keep current. Groq/Gemini changes apply instantly.
        </p>
      </div>

      {KEY_GROUPS.map(({ section, fields }) => (
        <div key={section}>
          <SectionHeader label={section} />
          {fields.map(({ key, label, hint, password }) => (
            <div key={key} style={{ padding: '0 20px 10px' }}>
              <p style={labelStyle}>{label}</p>
              <input
                type={password ? 'password' : 'text'}
                value={edits[key] ?? ''}
                onChange={e => edit(key, e.target.value)}
                placeholder={masked[key] ? masked[key] : 'Not set — paste here'}
                autoComplete="off"
                style={{
                  width: '100%',
                  padding: '7px 10px',
                  background: '#071020',
                  border: '1px solid #0d2a3a',
                  borderRadius: 4,
                  color: '#c8e8f0',
                  fontFamily: "'JetBrains Mono'",
                  fontSize: '11px',
                  outline: 'none',
                  caretColor: '#00e5ff',
                }}
                onFocus={e => e.target.style.borderColor = '#00e5ff'}
                onBlur={e  => e.target.style.borderColor = '#0d2a3a'}
              />
              <p style={hintStyle}>{hint}</p>
            </div>
          ))}
        </div>
      ))}

      <div style={{ padding: '8px 20px 20px', display: 'flex', alignItems: 'center', gap: 12 }}>
        <Btn label={busy ? 'SAVING...' : 'SAVE ALL KEYS'} onClick={save} />
        {msg && <span style={{ color: '#5a9ab0', fontFamily: "'JetBrains Mono'", fontSize: '9px' }}>{msg}</span>}
      </div>
    </div>
  )
}

// ── Settings Section ──────────────────────────────────────────
function GeneralSection({ settings, onSave }) {
  const [form, setForm] = useState({
    wake_word_enabled:        settings.wake_word_enabled        ?? false,
    voice:                    settings.voice                    ?? 'en-US-ChristopherNeural',
    tts_speed:                settings.tts_speed                ?? 0,
    response_style:           settings.response_style           ?? 'casual',
    response_verbosity:       settings.response_verbosity       ?? 'balanced',
    safe_mode_enabled:        settings.safe_mode_enabled        ?? true,
    notif_performance:        settings.notif_performance        ?? true,
    notif_whatsapp:           settings.notif_whatsapp           ?? true,
    notif_downloads:          settings.notif_downloads          ?? true,
    command_history_enabled:  settings.command_history_enabled  ?? true,
    log_retention_days:       settings.log_retention_days       ?? 30,
    morning_briefing_time:    settings.morning_briefing_time    ?? '08:00',
    briefing_enabled:         settings.briefing_enabled         ?? false,
    briefing_greeting:        settings.briefing_greeting        ?? true,
    briefing_news:            settings.briefing_news            ?? false,
    briefing_gold_rate:       settings.briefing_gold_rate       ?? false,
    briefing_silver_rate:     settings.briefing_silver_rate     ?? false,
    briefing_weather:         settings.briefing_weather         ?? true,
    briefing_battery_status:  settings.briefing_battery_status  ?? true,
    briefing_battery_health:  settings.briefing_battery_health  ?? false,
    briefing_ram:             settings.briefing_ram             ?? true,
    briefing_events:          settings.briefing_events          ?? true,
    briefing_whatsapp:        settings.briefing_whatsapp        ?? false,
    ui:                       settings.ui                       ?? 'classic',
    _savedUi:                 settings.ui                       ?? 'classic',
  })
  const [dirty,      setDirty]      = useState(false)
  const [micDevices, setMicDevices] = useState([])
  const [activeMic,  setActiveMic]  = useState(null)
  const [micSaved,   setMicSaved]   = useState(false)

  useEffect(() => {
    fetch(`${BASE}/mic/devices`)
      .then(r => r.json())
      .then(d => { if (d.ok) { setMicDevices(d.devices || []); setActiveMic(d.active) } })
      .catch(() => {})
  }, [])

  function set(key, val) { setForm(f => ({ ...f, [key]: val })); setDirty(true) }

  function selectMic(index) {
    const idx = index === '' ? null : Number(index)
    setActiveMic(idx)
    fetch(`${BASE}/mic/select`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ index: idx }),
    }).then(() => { setMicSaved(true); setTimeout(() => setMicSaved(false), 2000) }).catch(() => {})
  }

  function handleSave() { onSave(form); setDirty(false) }

  const VOICES = [
    'en-US-ChristopherNeural', 'en-US-GuyNeural',
    'en-IN-PrabhatNeural', 'en-GB-RyanNeural', 'en-AU-WilliamNeural',
  ]

  return (
    <div>

      {/* ── VOICE & AUDIO ─────────────────────────── */}
      <SectionHeader label="VOICE & AUDIO" />
      <Toggle label="Wake Word Detection ('Hey iZACH')"              checked={form.wake_word_enabled}  onChange={v => set('wake_word_enabled', v)} />
      <SelectField
        label="TTS VOICE"
        value={form.voice}
        onChange={v => set('voice', v)}
        options={VOICES.map(v => ({ value: v, label: v }))}
      />

      <SelectField
        label="TTS SPEED"
        value={form.tts_speed}
        onChange={v => set('tts_speed', Number(v))}
        options={[
          { value: -25, label: 'Slow (-25%)' },
          { value: 0,   label: 'Normal' },
          { value: 25,  label: 'Fast (+25%)' },
          { value: 50,  label: 'Very Fast (+50%)' },
        ]}
      />

      {/* Mic device — direct API call, separate from Save */}
      <div style={{ padding: '4px 20px 10px' }}>
        <p style={{ color: '#3a6070', fontFamily: "'Share Tech Mono'", fontSize: '9px', letterSpacing: '0.1em', marginBottom: 6 }}>
          MIC DEVICE {micSaved && <span style={{ color: '#1db954', marginLeft: 8 }}>✓ Applied</span>}
        </p>
        <select
          value={activeMic ?? ''}
          onChange={e => selectMic(e.target.value)}
          style={{
            width: '100%', padding: '7px 10px',
            background: '#071020', border: '1px solid #0d2a3a',
            borderRadius: 4, color: '#c8e8f0',
            fontFamily: "'JetBrains Mono'", fontSize: '11px',
            outline: 'none', cursor: 'pointer',
          }}
        >
          <option value="">Default</option>
          {micDevices.map(d => (
            <option key={d.index} value={d.index}>
              {typeof d.name === 'string' ? d.name : `Device ${d.index}`}
            </option>
          ))}
        </select>
        <p style={{ color: '#1a4a5a', fontFamily: "'JetBrains Mono'", fontSize: '9px', marginTop: 4 }}>
          Applied immediately — no restart needed
        </p>
      </div>

      {/* ── INTERFACE ─────────────────────────────── */}
      <SectionHeader label="INTERFACE" />
      <SelectField
        label="UI STYLE (restart to apply)"
        value={form.ui || 'classic'}
        onChange={v => set('ui', v)}
        options={[
          { value: 'classic', label: 'Classic — React dashboard (default)' },
          { value: 'scifi',   label: 'Sci-Fi — JARVIS-style holographic UI' },
        ]}
      />
      {(form.ui || 'classic') !== (form._savedUi || 'classic') && (
        <div style={{ padding: '0 20px 10px' }}>
          <p style={{ color: '#ffb300', fontFamily: "'Share Tech Mono'", fontSize: '9px', letterSpacing: '0.1em' }}>
            ⚠ Save changes then restart iZACH to switch UI
          </p>
        </div>
      )}

      {/* ── AI BEHAVIOUR ──────────────────────────── */}
      <SectionHeader label="AI BEHAVIOUR" />
      <Toggle label="Safe Mode (confirm dangerous commands)" checked={form.safe_mode_enabled} onChange={v => set('safe_mode_enabled', v)} />

      <SelectField
        label="RESPONSE STYLE"
        value={form.response_style}
        onChange={v => set('response_style', v)}
        options={[
          { value: 'casual',       label: 'Casual (default — JARVIS-style)' },
          { value: 'professional', label: 'Professional (formal, no humor)' },
          { value: 'concise',      label: 'Concise (ultra-short answers)' },
        ]}
      />

      <SelectField
        label="RESPONSE VERBOSITY"
        value={form.response_verbosity}
        onChange={v => set('response_verbosity', v)}
        options={[
          { value: 'balanced', label: 'Balanced (default)' },
          { value: 'brief',    label: 'Brief (1-2 sentences max)' },
          { value: 'detailed', label: 'Detailed (thorough explanations)' },
        ]}
      />

      {/* ── NOTIFICATIONS ─────────────────────────── */}
      <SectionHeader label="NOTIFICATIONS" />
      <Toggle label="Performance Alerts (CPU / RAM / Battery warnings)" checked={form.notif_performance} onChange={v => set('notif_performance', v)} />
      <Toggle label="WhatsApp notifications"                             checked={form.notif_whatsapp}    onChange={v => set('notif_whatsapp', v)} />
      <Toggle label="Download completion alerts"                         checked={form.notif_downloads}   onChange={v => set('notif_downloads', v)} />

      {/* ── PRIVACY ───────────────────────────────── */}
      <SectionHeader label="PRIVACY" />
      <Toggle label="Save command history to MongoDB" checked={form.command_history_enabled} onChange={v => set('command_history_enabled', v)} />

      <SelectField
        label="LOG RETENTION"
        value={form.log_retention_days}
        onChange={v => set('log_retention_days', Number(v))}
        options={[
          { value: 7,  label: '7 days' },
          { value: 30, label: '30 days' },
          { value: 90, label: '90 days' },
          { value: 0,  label: 'Forever' },
        ]}
      />

      {/* ── DAILY BRIEFING ────────────────────────── */}
      <BriefingSection form={form} set={set} />

      {dirty && (
        <div style={{ padding: '8px 20px 16px' }}>
          <Btn label="SAVE SETTINGS" onClick={handleSave} />
          <p style={{ color: '#1a4a5a', fontFamily: "'JetBrains Mono'", fontSize: '9px', marginTop: 6 }}>
            Voice, AI, notifications &amp; privacy apply instantly. Wake word toggle needs restart.
          </p>
        </div>
      )}
    </div>
  )
}

// ── Commands reference data ───────────────────────────────────
const COMMAND_CATEGORIES = [
  {
    id: 'music',
    label: 'MUSIC & SPOTIFY',
    icon: '♪',
    commands: [
      'play something chill',
      'play study music',
      'play energetic music',
      'play <song name>',
      'pause / resume music',
      'next song / previous song',
      'set volume to 60',
      'what song is this',
      'play my liked songs',
      'what was I listening to earlier',
      'sleep timer 30 minutes',
      'cancel sleep timer',
    ],
  },
  {
    id: 'whatsapp',
    label: 'WHATSAPP',
    icon: '✉',
    commands: [
      'summarize my WhatsApp',
      'read my WhatsApp messages from <name>',
      'send a WhatsApp to <name> saying <message>',
      'what did <name> say',
      'reply to <name> — <message>',
      'any new messages on WhatsApp',
    ],
  },
  {
    id: 'system',
    label: 'SYSTEM CONTROL',
    icon: '⚙',
    commands: [
      'set volume to 50',
      'mute / unmute',
      'increase brightness',
      'turn on dark mode / light mode',
      'turn on / off wifi',
      'battery status',
      'battery health',
      'how much ram is being used',
      'what\'s my cpu temperature',
      'shut down in 30 minutes',
      'restart in 1 hour',
      'cancel shutdown',
      'boost VS Code priority',
      'set Chrome to high priority',
      'take a screenshot',
      'lock the screen',
    ],
  },
  {
    id: 'files',
    label: 'FILE MANAGER',
    icon: '📁',
    commands: [
      'open downloads folder',
      'find <filename>',
      'delete old files in downloads',
      'organize my desktop',
      'rename <file> to <new name>',
      'move <file> to documents',
      'copy <file> to desktop',
      'what\'s the largest file in downloads',
    ],
  },
  {
    id: 'web',
    label: 'WEB & BROWSER',
    icon: '🌐',
    commands: [
      'open youtube',
      'search for <query>',
      'play <query> on youtube',
      'summarize this page',
      'open a new tab',
      'close this tab',
      'get me the news',
      'what\'s the price of <product>',
      'fill my details',
    ],
  },
  {
    id: 'calendar',
    label: 'CALENDAR & REMINDERS',
    icon: '📅',
    commands: [
      'remind me to <task> at <time>',
      'what\'s on my calendar today',
      'set an alarm for 7am',
      'schedule meeting with <name> at <time>',
      'cancel my 3pm reminder',
      'what do I have tomorrow',
      'morning briefing',
    ],
  },
  {
    id: 'apps',
    label: 'APPS & WINDOWS',
    icon: '▣',
    commands: [
      'open <app name>',
      'close <app name>',
      'switch to chrome',
      'snap window to the left',
      'minimize everything',
      'open vs code',
      'open calculator',
    ],
  },
  {
    id: 'vision',
    label: 'VISION & SCREEN',
    icon: '👁',
    commands: [
      'what\'s on my screen',
      'read the screen',
      'what do you see',
      'describe what\'s in front of me',
      'take a photo',
    ],
  },
  {
    id: 'memory',
    label: 'MEMORY',
    icon: '🧠',
    commands: [
      'remember that my name is <name>',
      'remember my phone number is <number>',
      'what do you know about me',
      'forget my phone number',
      'remember my email is <email>',
    ],
  },
  {
    id: 'biometrics',
    label: 'SECURITY & BIOMETRICS',
    icon: '◎',
    commands: [
      'enroll my voice',
      'delete voice data',
      'voice status',
      'enroll my face',
      'delete my face data',
      'is my face enrolled',
    ],
  },
  {
    id: 'ai',
    label: 'AI & GENERAL',
    icon: '◈',
    commands: [
      'what can you do',
      'who are you',
      'tell me a joke',
      'what\'s the weather like',
      'translate <phrase> to hindi',
      'explain <topic>',
      'what time is it',
      'what\'s today\'s date',
    ],
  },
  {
    id: 'patterns',
    label: 'ROUTINES & PATTERNS',
    icon: '↺',
    commands: [
      'confirm routine',
      'reject routine',
      'what patterns have you learned',
      'run my morning routine',
    ],
  },
]

function CommandsSection() {
  const [open, setOpen] = useState(null)

  function toggle(id) {
    setOpen(prev => prev === id ? null : id)
  }

  return (
    <div style={{ padding: '8px 0 16px' }}>
      <div style={{ padding: '4px 20px 12px' }}>
        <p style={{ color: '#3a6070', fontFamily: "'JetBrains Mono'", fontSize: '10px', margin: 0, lineHeight: 1.6 }}>
          All voice commands. Click category to expand.
        </p>
      </div>

      {COMMAND_CATEGORIES.map(cat => {
        const isOpen = open === cat.id
        return (
          <div key={cat.id} style={{ margin: '0 12px 4px' }}>
            {/* Category header */}
            <button
              onClick={() => toggle(cat.id)}
              style={{
                width: '100%',
                display: 'flex',
                alignItems: 'center',
                gap: 10,
                padding: '8px 12px',
                background: isOpen ? 'rgba(0,229,255,0.07)' : 'rgba(0,229,255,0.02)',
                border: `1px solid ${isOpen ? 'rgba(0,229,255,0.25)' : '#0d2a3a'}`,
                borderRadius: isOpen ? '4px 4px 0 0' : 4,
                cursor: 'pointer',
                transition: 'all 0.15s',
              }}
            >
              <span style={{ color: '#00e5ff', fontSize: '12px', width: 16, textAlign: 'center' }}>{cat.icon}</span>
              <span style={{ color: isOpen ? '#00e5ff' : '#c8e8f0', fontFamily: "'Share Tech Mono'", fontSize: '10px', letterSpacing: '0.12em', flex: 1, textAlign: 'left' }}>
                {cat.label}
              </span>
              <span style={{ color: '#3a6070', fontSize: '10px', fontFamily: "'JetBrains Mono'" }}>
                {isOpen ? '▲' : '▼'}
              </span>
            </button>

            {/* Commands list */}
            {isOpen && (
              <div style={{
                background: 'rgba(0,229,255,0.02)',
                border: '1px solid rgba(0,229,255,0.15)',
                borderTop: 'none',
                borderRadius: '0 0 4px 4px',
                padding: '8px 12px 10px',
              }}>
                {cat.commands.map((cmd, i) => (
                  <div
                    key={i}
                    style={{
                      display: 'flex',
                      alignItems: 'flex-start',
                      gap: 8,
                      padding: '4px 0',
                      borderBottom: i < cat.commands.length - 1 ? '1px solid rgba(13,42,58,0.5)' : 'none',
                    }}
                  >
                    <span style={{ color: '#00e5ff', fontFamily: "'Share Tech Mono'", fontSize: '10px', marginTop: 1, opacity: 0.5 }}>›</span>
                    <span style={{ color: '#c8e8f0', fontFamily: "'JetBrains Mono'", fontSize: '10px', lineHeight: 1.5 }}>
                      {cmd}
                    </span>
                  </div>
                ))}
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}

// ── Custom Websites Section ───────────────────────────────────
function CustomWebsitesSection() {
  const [sites,   setSites]   = useState([])
  const [newName, setNewName] = useState('')
  const [newUrl,  setNewUrl]  = useState('')
  const [msg,     setMsg]     = useState('')

  async function fetchSites() {
    try {
      const r = await fetch(`${BASE}/websites`).then(r => r.json())
      if (r.ok) setSites(r.websites || [])
    } catch {}
  }

  useEffect(() => { fetchSites() }, [])

  function flash(text) { setMsg(text); setTimeout(() => setMsg(''), 4000) }

  async function addSite() {
    const name = newName.trim()
    const url  = newUrl.trim()
    if (!name || !url) return
    try {
      const r = await fetch(`${BASE}/websites`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name, url }),
      }).then(r => r.json())
      if (r.ok) {
        flash(`Added "${name}"`)
        setNewName('')
        setNewUrl('')
        fetchSites()
      } else {
        flash(r.error || 'Error adding website')
      }
    } catch { flash('Failed to connect') }
  }

  async function deleteSite(key) {
    try {
      await fetch(`${BASE}/websites/${encodeURIComponent(key)}`, { method: 'DELETE' })
      fetchSites()
    } catch {}
  }

  const rowStyle = {
    display: 'flex', alignItems: 'center', gap: 10,
    padding: '6px 8px', marginBottom: 4,
    background: 'rgba(0,229,255,0.03)',
    border: '1px solid #0d2a3a',
    borderRadius: 4,
  }

  return (
    <div>
      <SectionHeader label="CUSTOM WEBSITES" />

      <div style={{ padding: '0 20px 10px' }}>
        <p style={{ color: '#3a6070', fontFamily: "'JetBrains Mono'", fontSize: '9px', margin: 0, lineHeight: 1.6 }}>
          Say "open &lt;name&gt;" to open any custom site. Name becomes the voice trigger.
        </p>
      </div>

      <Row>
        <Input
          value={newName}
          onChange={setNewName}
          placeholder="Name (e.g. Google Slides)"
          style={{ flex: 1.2 }}
        />
        <span style={{ color: '#3a6070', fontFamily: "'Share Tech Mono'", fontSize: '12px', flexShrink: 0 }}>→</span>
        <Input
          value={newUrl}
          onChange={setNewUrl}
          placeholder="URL (e.g. slides.google.com)"
          style={{ flex: 2 }}
        />
        <Btn label="ADD" onClick={addSite} />
      </Row>

      {msg && (
        <div style={{ padding: '0 20px 8px', color: '#5a9ab0', fontFamily: "'JetBrains Mono'", fontSize: '9px' }}>
          {msg}
        </div>
      )}

      <div style={{ padding: '0 20px', maxHeight: 260, overflowY: 'auto' }}>
        {sites.length === 0 ? (
          <p style={{ color: '#1a4a5a', fontFamily: "'JetBrains Mono'", fontSize: '10px', padding: '4px 0' }}>
            No custom websites yet.
          </p>
        ) : sites.map(({ name, key, url }) => (
          <div key={key} style={rowStyle}>
            <div style={{ flex: 1, overflow: 'hidden', minWidth: 0 }}>
              <span style={{ color: '#00e5ff', fontFamily: "'Share Tech Mono'", fontSize: '10px' }}>{name}</span>
              <span style={{ color: '#3a6070', margin: '0 8px', fontSize: '10px' }}>→</span>
              <span style={{ color: '#5a9ab0', fontFamily: "'JetBrains Mono'", fontSize: '9px' }}>{url}</span>
            </div>
            <Btn label="✕" danger onClick={() => deleteSite(key)} />
          </div>
        ))}
      </div>
    </div>
  )
}

// ── Contacts Section ──────────────────────────────────────────
function ContactsSection() {
  const [contacts,  setContacts]  = useState([])
  const [newNumber, setNewNumber] = useState('')
  const [newName,   setNewName]   = useState('')
  const [msg,       setMsg]       = useState('')
  const [importing, setImporting] = useState(false)

  async function fetchContacts() {
    try {
      const r = await fetch(`${BASE}/contacts`).then(r => r.json())
      if (r.ok) setContacts(r.contacts || [])
    } catch {}
  }

  useEffect(() => { fetchContacts() }, [])

  function flash(text) {
    setMsg(text)
    setTimeout(() => setMsg(''), 4000)
  }

  async function addContact() {
    if (!newNumber.trim() || !newName.trim()) return
    try {
      const r = await fetch(`${BASE}/contacts`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ number: newNumber.trim(), name: newName.trim() }),
      }).then(r => r.json())
      if (r.ok) {
        flash(`Added ${r.name}`)
        setNewNumber('')
        setNewName('')
        fetchContacts()
      } else {
        flash(r.error || 'Error adding contact')
      }
    } catch { flash('Failed to connect') }
  }

  async function deleteContact(number) {
    try {
      await fetch(`${BASE}/contacts/${encodeURIComponent(number)}`, { method: 'DELETE' })
      fetchContacts()
    } catch {}
  }

  async function importFile(e) {
    const file = e.target.files?.[0]
    if (!file) return
    setImporting(true)
    flash('Importing...')
    try {
      const fd = new FormData()
      fd.append('file', file)
      const r = await fetch(`${BASE}/contacts/import`, { method: 'POST', body: fd }).then(r => r.json())
      if (r.ok) {
        flash(`Imported ${r.imported} contacts · ${r.total} total`)
        fetchContacts()
      } else {
        flash(r.error || 'Import failed')
      }
    } catch { flash('Import error') }
    setImporting(false)
    e.target.value = ''
  }

  const rowStyle = {
    display: 'flex', alignItems: 'center', gap: 10,
    padding: '6px 8px', marginBottom: 4,
    background: 'rgba(0,229,255,0.03)',
    border: '1px solid #0d2a3a',
    borderRadius: 4,
  }

  return (
    <div>
      <SectionHeader label="WHATSAPP CONTACTS" />

      {/* Import from file */}
      <Row>
        <label style={{
          padding: '6px 14px',
          background: 'rgba(0,229,255,0.07)',
          border: '1px solid rgba(0,229,255,0.25)',
          borderRadius: 4,
          color: importing ? '#5a9ab0' : '#00e5ff',
          fontFamily: "'Share Tech Mono'",
          fontSize: '10px',
          letterSpacing: '0.1em',
          cursor: importing ? 'not-allowed' : 'pointer',
          flexShrink: 0,
        }}>
          {importing ? 'IMPORTING...' : 'IMPORT CSV / VCF'}
          <input type="file" accept=".csv,.vcf" onChange={importFile}
            style={{ display: 'none' }} disabled={importing} />
        </label>
        <span style={{ color: '#3a6070', fontFamily: "'JetBrains Mono'", fontSize: '9px' }}>
          Google Contacts export or phone export
        </span>
      </Row>

      {/* Add single */}
      <Row>
        <Input value={newNumber} onChange={setNewNumber} placeholder="Phone number (e.g. 919810001234)" style={{ flex: '1.5' }} />
        <Input value={newName}   onChange={setNewName}   placeholder="Name (e.g. Mummy)" />
        <Btn label="ADD" onClick={addContact} />
      </Row>

      {msg && (
        <div style={{ padding: '0 20px 8px', color: '#5a9ab0', fontFamily: "'JetBrains Mono'", fontSize: '9px' }}>
          {msg}
        </div>
      )}

      {/* List */}
      <div style={{ padding: '0 20px', maxHeight: 240, overflowY: 'auto' }}>
        {contacts.length === 0 ? (
          <p style={{ color: '#1a4a5a', fontFamily: "'JetBrains Mono'", fontSize: '10px', padding: '4px 0' }}>
            No contacts. Import a file or add manually.
          </p>
        ) : contacts.map(({ number, name }) => (
          <div key={number} style={rowStyle}>
            <div style={{ flex: 1, overflow: 'hidden' }}>
              <span style={{ color: '#00e5ff', fontFamily: "'Share Tech Mono'", fontSize: '10px' }}>{name}</span>
              <span style={{ color: '#1a4a5a', fontFamily: "'JetBrains Mono'", fontSize: '9px', marginLeft: 10 }}>{number}</span>
            </div>
            <Btn label="✕" danger onClick={() => deleteContact(number)} />
          </div>
        ))}
      </div>
    </div>
  )
}

// ── Main SettingsPanel export ─────────────────────────────────
export default function SettingsPanel({
  memoryEntries,
  settings,
  onAddMemory,
  onDeleteMemory,
  onSaveSettings,
}) {
  const [tab, setTab] = useState('memory')

  const tabs = [
    { id: 'memory',   label: 'MEMORY'   },
    { id: 'general',  label: 'SETTINGS' },
    { id: 'websites', label: 'WEBSITES' },
    { id: 'keys',     label: 'KEYS & ID'},
    { id: 'contacts', label: 'CONTACTS' },
    { id: 'security', label: 'SECURITY' },
    { id: 'commands', label: 'COMMANDS' },
  ]

  return (
    <div style={{
      display: 'flex', flexDirection: 'column', height: '100%',
      background: '#0a1628', borderLeft: '1px solid #0d2a3a',
      overflowY: 'auto',
    }}>
      {/* Tab bar */}
      <div style={{
        display: 'flex',
        borderBottom: '1px solid #0d2a3a',
        flexShrink: 0,
      }}>
        {tabs.map(t => (
          <button
            key={t.id}
            onClick={() => setTab(t.id)}
            style={{
              flex: 1,
              padding: '10px 0',
              background: tab === t.id ? 'rgba(0,229,255,0.07)' : 'transparent',
              border: 'none',
              borderBottom: tab === t.id ? '2px solid #00e5ff' : '2px solid transparent',
              color: tab === t.id ? '#00e5ff' : '#3a6070',
              fontFamily: "'Share Tech Mono'",
              fontSize: '10px',
              letterSpacing: '0.15em',
              cursor: 'pointer',
              transition: 'all 0.18s',
              boxShadow: tab === t.id ? 'inset 0 -1px 8px rgba(0,229,255,0.08)' : 'none',
              textShadow: tab === t.id ? '0 0 8px rgba(0,229,255,0.4)' : 'none',
            }}
            onMouseEnter={e => { if (tab !== t.id) e.currentTarget.style.color = '#c8e8f0' }}
            onMouseLeave={e => { if (tab !== t.id) e.currentTarget.style.color = '#3a6070' }}
          >
            {t.label}
          </button>
        ))}
      </div>

      {/* Content — key forces remount on tab change → triggers tabEnter animation */}
      <div key={tab} className="tab-content" style={{ flex: 1, overflowY: 'auto' }}>
        {tab === 'memory' && (
          <MemorySection
            entries={memoryEntries}
            onAdd={onAddMemory}
            onDelete={onDeleteMemory}
          />
        )}
        {tab === 'general' && (
          <GeneralSection
            settings={settings}
            onSave={onSaveSettings}
          />
        )}
        {tab === 'websites' && (
          <CustomWebsitesSection />
        )}
        {tab === 'keys' && (
          <KeysTab />
        )}
        {tab === 'contacts' && (
          <ContactsSection />
        )}
        {tab === 'security' && (
          <>
            <div style={{ padding: '12px 20px 8px', display: 'flex', alignItems: 'center', gap: 8 }}>
              <span style={{ color: '#00e5ff' }}>*</span>
              <span style={{ color: '#00e5ff', fontFamily: "'Share Tech Mono'", fontSize: '10px', letterSpacing: '0.2em' }}>
                BIOMETRIC SECURITY
              </span>
              <div style={{ flex: 1, height: 1, background: '#0d2a3a' }} />
            </div>
            <div style={{ padding: '0 20px 8px' }}>
              <p style={{ color: '#3a6070', fontFamily: "'JetBrains Mono'", fontSize: '9px', margin: 0, lineHeight: 1.6 }}>
                Voice auth identifies who is speaking. Face auth gates secure actions like file deletion.
              </p>
            </div>
            <SecuritySection />
            <div style={{ padding: '0 20px 4px' }}>
              <p style={{ color: '#1a4a5a', fontFamily: "'JetBrains Mono'", fontSize: '9px', lineHeight: 1.6, margin: 0 }}>
                Voice commands: "enroll my voice" · "enroll my face" · "delete voice data" · "delete face data"
              </p>
            </div>
            <div style={{ height: 1, background: '#0d2a3a', margin: '8px 20px' }} />
            <WhatsAppLogoutRow />
          </>
        )}
        {tab === 'commands' && (
          <CommandsSection />
        )}
      </div>
    </div>
  )
}