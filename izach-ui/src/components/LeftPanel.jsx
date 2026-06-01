import React, { useState, useEffect, useRef } from 'react'
import CameraPanel from './CameraPanel.jsx'

const BASE = 'http://localhost:5050'

// ─── Widget registry ─────────────────────────────────────────────────────────
const ALL_WIDGETS = [
  { id: 'vitals',    label: 'SYSTEM VITALS', defaultOn: true  },
  { id: 'hardware',  label: 'HARDWARE',       defaultOn: true  },
  { id: 'spotify',   label: 'SPOTIFY',        defaultOn: false },
  { id: 'fitness',   label: 'GOOGLE FIT',     defaultOn: false },
  { id: 'location',  label: 'LOCATION',       defaultOn: false },
  { id: 'smarthome', label: 'SMART HOME',     defaultOn: false },
  { id: 'calendar',  label: 'CALENDAR',       defaultOn: false },
  { id: 'whatsapp',  label: 'WHATSAPP',       defaultOn: false },
  { id: 'phone',     label: 'PHONE',          defaultOn: false },
  { id: 'notifs',    label: 'NOTIFICATIONS',  defaultOn: false },
  { id: 'ocr',       label: 'DOCUMENT OCR',   defaultOn: false },
]

// ─── localStorage ─────────────────────────────────────────────────────────────
const LS_ORDER     = 'lp_widget_order_v3'
const LS_ENABLED   = 'lp_widget_enabled_v3'
const LS_COLLAPSED = 'lp_widget_collapsed_v3'

function loadOrder() {
  try {
    const saved = JSON.parse(localStorage.getItem(LS_ORDER) || '[]')
    const allIds = ALL_WIDGETS.map(w => w.id)
    const savedSet = new Set(saved)
    return [...saved.filter(id => allIds.includes(id)), ...allIds.filter(id => !savedSet.has(id))]
  } catch { return ALL_WIDGETS.map(w => w.id) }
}

function loadEnabled() {
  try {
    const saved = JSON.parse(localStorage.getItem(LS_ENABLED) || '{}')
    const out = {}
    ALL_WIDGETS.forEach(w => { out[w.id] = w.id in saved ? saved[w.id] : w.defaultOn })
    return out
  } catch {
    const out = {}
    ALL_WIDGETS.forEach(w => { out[w.id] = w.defaultOn })
    return out
  }
}

function loadCollapsed() {
  try { return JSON.parse(localStorage.getItem(LS_COLLAPSED) || '{}') }
  catch { return {} }
}

// ─── Shared theme helpers ─────────────────────────────────────────────────────
const T = {
  mono:  { fontFamily: "'Share Tech Mono'" },
  code:  { fontFamily: "'JetBrains Mono'" },
  label: { fontFamily: "'Share Tech Mono'", fontSize: 8, color: 'rgba(0,148,255,0.4)', letterSpacing: '.15em', textTransform: 'uppercase', marginBottom: 4 },
  row:   { display: 'flex', gap: 4, flexWrap: 'wrap', marginBottom: 4 },
  btn:   { flex: 1, minWidth: 0, background: 'rgba(0,148,255,0.08)', border: '1px solid rgba(0,148,255,0.18)', borderRadius: 4, color: 'rgba(0,148,255,0.8)', fontFamily: "'Share Tech Mono'", fontSize: 8, padding: '4px 3px', cursor: 'pointer' },
  inp:   { background: 'rgba(0,10,28,0.8)', border: '1px solid rgba(0,148,255,0.18)', borderRadius: 3, color: 'rgba(0,200,255,0.85)', fontFamily: "'Share Tech Mono'", fontSize: 8, padding: '3px 6px', outline: 'none', width: '100%', boxSizing: 'border-box' },
  sep:   { height: 1, margin: '6px 0', background: 'rgba(0,148,255,0.07)' },
}

function Divider() { return <div style={{ height: 1, margin: '0 12px', background: '#0d2a3a' }} /> }

// ─── Collapsible Widget Wrapper ───────────────────────────────────────────────
function Widget({ id, label, collapsed, onToggle, children }) {
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
        <span style={{ color: '#00e5ff', fontFamily: "'Share Tech Mono'", fontSize: '10px', letterSpacing: '0.2em', flexShrink: 0 }}>
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

// ─── System Vitals ────────────────────────────────────────────────────────────
function vitalColor(v) { return v > 85 ? '#ff3d3d' : v > 65 ? '#ffb300' : '#00e5ff' }

function Sparkline({ data, color }) {
  const W = 48, H = 14
  const max = Math.max(...data, 1)
  const pts = data.map((v, i) => `${(i / (data.length - 1)) * W},${H - (v / max) * H}`).join(' ')
  const last = data[data.length - 1]
  const lx = W, ly = H - (last / max) * H
  return (
    <svg width={W} height={H} style={{ overflow: 'visible', flexShrink: 0 }}>
      <polyline points={pts} fill="none" stroke={color} strokeWidth="1.1" strokeOpacity="0.45" strokeLinejoin="round" />
      <circle cx={lx} cy={ly} r="1.8" fill={color} fillOpacity="0.85" />
    </svg>
  )
}

function VitalBar({ label, value, history }) {
  const safeValue = Math.min(100, Math.max(0, value || 0))
  const color = vitalColor(safeValue)
  const critical = safeValue > 85
  return (
    <div style={{ marginBottom: 10, paddingLeft: 12, paddingRight: 12 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 3 }}>
        <span style={{ color: '#3a6070', fontFamily: "'JetBrains Mono'", fontSize: '10px' }}>{label}</span>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          {critical && <span style={{ width: 5, height: 5, borderRadius: '50%', background: '#ff3d3d', boxShadow: '0 0 5px #ff3d3d', display: 'inline-block', flexShrink: 0 }} />}
          <Sparkline data={history} color={color} />
          <span style={{ color, fontFamily: "'Share Tech Mono'", fontSize: '10px', minWidth: 30, textAlign: 'right' }}>{safeValue}%</span>
        </div>
      </div>
      <div style={{ height: 3, background: '#0d2a3a', borderRadius: 2, overflow: 'hidden' }}>
        <div style={{ height: '100%', width: `${safeValue}%`, background: `linear-gradient(90deg, ${color}55, ${color})`, boxShadow: `0 0 6px ${color}88`, borderRadius: 2, transition: 'width 0.7s ease' }} />
      </div>
    </div>
  )
}

function VitalsWidget({ cpuUsage, ramUsage, gpuUsage, procCpu, procMem }) {
  const HIST = 22
  const [cpuH, setCpuH] = useState(Array(HIST).fill(0))
  const [ramH, setRamH] = useState(Array(HIST).fill(0))
  const [gpuH, setGpuH] = useState(Array(HIST).fill(0))
  useEffect(() => { setCpuH(h => [...h.slice(1), cpuUsage || 0]) }, [cpuUsage])
  useEffect(() => { setRamH(h => [...h.slice(1), ramUsage || 0]) }, [ramUsage])
  useEffect(() => { setGpuH(h => [...h.slice(1), gpuUsage || 0]) }, [gpuUsage])
  return (
    <>
      <VitalBar label="CPU" value={cpuUsage} history={cpuH} />
      <VitalBar label="RAM" value={ramUsage} history={ramH} />
      <VitalBar label="GPU" value={gpuUsage} history={gpuH} />
      <div style={{ padding: '2px 12px 10px' }}>
        <p style={{ color: '#1a4a5a', fontFamily: "'Share Tech Mono'", fontSize: '8px', letterSpacing: '0.15em', marginBottom: 5 }}>iZACH PROCESS</p>
        {[['CPU', `${procCpu ?? 0}%`], ['MEM', `${procMem ?? 0}%`]].map(([k, v]) => (
          <div key={k} style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 3 }}>
            <span style={{ color: '#1a4a5a', fontFamily: "'JetBrains Mono'", fontSize: '10px' }}>{k}</span>
            <span style={{ color: '#00e5ff', fontFamily: "'Share Tech Mono'", fontSize: '10px' }}>{v}</span>
          </div>
        ))}
      </div>
    </>
  )
}

// ─── Spotify Widget ───────────────────────────────────────────────────────────
async function spotifyAction(action) {
  try { await fetch(`${BASE}/spotify/control`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ action }) }) } catch {}
}

function SpotifyWidget({ track }) {
  // track may be undefined/null before first fetch — safe defaults
  const t = track || {}
  const { playing = false, title = '—', artist = '', device = '—', albumArt = null, progress = 0, duration = 0, volume = 0 } = t
  const pct = duration > 0 ? (progress / duration) * 100 : 0

  return (
    <div style={{ padding: '0 12px 12px' }}>
      <div style={{ display: 'flex', gap: 10, marginBottom: 10 }}>
        <div style={{ width: 38, height: 38, flexShrink: 0, borderRadius: 4, overflow: 'hidden', background: '#0d2a3a', border: '1px solid #1a4a5a', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
          {albumArt
            ? <img src={albumArt} alt="art" style={{ width: '100%', height: '100%', objectFit: 'cover' }} />
            : <svg width="14" height="14" viewBox="0 0 24 24" fill="none"><circle cx="12" cy="12" r="10" fill={playing ? '#1db954' : '#1a4a5a'} /><polygon points="10,8 16,12 10,16" fill="#050d1a" /></svg>
          }
        </div>
        <div style={{ overflow: 'hidden', flex: 1 }}>
          <p style={{ color: playing ? '#c8e8f0' : '#3a6070', fontFamily: "'JetBrains Mono'", fontSize: '10px', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis', marginBottom: 2 }}>{title}</p>
          <p style={{ color: '#3a6070', fontFamily: "'JetBrains Mono'", fontSize: '9px', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{artist}</p>
        </div>
      </div>
      {/* Progress */}
      <div style={{ height: 2, background: '#0d2a3a', borderRadius: 1, overflow: 'hidden', marginBottom: 8 }}>
        <div style={{ height: '100%', width: `${pct}%`, background: playing ? '#1db954' : '#1a4a5a', boxShadow: playing ? '0 0 4px #1db95466' : 'none', borderRadius: 1, transition: 'width 1s linear' }} />
      </div>
      {/* Device */}
      <p style={{ color: '#1a4a5a', fontFamily: "'Share Tech Mono'", fontSize: '8px', letterSpacing: '0.12em', marginBottom: 3 }}>DEVICE</p>
      <p style={{ color: '#3a6070', fontFamily: "'JetBrains Mono'", fontSize: '9px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', marginBottom: 8 }}>{device}</p>
      {/* Volume */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 8 }}>
        <span style={{ color: '#1a4a5a', fontSize: '9px' }}>◁</span>
        <div style={{ flex: 1, height: 2, background: '#0d2a3a', borderRadius: 1 }}>
          <div style={{ height: '100%', width: `${volume}%`, background: 'linear-gradient(90deg, #005060, #00e5ff)', borderRadius: 1, transition: 'width 0.5s ease' }} />
        </div>
        <span style={{ color: '#3a6070', fontFamily: "'Share Tech Mono'", fontSize: '9px' }}>{volume}%</span>
      </div>
      {/* Controls */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 8 }}>
        {[{ label: '⏮', action: 'prev' }, { label: playing ? '⏸' : '▶', action: 'playpause' }, { label: '⏭', action: 'next' }].map(btn => (
          <button key={btn.action} onClick={() => spotifyAction(btn.action)} style={{ background: 'rgba(0,229,255,0.06)', border: '1px solid #0d2a3a', borderRadius: 4, color: '#00e5ff', fontFamily: "'Share Tech Mono'", fontSize: '13px', width: 32, height: 28, cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
            {btn.label}
          </button>
        ))}
      </div>
      {!playing && <p style={{ color: '#1a4a5a', fontFamily: "'Share Tech Mono'", fontSize: '9px', letterSpacing: '0.1em', marginTop: 8 }}>NOTHING PLAYING</p>}
    </div>
  )
}

// ─── Google Fit Widget ────────────────────────────────────────────────────────
function FitnessWidget() {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(false)
  const [codeRow, setCodeRow] = useState(false)
  const [authCode, setAuthCode] = useState('')

  const refresh = async () => {
    try { const r = await fetch(`${BASE}/fitness/summary`); setData(await r.json()) } catch {}
  }
  useEffect(() => { refresh() }, [])

  const startAuth = async () => {
    try {
      const r = await fetch(`${BASE}/fitness/auth/start`)
      const d = await r.json()
      if (d.error) { alert(d.error); return }
      window.open(d.url, '_blank'); setCodeRow(true)
    } catch { alert('Cannot reach backend') }
  }
  const completeAuth = async () => {
    if (!authCode.trim()) return
    setLoading(true)
    try {
      const r = await fetch(`${BASE}/fitness/auth/complete`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ code: authCode }) })
      const d = await r.json()
      if (d.error) { alert(d.error); return }
      setCodeRow(false); setAuthCode(''); refresh()
    } catch { alert('Cannot reach backend') }
    setLoading(false)
  }

  const pct = data?.steps ? Math.min(100, Math.round(data.steps / 10000 * 100)) : 0
  const connected = data?.connected

  return (
    <div style={{ padding: '0 12px 10px' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
        <div style={{ width: 7, height: 7, borderRadius: '50%', background: connected ? '#1db954' : 'rgba(0,148,255,0.2)', boxShadow: connected ? '0 0 6px #1db954' : 'none' }} />
        <span style={{ fontSize: 8, letterSpacing: '0.25em', color: connected ? '#1db954' : 'rgba(0,148,255,0.4)', fontFamily: "'Share Tech Mono'" }}>
          {connected ? 'CONNECTED' : 'NOT CONNECTED'}
        </span>
        {connected && <button onClick={refresh} style={{ marginLeft: 'auto', background: 'none', border: 'none', color: 'rgba(0,200,255,0.5)', cursor: 'pointer', fontSize: 12 }}>↻</button>}
      </div>

      {!connected && <button onClick={startAuth} style={{ width: '100%', padding: '6px 0', marginBottom: 6, background: 'rgba(0,148,255,0.1)', border: '1px solid rgba(0,148,255,0.3)', borderRadius: 3, color: 'rgba(0,200,255,0.8)', fontFamily: "'Share Tech Mono'", fontSize: 9, letterSpacing: '0.15em', cursor: 'pointer' }}>⊕ CONNECT GOOGLE FIT</button>}

      {codeRow && (
        <div style={{ marginBottom: 8 }}>
          <div style={{ fontSize: 7, color: 'rgba(0,148,255,0.4)', letterSpacing: '0.2em', marginBottom: 4 }}>PASTE AUTH CODE:</div>
          <div style={{ display: 'flex', gap: 5 }}>
            <input value={authCode} onChange={e => setAuthCode(e.target.value)} placeholder="4/0AX…" style={{ flex: 1, background: 'rgba(0,10,28,0.8)', border: '1px solid rgba(0,148,255,0.2)', borderRadius: 2, color: 'rgba(0,200,255,0.8)', fontFamily: "'Share Tech Mono'", fontSize: 8, padding: '4px 6px', outline: 'none' }} />
            <button onClick={completeAuth} disabled={loading} style={{ padding: '4px 10px', background: 'rgba(0,148,255,0.15)', border: '1px solid rgba(0,148,255,0.35)', borderRadius: 2, color: 'rgba(0,200,255,0.8)', fontFamily: "'Share Tech Mono'", fontSize: 8, cursor: 'pointer' }}>OK</button>
          </div>
        </div>
      )}

      {connected && data && (
        <>
          <div style={{ fontSize: 7, color: 'rgba(0,148,255,0.35)', letterSpacing: '0.3em', marginBottom: 8 }}>TODAY — {data.date || '—'}</div>
          <div style={{ display: 'flex', gap: 6, marginBottom: 10 }}>
            {[
              [(data.steps || 0).toLocaleString(), 'STEPS', 'rgba(0,200,255,0.9)'],
              [Math.round(data.calories || 0), 'KCAL', 'rgba(255,140,80,0.9)'],
              [data.active_minutes || 0, 'ACT MIN', 'rgba(80,220,120,0.9)'],
            ].map(([val, lbl, color]) => (
              <div key={lbl} style={{ flex: 1, background: 'rgba(0,10,28,0.7)', border: '1px solid rgba(0,148,255,0.1)', borderRadius: 4, padding: '6px 3px', textAlign: 'center' }}>
                <div style={{ fontSize: 13, color, fontFamily: "'Share Tech Mono'" }}>{val}</div>
                <div style={{ fontSize: 6, color: 'rgba(0,148,255,0.4)', letterSpacing: '0.2em', marginTop: 2 }}>{lbl}</div>
              </div>
            ))}
          </div>
          <div style={{ fontSize: 7, color: 'rgba(0,148,255,0.4)', letterSpacing: '0.15em', marginBottom: 4, display: 'flex', justifyContent: 'space-between' }}>
            <span>STEP GOAL (10K)</span><span>{pct}%</span>
          </div>
          <div style={{ height: 3, background: 'rgba(0,148,255,0.08)', borderRadius: 2, overflow: 'hidden' }}>
            <div style={{ height: '100%', width: pct + '%', background: '#00c8ff', borderRadius: 2, transition: 'width 0.6s ease' }} />
          </div>
        </>
      )}
    </div>
  )
}

// ─── Location Widget ──────────────────────────────────────────────────────────
function LocationWidget() {
  const [loc, setLoc] = useState(null)
  const [labelInput, setLabelInput] = useState('')

  const refresh = async () => {
    try { const r = await fetch(`${BASE}/location/status`); setLoc(await r.json()) } catch {}
  }
  const toggle = async () => {
    try {
      await fetch(`${BASE}/location/toggle`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ enabled: !loc?.engine_running }) })
      refresh()
    } catch {}
  }
  const saveLabel = async () => {
    const label = labelInput.trim()
    if (!label || !loc?.pc?.ssid) return
    try {
      await fetch(`${BASE}/location/label-ssid`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ ssid: loc.pc.ssid, label }) })
      setLabelInput(''); refresh()
    } catch {}
  }
  useEffect(() => { refresh() }, [])

  const phone = loc?.phone || {}
  const pc = loc?.pc || {}
  const active = phone.active && phone.lat
  const running = loc?.engine_running
  const ago = phone.ts ? Math.round((Date.now() / 1000 - phone.ts) / 60) : null

  return (
    <div style={{ padding: '0 12px 10px' }}>
      <button onClick={toggle} style={{ width: '100%', padding: '6px 0', marginBottom: 10, background: running ? 'rgba(255,50,50,0.07)' : 'rgba(0,148,255,0.08)', border: `1px solid ${running ? 'rgba(255,80,80,0.35)' : 'rgba(0,148,255,0.3)'}`, borderRadius: 3, color: running ? 'rgba(255,100,100,0.8)' : 'rgba(0,200,255,0.8)', fontFamily: "'Share Tech Mono'", fontSize: 9, letterSpacing: '0.2em', cursor: 'pointer', transition: 'all 0.2s' }}>
        {running ? '■ STOP TRACKING' : '▶ START TRACKING'}
      </button>
      {/* Phone GPS */}
      <div style={{ marginBottom: 10 }}>
        <div style={{ fontSize: 7, color: 'rgba(0,148,255,0.32)', letterSpacing: '0.35em', marginBottom: 6 }}>PHONE GPS</div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 5 }}>
          <div style={{ width: 7, height: 7, borderRadius: '50%', flexShrink: 0, background: active ? '#1db954' : 'rgba(0,148,255,0.2)', boxShadow: active ? '0 0 6px #1db954' : 'none' }} />
          <span style={{ fontSize: 8, letterSpacing: '0.2em', color: active ? '#1db954' : 'rgba(0,148,255,0.4)', fontFamily: "'Share Tech Mono'" }}>{active ? 'ACTIVE' : 'NO SIGNAL'}</span>
          <button onClick={refresh} style={{ marginLeft: 'auto', background: 'none', border: 'none', color: 'rgba(0,200,255,0.5)', cursor: 'pointer', fontSize: 12 }}>↻</button>
        </div>
        {active ? (
          <>
            <div style={{ fontSize: 10, color: 'rgba(0,200,255,0.75)', letterSpacing: '0.1em', marginBottom: 3 }}>{phone.place_name || 'Locating…'}</div>
            <div style={{ display: 'flex', gap: 10, fontSize: 7, color: 'rgba(0,148,255,0.35)', letterSpacing: '0.1em' }}>
              <span>LAT {phone.lat?.toFixed(4)}</span><span>LON {phone.lon?.toFixed(4)}</span>
            </div>
            <div style={{ fontSize: 7, color: 'rgba(0,148,255,0.25)', marginTop: 3 }}>LAST: {ago === null ? '—' : ago < 1 ? 'just now' : `${ago}m ago`}</div>
          </>
        ) : (
          <div style={{ fontSize: 8, color: 'rgba(0,148,255,0.3)', marginTop: 4 }}>
            Open <span style={{ color: 'rgba(0,200,255,0.5)' }}>location_companion.html</span> on your phone
          </div>
        )}
      </div>
      <Divider />
      {/* PC Network */}
      <div style={{ marginTop: 8, marginBottom: 10 }}>
        <div style={{ fontSize: 7, color: 'rgba(0,148,255,0.32)', letterSpacing: '0.35em', marginBottom: 6 }}>PC NETWORK</div>
        <div style={{ fontSize: 10, color: 'rgba(0,200,255,0.65)' }}>{pc.city ? `${pc.city}, ${pc.country || ''}` : '—'}</div>
        <div style={{ fontSize: 7, color: 'rgba(0,148,255,0.35)', letterSpacing: '0.2em', marginTop: 3 }}>WIFI: {pc.ssid || '—'}</div>
        {pc.label && <div style={{ fontSize: 8, color: 'rgba(0,200,255,0.5)', marginTop: 3 }}>▸ {pc.label}</div>}
      </div>
      {/* Label SSID */}
      <div style={{ fontSize: 7, color: 'rgba(0,148,255,0.32)', letterSpacing: '0.35em', marginBottom: 5 }}>LABEL THIS WIFI</div>
      <div style={{ display: 'flex', gap: 5 }}>
        <input value={labelInput} onChange={e => setLabelInput(e.target.value)} onKeyDown={e => e.key === 'Enter' && saveLabel()} placeholder="Home / College / Gym…" style={{ flex: 1, background: 'rgba(0,10,28,0.8)', border: '1px solid rgba(0,148,255,0.15)', borderRadius: 2, color: 'rgba(0,200,255,0.8)', fontFamily: "'Share Tech Mono'", fontSize: 8, padding: '4px 6px', outline: 'none' }} />
        <button onClick={saveLabel} style={{ padding: '4px 8px', background: 'rgba(0,148,255,0.12)', border: '1px solid rgba(0,148,255,0.3)', borderRadius: 2, color: 'rgba(0,200,255,0.8)', fontFamily: "'Share Tech Mono'", fontSize: 8, cursor: 'pointer' }}>SAVE</button>
      </div>
    </div>
  )
}

// ─── Smart Home Widget ────────────────────────────────────────────────────────
function SmartHomeWidget() {
  const [data, setData] = useState({})
  const [cmd, setCmd] = useState('')
  const [msg, setMsg] = useState({ text: '', ok: true })
  const [acTemp, setAcTemp] = useState({})
  const [acStatus, setAcStatus] = useState({})
  const [tvIp, setTvIp] = useState('')

  const flash = (text, ok = true) => { setMsg({ text, ok }); setTimeout(() => setMsg({ text: '', ok: true }), 4000) }

  const refresh = async () => {
    try {
      const r = await fetch(`${BASE}/smarthome/status`)
      const d = await r.json()
      setData(d)
      const s = d.settings || {}
      if (s.samsung_tv_ip && !tvIp) setTvIp(s.samsung_tv_ip)
    } catch {}
  }
  useEffect(() => { refresh() }, [])

  async function _post(path, body) {
    try {
      const r = await fetch(`${BASE}/smarthome/${path}`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
      return await r.json()
    } catch { return { success: false, error: 'Backend error' } }
  }

  const sendCmd = async () => {
    if (!cmd.trim()) return
    flash('Sending…')
    const d = await _post('command', { command: cmd })
    flash(d.message || d.error || 'Done', d.success !== false)
    setCmd('')
    if (d.success) setTimeout(refresh, 1500)
  }
  const tvCtrl = async (action, value) => { const d = await _post('samsung/tv/control', { action, value, ip: tvIp }); flash(d.message || d.error || '', d.success !== false) }
  const acOn   = async (id) => { const d = await _post('smartthings/ac/onoff', { device_id: id, on: true  }); flash(d.message || d.error || '', d.success) }
  const acOff  = async (id) => { const d = await _post('smartthings/ac/onoff', { device_id: id, on: false }); flash(d.message || d.error || '', d.success) }
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
      setAcStatus(prev => ({ ...prev, [id]: parts.join(' · ') || 'No data' }))
    } catch {}
  }
  const acSetTemp = async (id, mode) => { const d = await _post('smartthings/ac/temperature', { device_id: id, temp_c: parseFloat(acTemp[id] || 24), mode }); flash(d.message || d.error || '', d.success) }
  const acSetFan  = async (id, sp)   => { const d = await _post('smartthings/ac/fan',         { device_id: id, speed: sp }); flash(d.message || d.error || '', d.success) }

  const st    = data.smartthings || {}
  const stDev = (st.devices || []).filter(d => d.category === 'ac')
  const cast  = data.cast || {}
  const tvInfo = data.samsung_tv || {}

  const S = {
    lbl:  { fontFamily: "'Share Tech Mono'", fontSize: 7, color: 'rgba(0,148,255,0.4)', letterSpacing: '.15em', textTransform: 'uppercase', marginBottom: 4 },
    row:  { display: 'flex', gap: 4, flexWrap: 'wrap', marginBottom: 4 },
    btn:  { flex: 1, minWidth: 0, background: 'rgba(0,148,255,0.08)', border: '1px solid rgba(0,148,255,0.18)', borderRadius: 4, color: 'rgba(0,148,255,0.8)', fontFamily: "'Share Tech Mono'", fontSize: 7, padding: '4px 3px', cursor: 'pointer' },
    rbtn: { flex: '0 0 auto', background: 'rgba(255,80,80,0.07)', border: '1px solid rgba(255,80,80,0.2)', borderRadius: 4, color: 'rgba(255,100,60,0.75)', fontFamily: "'Share Tech Mono'", fontSize: 7, padding: '4px 6px', cursor: 'pointer' },
    inp:  { background: 'rgba(0,10,28,0.8)', border: '1px solid rgba(0,148,255,0.18)', borderRadius: 3, color: 'rgba(0,200,255,0.85)', fontFamily: "'Share Tech Mono'", fontSize: 7, padding: '3px 6px', outline: 'none', width: '100%', boxSizing: 'border-box' },
    card: { background: 'rgba(0,148,255,0.04)', border: '1px solid rgba(0,148,255,0.1)', borderRadius: 5, padding: '6px 8px', marginBottom: 5 },
    sep:  { height: 1, margin: '6px 0', background: 'rgba(0,148,255,0.07)' },
    badge: ok => ({ fontFamily: "'Share Tech Mono'", fontSize: 7, padding: '1px 5px', borderRadius: 3, background: ok ? 'rgba(0,200,83,0.1)' : 'rgba(255,80,80,0.08)', color: ok ? '#00c853' : 'rgba(255,80,80,0.55)', border: `1px solid ${ok ? 'rgba(0,200,83,0.25)' : 'rgba(255,80,80,0.18)'}` }),
  }

  return (
    <div style={{ padding: '0 12px 12px' }}>
      {/* NL command */}
      <div style={{ marginBottom: 8 }}>
        <div style={S.lbl}>COMMAND</div>
        <div style={{ display: 'flex', gap: 4 }}>
          <input style={{ ...S.inp, flex: 1 }} value={cmd} onChange={e => setCmd(e.target.value)} onKeyDown={e => e.key === 'Enter' && sendCmd()} placeholder="Set AC 22° · TV mute…" />
          <button style={{ ...S.btn, flex: '0 0 auto', padding: '3px 8px' }} onClick={sendCmd}>▶</button>
          <button style={{ ...S.btn, flex: '0 0 auto', padding: '3px 8px' }} onClick={refresh}>↻</button>
        </div>
        {msg.text && <div style={{ fontFamily: "'Share Tech Mono'", fontSize: 7, marginTop: 3, color: msg.ok ? 'rgba(0,200,83,0.8)' : 'rgba(255,80,80,0.7)' }}>{msg.text}</div>}
      </div>

      <div style={S.sep} />

      {/* Samsung AC */}
      <div style={{ marginBottom: 8 }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 5 }}>
          <div style={S.lbl}>SAMSUNG AC</div>
          <span style={S.badge(st.connected)}>{st.connected ? 'CONNECTED' : 'NO TOKEN'}</span>
        </div>
        {!st.connected
          ? <div style={{ fontFamily: "'Share Tech Mono'", fontSize: 7, color: 'rgba(0,148,255,0.25)', textAlign: 'center' }}>Set SmartThings token in Settings</div>
          : stDev.length === 0
            ? <div style={{ fontFamily: "'Share Tech Mono'", fontSize: 7, color: 'rgba(0,148,255,0.25)', textAlign: 'center' }}>No AC found</div>
            : stDev.map(d => (
              <div key={d.id} style={S.card}>
                <div style={{ fontFamily: "'Share Tech Mono'", fontSize: 9, color: 'rgba(0,148,255,0.85)', marginBottom: 4 }}>{d.label}</div>
                {acStatus[d.id] && <div style={{ fontFamily: "'Share Tech Mono'", fontSize: 6, color: 'rgba(0,200,255,0.6)', marginBottom: 4 }}>{acStatus[d.id]}</div>}
                <div style={{ display: 'flex', gap: 4, marginBottom: 4 }}>
                  <input type="number" style={{ ...S.inp, width: 50, flex: 'none' }} min="16" max="32" step="0.5" value={acTemp[d.id] ?? 24} onChange={e => setAcTemp(p => ({ ...p, [d.id]: e.target.value }))} placeholder="°C" />
                  <button style={S.btn} onClick={() => acSetTemp(d.id, 'cool')}>❄</button>
                  <button style={S.btn} onClick={() => acSetTemp(d.id, 'heat')}>🔥</button>
                </div>
                <div style={S.row}>
                  <button style={S.btn} onClick={() => acOn(d.id)}>ON</button>
                  <button style={S.rbtn} onClick={() => acOff(d.id)}>OFF</button>
                </div>
                {['auto', 'low', 'medium', 'high', 'turbo'].map(sp => (
                  <button key={sp} style={{ ...S.btn, fontSize: 6, marginBottom: 2 }} onClick={() => acSetFan(d.id, sp)}>{sp.toUpperCase()}</button>
                ))}
                <button style={{ ...S.btn, width: '100%', marginTop: 2 }} onClick={() => acGetStatus(d.id)}>↻ STATUS</button>
              </div>
            ))
        }
      </div>

      <div style={S.sep} />

      {/* Samsung TV */}
      <div style={{ marginBottom: 8 }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 4 }}>
          <div style={S.lbl}>SAMSUNG TV</div>
          <span style={S.badge(tvIp && tvInfo.connected)}>{tvIp ? (tvInfo.connected ? 'ONLINE' : 'OFFLINE') : 'NO IP'}</span>
        </div>
        <div style={S.row}>
          <button style={S.btn} onClick={() => tvCtrl('power')}>⏻</button>
          <button style={S.btn} onClick={() => tvCtrl('mute')}>🔇</button>
          <button style={S.btn} onClick={() => tvCtrl('volume_down')}>🔉</button>
          <button style={S.btn} onClick={() => tvCtrl('volume_up')}>🔊</button>
        </div>
        <div style={S.row}>
          <button style={S.btn} onClick={() => tvCtrl('channel_up')}>CH+</button>
          <button style={S.btn} onClick={() => tvCtrl('channel_down')}>CH−</button>
          <button style={S.btn} onClick={() => tvCtrl('key', 'KEY_HOME')}>HOME</button>
          <button style={S.btn} onClick={() => tvCtrl('key', 'KEY_RETURN')}>BACK</button>
        </div>
      </div>

      <div style={S.sep} />

      {/* Chromecast */}
      <div>
        <div style={S.lbl}>CHROMECAST</div>
        {(cast.devices || []).length === 0
          ? <div style={{ fontFamily: "'Share Tech Mono'", fontSize: 7, color: 'rgba(0,148,255,0.25)', textAlign: 'center', marginBottom: 4 }}>No Chromecast found</div>
          : (cast.devices || []).map(d => (
            <div key={d.name} style={{ ...S.card, marginBottom: 4 }}>
              <div style={{ fontFamily: "'Share Tech Mono'", fontSize: 8, color: 'rgba(0,148,255,0.8)' }}>{d.name}</div>
              <div style={{ fontFamily: "'Share Tech Mono'", fontSize: 6, color: 'rgba(0,148,255,0.4)', marginTop: 2 }}>VOL {d.volume}% · {d.is_idle ? 'IDLE' : 'ACTIVE'}</div>
            </div>
          ))
        }
      </div>
    </div>
  )
}

// ─── Hardware Widget ──────────────────────────────────────────────────────────
function HardwareWidget({ cameras, activeCam, mics, activeMic, onSwitchCam, onSwitchMic, onRefresh, camVisible, faceState }) {
  const selectStyle = { width: '100%', background: '#0a1628', color: '#00e5ff', border: '1px solid #0d2a3a', borderRadius: 3, padding: '4px 6px', fontSize: '10px', fontFamily: "'Share Tech Mono'", outline: 'none', cursor: 'pointer' }

  return (
    <div style={{ paddingBottom: 10 }}>
      {camVisible && (
        <>
          <CameraPanel faceState={faceState} />
          <Divider />
        </>
      )}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '6px 12px 2px' }}>
        <span style={{ color: '#1a4a5a', fontFamily: "'Share Tech Mono'", fontSize: '8px', letterSpacing: '0.15em' }}>DEVICES</span>
        <button onClick={onRefresh} title="Refresh" style={{ background: 'transparent', border: 'none', color: '#1a4a5a', fontFamily: "'Share Tech Mono'", fontSize: '10px', cursor: 'pointer', padding: 0 }}>⟳</button>
      </div>
      <div style={{ padding: '4px 12px 6px' }}>
        <p style={{ color: '#1a4a5a', fontFamily: "'Share Tech Mono'", fontSize: '8px', letterSpacing: '0.15em', marginBottom: 4 }}>CAMERA INPUT</p>
        <select style={selectStyle} value={activeCam ?? ''} onChange={e => onSwitchCam(e.target.value === '' ? null : Number(e.target.value))}>
          {cameras.map(d => <option key={d.index} value={d.index} style={{ background: '#0a1628' }}>{typeof d.name === 'string' ? d.name : `Camera ${d.index}`}</option>)}
        </select>
      </div>
      <Divider />
      <div style={{ padding: '4px 12px 6px' }}>
        <p style={{ color: '#1a4a5a', fontFamily: "'Share Tech Mono'", fontSize: '8px', letterSpacing: '0.15em', marginBottom: 4 }}>MICROPHONE INPUT</p>
        <select style={selectStyle} value={activeMic ?? ''} onChange={e => onSwitchMic(e.target.value === '' ? null : Number(e.target.value))}>
          {mics.map(d => <option key={d.index} value={d.index} style={{ background: '#0a1628' }}>{typeof d.name === 'string' ? d.name : (d.label ?? `Device ${d.index}`)}</option>)}
        </select>
      </div>
    </div>
  )
}

// ─── Calendar Widget ──────────────────────────────────────────────────────────
function CalendarWidget({ events = [], onUpdate }) {
  const [expanded, setExpanded] = useState(null)
  const typeColor = { class: '#00e5ff', meeting: '#1db954', social: '#ff9800', appointment: '#ff4081', other: '#3a6070' }

  function fmtDT(iso) {
    if (!iso) return '—'
    try {
      const d = new Date(iso)
      return `${d.toLocaleDateString('en-IN', { day: '2-digit', month: 'short' })}, ${d.toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit', hour12: true })}`
    } catch { return iso }
  }

  return (
    <div style={{ padding: '0 12px 12px' }}>
      {events.length === 0
        ? <p style={{ color: '#1a4a5a', fontFamily: "'JetBrains Mono'", fontSize: '9px' }}>No events in next 3 days</p>
        : events.map(ev => {
          const color = typeColor[ev.event_type] || typeColor.other
          const isOpen = expanded === ev.id
          return (
            <div key={ev.id} style={{ marginBottom: 6, border: `1px solid ${isOpen ? color + '55' : '#0d2a3a'}`, borderRadius: 4, overflow: 'hidden' }}>
              <div onClick={() => setExpanded(isOpen ? null : ev.id)} style={{ display: 'flex', alignItems: 'center', gap: 7, padding: '6px 8px', cursor: 'pointer', background: isOpen ? 'rgba(0,229,255,0.04)' : 'transparent' }}>
                <span style={{ width: 5, height: 5, borderRadius: '50%', flexShrink: 0, background: color, boxShadow: `0 0 4px ${color}88` }} />
                <div style={{ flex: 1, overflow: 'hidden' }}>
                  <p style={{ color: '#c8e8f0', fontFamily: "'JetBrains Mono'", fontSize: '9px', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{ev.title}</p>
                  <p style={{ color: '#3a6070', fontFamily: "'Share Tech Mono'", fontSize: '8px', marginTop: 1 }}>{fmtDT(ev.start)}</p>
                </div>
                <span style={{ color: '#1a4a5a', fontSize: '8px' }}>{isOpen ? '▲' : '▼'}</span>
              </div>
              {isOpen && ev.link && (
                <div style={{ padding: '6px 8px', borderTop: '1px solid #0d2a3a', background: '#060f1e' }}>
                  <p style={{ color: '#00e5ff', fontFamily: "'JetBrains Mono'", fontSize: '8px', wordBreak: 'break-all' }}>{ev.link}</p>
                </div>
              )}
            </div>
          )
        })
      }
    </div>
  )
}

// ─── WhatsApp Widget ──────────────────────────────────────────────────────────
function WhatsAppWidget({ status, qr }) {
  const [qrDataUrl, setQrDataUrl] = useState(null)
  useEffect(() => {
    setQrDataUrl(qr && qr.length > 0 ? `data:image/png;base64,${qr}` : null)
  }, [qr])
  return (
    <div style={{ padding: '0 12px 12px' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: qrDataUrl ? 10 : 0 }}>
        <span style={{ display: 'inline-block', width: 7, height: 7, borderRadius: '50%', background: status === 'online' ? '#1db954' : '#ff3d3d' }} />
        <span style={{ color: status === 'online' ? '#1db954' : '#ff3d3d', fontFamily: "'Share Tech Mono'", fontSize: '10px', letterSpacing: '0.2em' }}>{status}</span>
      </div>
      {qrDataUrl && status !== 'online' && (
        <>
          <p style={{ color: '#3a6070', fontFamily: "'Share Tech Mono'", fontSize: '8px', letterSpacing: '0.12em', marginBottom: 6 }}>SCAN TO CONNECT</p>
          <img src={qrDataUrl} alt="WhatsApp QR" style={{ width: '100%', borderRadius: 4, display: 'block' }} />
        </>
      )}
    </div>
  )
}

// ─── Phone Widget ─────────────────────────────────────────────────────────────
function PhoneWidget({ mmaStatus, androidDevices }) {
  const [qr, setQr] = useState(null)
  useEffect(() => {
    if (androidDevices.length > 0) { setQr(null); return }
    fetch(`${BASE}/connect/qr?mode=lan`).then(r => r.json()).then(d => { if (d.ok) setQr(d.qr_base64) }).catch(() => {})
  }, [androidDevices.length])
  return (
    <div style={{ padding: '0 12px 12px' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
        <span style={{ display: 'inline-block', width: 7, height: 7, borderRadius: '50%', background: mmaStatus === 'online' ? '#1db954' : '#ff3d3d' }} />
        <span style={{ color: mmaStatus === 'online' ? '#1db954' : '#ff3d3d', fontFamily: "'Share Tech Mono'", fontSize: '10px', letterSpacing: '0.2em' }}>{mmaStatus}</span>
      </div>
      {androidDevices.map((name, i) => (
        <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 7, marginBottom: 5 }}>
          <span style={{ display: 'inline-block', width: 6, height: 6, borderRadius: '50%', background: '#1db954', boxShadow: '0 0 5px #1db954', flexShrink: 0 }} />
          <span style={{ color: '#c8f0ff', fontFamily: "'JetBrains Mono'", fontSize: '9px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{name}</span>
          <span style={{ color: '#1db954', fontFamily: "'Share Tech Mono'", fontSize: '8px', marginLeft: 'auto', flexShrink: 0 }}>ONLINE</span>
        </div>
      ))}
      {androidDevices.length === 0 && qr && (
        <>
          <p style={{ color: '#3a6070', fontFamily: "'Share Tech Mono'", fontSize: '8px', letterSpacing: '0.12em', marginBottom: 6 }}>SCAN TO CONNECT PHONE</p>
          <img src={`data:image/png;base64,${qr}`} alt="Connect QR" style={{ width: '100%', borderRadius: 4, display: 'block' }} />
        </>
      )}
    </div>
  )
}

// ─── Notifications Widget ─────────────────────────────────────────────────────
function NotifsWidget({ notifications }) {
  return (
    <div style={{ padding: '0 12px 12px' }}>
      {(!notifications || notifications.length === 0)
        ? <p style={{ color: '#1a4a5a', fontFamily: "'JetBrains Mono'", fontSize: '9px' }}>No notifications</p>
        : notifications.map((n, i) => (
          <div key={i} style={{ marginBottom: 6, padding: '5px 8px', background: 'rgba(0,229,255,0.04)', border: '1px solid #0d2a3a', borderRadius: 3 }}>
            <p style={{ color: '#c8e8f0', fontFamily: "'JetBrains Mono'", fontSize: '9px', marginBottom: 2 }}>{typeof n === 'object' ? n.text : n}</p>
            {typeof n === 'object' && n.ts && <p style={{ color: '#1a4a5a', fontFamily: "'Share Tech Mono'", fontSize: '8px' }}>{n.ts}</p>}
          </div>
        ))
      }
    </div>
  )
}

// ─── OCR Widget ───────────────────────────────────────────────────────────────
function OcrWidget() {
  const [enabled, setEnabled] = useState(false)
  const [mode, setMode] = useState('idle')
  const [text, setText] = useState('')
  const [copied, setCopied] = useState(false)
  const pollRef = useRef(null)

  const modeColor = { idle: '#3a6070', scanning: '#00e5ff', done: '#1db954' }

  async function toggle() {
    const next = !enabled
    setEnabled(next); setMode(next ? 'scanning' : 'idle')
    try {
      await fetch(`${BASE}/ocr/toggle`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ enabled: next }) })
      if (next) {
        pollRef.current = setInterval(async () => {
          const r = await fetch(`${BASE}/ocr/status`).then(x => x.json()).catch(() => null)
          if (r?.mode === 'done') { clearInterval(pollRef.current); setEnabled(false); setMode('done'); setText(r.last_text || '') }
        }, 1500)
      } else { clearInterval(pollRef.current) }
    } catch {}
  }

  async function scanUpload(e) {
    const file = e.target.files[0]; if (!file) return
    setMode('scanning')
    const b64 = await new Promise(res => { const fr = new FileReader(); fr.onload = ev => res(ev.target.result.split(',')[1]); fr.readAsDataURL(file) })
    e.target.value = ''
    try {
      const r = await fetch(`${BASE}/ocr/scan-image`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ image: b64, mime: file.type }) }).then(x => x.json())
      setText(r.text || ''); setMode('done')
    } catch { setMode('idle') }
  }

  function copy() {
    if (!text) return
    import('../utils/clipboard.js').then(({ copyToClipboard }) => {
      copyToClipboard(text).then(ok => { if (ok) { setCopied(true); setTimeout(() => setCopied(false), 1500) } })
    })
  }

  async function save() {
    if (!text) return
    try {
      await fetch(`${BASE}/ocr/save`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ text }) })
    } catch {}
  }

  useEffect(() => () => clearInterval(pollRef.current), [])

  return (
    <div style={{ padding: '0 12px 12px' }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 8 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <div style={{ width: 6, height: 6, borderRadius: '50%', background: modeColor[mode], boxShadow: mode === 'scanning' ? '0 0 6px #00e5ff' : 'none', transition: 'all 0.3s' }} />
          <span style={{ fontFamily: "'Share Tech Mono'", fontSize: 9, letterSpacing: '0.2em', color: modeColor[mode] }}>{mode.toUpperCase()}</span>
        </div>
        <div onClick={toggle} style={{ width: 32, height: 16, borderRadius: 8, cursor: 'pointer', position: 'relative', background: enabled ? 'rgba(0,229,255,0.2)' : 'rgba(13,42,58,0.8)', border: `1px solid ${enabled ? '#00e5ff55' : '#0d2a3a'}`, transition: 'all 0.2s' }}>
          <div style={{ position: 'absolute', top: 2, left: enabled ? 14 : 2, width: 10, height: 10, borderRadius: '50%', background: enabled ? '#00e5ff' : '#1a4a5a', transition: 'left 0.2s' }} />
        </div>
      </div>
      <div style={{ display: 'flex', gap: 4, marginBottom: 8 }}>
        <label style={{ flex: 1, textAlign: 'center', padding: '4px 0', background: 'rgba(0,148,255,0.07)', border: '1px solid #0d2a3a', borderRadius: 3, color: '#3a6070', fontFamily: "'Share Tech Mono'", fontSize: 8, letterSpacing: '0.15em', cursor: 'pointer' }}>
          ⊡ UPLOAD<input type="file" accept="image/*" style={{ display: 'none' }} onChange={scanUpload} />
        </label>
        <button onClick={toggle} style={{ flex: 1, padding: '4px 0', background: enabled ? 'rgba(0,229,255,0.1)' : 'rgba(0,148,255,0.07)', border: `1px solid ${enabled ? '#00e5ff44' : '#0d2a3a'}`, borderRadius: 3, color: enabled ? '#00e5ff' : '#3a6070', fontFamily: "'Share Tech Mono'", fontSize: 8, cursor: 'pointer' }}>◎ CAM</button>
      </div>
      <textarea readOnly value={text} placeholder="Scan or upload…" style={{ width: '100%', height: 70, background: '#050d1a', border: '1px solid #0d2a3a', borderRadius: 3, color: '#60b8d0', fontFamily: "'JetBrains Mono'", fontSize: 8, lineHeight: 1.6, padding: '4px 6px', resize: 'none', outline: 'none', boxSizing: 'border-box', marginBottom: 6 }} />
      <div style={{ display: 'flex', gap: 4 }}>
        {[{ label: copied ? 'COPIED ✓' : 'COPY', fn: copy, color: copied ? '#1db954' : '#3a6070' }, { label: 'SAVE', fn: save, color: '#3a6070' }, { label: 'CLEAR', fn: () => { setText(''); setMode('idle') }, color: '#ff3d3d55' }].map(({ label, fn, color }) => (
          <button key={label} onClick={fn} style={{ flex: 1, padding: '3px 0', background: 'transparent', border: `1px solid ${color}`, borderRadius: 3, color, fontFamily: "'Share Tech Mono'", fontSize: 7, cursor: 'pointer' }}>{label}</button>
        ))}
      </div>
    </div>
  )
}

// ─── Settings Panel (drag-to-reorder + toggle) ────────────────────────────────
function WidgetSettings({ order, enabled, onSave, onClose }) {
  const [localOrder, setLocalOrder] = useState([...order])
  const [localEnabled, setLocalEnabled] = useState({ ...enabled })
  const dragIdx = useRef(null)
  const dragOverIdx = useRef(null)

  function onDragStart(e, i) {
    dragIdx.current = i
    e.dataTransfer.effectAllowed = 'move'
    e.currentTarget.style.opacity = '0.5'
  }
  function onDragEnd(e) { e.currentTarget.style.opacity = '1' }
  function onDragOver(e, i) { e.preventDefault(); dragOverIdx.current = i }
  function onDrop(e) {
    e.preventDefault()
    const from = dragIdx.current, to = dragOverIdx.current
    if (from === null || to === null || from === to) return
    const next = [...localOrder]
    const [moved] = next.splice(from, 1)
    next.splice(to, 0, moved)
    setLocalOrder(next)
    dragIdx.current = null; dragOverIdx.current = null
  }

  const save = () => { onSave(localOrder, localEnabled); onClose() }

  const idToLabel = Object.fromEntries(ALL_WIDGETS.map(w => [w.id, w.label]))

  return (
    <div style={{ flex: 1, overflowY: 'auto', padding: '10px 0' }}>
      <div style={{ padding: '0 12px 10px', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <span style={{ color: '#00e5ff', fontFamily: "'Share Tech Mono'", fontSize: '10px', letterSpacing: '0.2em' }}>PANEL WIDGETS</span>
        <button onClick={save} style={{ background: 'rgba(0,229,255,0.1)', border: '1px solid rgba(0,229,255,0.35)', borderRadius: 3, color: '#00e5ff', fontFamily: "'Share Tech Mono'", fontSize: 8, padding: '3px 10px', cursor: 'pointer' }}>SAVE</button>
      </div>
      <div style={{ padding: '0 8px', fontSize: 8, color: '#1a4a5a', fontFamily: "'Share Tech Mono'", letterSpacing: '0.12em', marginBottom: 8, paddingLeft: 12 }}>
        DRAG TO REORDER · TOGGLE TO SHOW/HIDE
      </div>
      {localOrder.map((id, i) => (
        <div
          key={id}
          draggable
          onDragStart={e => onDragStart(e, i)}
          onDragEnd={onDragEnd}
          onDragOver={e => onDragOver(e, i)}
          onDrop={onDrop}
          style={{
            display: 'flex', alignItems: 'center', gap: 8,
            padding: '7px 12px',
            background: 'transparent',
            borderBottom: '1px solid #0d2a3a',
            cursor: 'grab', userSelect: 'none',
            transition: 'background 0.1s',
          }}
          onMouseEnter={e => { e.currentTarget.style.background = 'rgba(0,229,255,0.04)' }}
          onMouseLeave={e => { e.currentTarget.style.background = 'transparent' }}
        >
          {/* Drag handle */}
          <span style={{ color: '#1a4a5a', fontSize: 12, flexShrink: 0, cursor: 'grab' }}>⠿</span>
          {/* Label */}
          <span style={{ flex: 1, color: localEnabled[id] ? '#c8e8f0' : '#1a4a5a', fontFamily: "'Share Tech Mono'", fontSize: 9, letterSpacing: '0.12em', transition: 'color 0.2s' }}>
            {idToLabel[id] || id}
          </span>
          {/* Toggle */}
          <div
            onClick={() => setLocalEnabled(p => ({ ...p, [id]: !p[id] }))}
            style={{
              width: 28, height: 14, borderRadius: 7, cursor: 'pointer', position: 'relative', flexShrink: 0,
              background: localEnabled[id] ? 'rgba(0,229,255,0.2)' : 'rgba(13,42,58,0.8)',
              border: `1px solid ${localEnabled[id] ? '#00e5ff55' : '#0d2a3a'}`,
              transition: 'all 0.2s',
            }}
          >
            <div style={{
              position: 'absolute', top: 2, left: localEnabled[id] ? 12 : 2,
              width: 8, height: 8, borderRadius: '50%',
              background: localEnabled[id] ? '#00e5ff' : '#1a4a5a',
              transition: 'left 0.2s',
            }} />
          </div>
        </div>
      ))}
      <div style={{ padding: '12px 12px 4px', display: 'flex', justifyContent: 'center' }}>
        <button onClick={onClose} style={{ background: 'transparent', border: '1px solid #0d2a3a', borderRadius: 3, color: '#3a6070', fontFamily: "'Share Tech Mono'", fontSize: 8, padding: '4px 14px', cursor: 'pointer' }}>CANCEL</button>
      </div>
    </div>
  )
}

// ─── Main LeftPanel ───────────────────────────────────────────────────────────
export default function LeftPanel({
  cpuUsage, ramUsage, gpuUsage, procCpu, procMem,
  faceState, camVisible = false,
  spotifyTrack,
  calendarEvents = [], onCalendarUpdate,
  waStatus, whatsappQr,
  mmaStatus, androidDevices = [],
  notifications = [],
}) {
  const [panelCollapsed, setPanelCollapsed] = useState(false)
  const [settingsOpen,   setSettingsOpen]   = useState(false)

  const [widgetOrder,   setWidgetOrder]   = useState(loadOrder)
  const [widgetEnabled, setWidgetEnabled] = useState(loadEnabled)
  const [widgetCollapsed, setWidgetCollapsed] = useState(loadCollapsed)

  // Devices state (for hardware widget)
  const [cameras, setCameras] = useState([{ index: 0, name: 'Default Camera' }])
  const [activeCam, setActiveCam] = useState(0)
  const [mics, setMics] = useState([{ index: null, name: 'Default Microphone' }])
  const [activeMic, setActiveMic] = useState(null)

  const fetchDevices = () => {
    fetch(`${BASE}/vision/cameras`).then(r => r.json()).then(d => {
      if (d.ok && (d.cameras || []).length > 0) {
        setCameras((d.cameras || []).map(c => typeof c === 'object' ? c : { index: c, name: `Camera ${c}` }))
        setActiveCam(d.active ?? 0)
      }
    }).catch(() => {})
    fetch(`${BASE}/mic/devices`).then(r => r.json()).then(d => {
      if (d.ok && (d.devices || []).length > 0) { setMics(d.devices || []); setActiveMic(d.active ?? null) }
    }).catch(() => {})
  }
  useEffect(() => { fetchDevices() }, [])

  const switchCamera = idx => {
    setActiveCam(idx)
    fetch(`${BASE}/vision/camera`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ index: idx }) }).catch(() => {})
  }
  const switchMic = idx => {
    setActiveMic(idx)
    fetch(`${BASE}/mic/select`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ index: idx }) }).catch(() => {})
  }

  const toggleWidget = (id) => {
    const next = { ...widgetCollapsed, [id]: !widgetCollapsed[id] }
    setWidgetCollapsed(next)
    localStorage.setItem(LS_COLLAPSED, JSON.stringify(next))
  }

  const saveSettings = (order, enabled) => {
    setWidgetOrder(order); setWidgetEnabled(enabled)
    localStorage.setItem(LS_ORDER,   JSON.stringify(order))
    localStorage.setItem(LS_ENABLED, JSON.stringify(enabled))
  }

  const renderWidget = (id) => {
    if (!widgetEnabled[id]) return null
    const collapsed = !!widgetCollapsed[id]
    const label = (ALL_WIDGETS.find(w => w.id === id) || {}).label || id

    const content = (() => {
      switch (id) {
        case 'vitals':    return <VitalsWidget cpuUsage={cpuUsage} ramUsage={ramUsage} gpuUsage={gpuUsage} procCpu={procCpu} procMem={procMem} />
        case 'spotify':   return <SpotifyWidget track={spotifyTrack} />
        case 'fitness':   return <FitnessWidget />
        case 'location':  return <LocationWidget />
        case 'smarthome': return <SmartHomeWidget />
        case 'hardware':  return <HardwareWidget cameras={cameras} activeCam={activeCam} mics={mics} activeMic={activeMic} onSwitchCam={switchCamera} onSwitchMic={switchMic} onRefresh={fetchDevices} camVisible={camVisible} faceState={faceState} />
        case 'calendar':  return <CalendarWidget events={calendarEvents} onUpdate={onCalendarUpdate} />
        case 'whatsapp':  return <WhatsAppWidget status={waStatus} qr={whatsappQr} />
        case 'phone':     return <PhoneWidget mmaStatus={mmaStatus} androidDevices={androidDevices} />
        case 'notifs':    return <NotifsWidget notifications={notifications} />
        case 'ocr':       return <OcrWidget />
        default: return null
      }
    })()

    if (!content) return null

    return (
      <React.Fragment key={id}>
        <Widget id={id} label={label} collapsed={collapsed} onToggle={toggleWidget}>
          {content}
        </Widget>
        <Divider />
      </React.Fragment>
    )
  }

  return (
    <div style={{
      width: panelCollapsed ? 36 : 240,
      transition: 'width 0.28s cubic-bezier(0.22,1,0.36,1)',
      height: '100%', overflow: 'hidden',
      background: '#0a1628', borderRight: '1px solid #0d2a3a',
      display: 'flex', flexDirection: 'column', position: 'relative',
    }}>
      {/* Panel header */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '10px 8px', borderBottom: '1px solid #0d2a3a', flexShrink: 0, minWidth: 36 }}>
        <button
          onClick={() => setPanelCollapsed(!panelCollapsed)}
          title={panelCollapsed ? 'Expand panel' : 'Collapse panel'}
          style={{ background: 'transparent', border: 'none', color: 'rgba(0,229,255,0.5)', fontFamily: "'Share Tech Mono'", fontSize: '14px', cursor: 'pointer', lineHeight: 1, padding: '2px 4px', flexShrink: 0, transition: 'color 0.15s' }}
          onMouseEnter={e => { e.currentTarget.style.color = '#00e5ff' }}
          onMouseLeave={e => { e.currentTarget.style.color = 'rgba(0,229,255,0.5)' }}
        >
          {panelCollapsed ? '›' : '‹'}
        </button>
        {!panelCollapsed && (
          <>
            <span style={{ color: '#00e5ff', fontFamily: "'Share Tech Mono'", fontSize: '10px', letterSpacing: '0.18em', whiteSpace: 'nowrap', flex: 1 }}>
              MODULES
            </span>
            <button
              onClick={() => setSettingsOpen(s => !s)}
              title="Widget settings"
              style={{ background: 'transparent', border: 'none', color: settingsOpen ? '#00e5ff' : 'rgba(0,229,255,0.35)', fontSize: '12px', cursor: 'pointer', padding: '2px 4px', flexShrink: 0, transition: 'color 0.15s' }}
              onMouseEnter={e => { e.currentTarget.style.color = '#00e5ff' }}
              onMouseLeave={e => { if (!settingsOpen) e.currentTarget.style.color = 'rgba(0,229,255,0.35)' }}
            >
              ⚙
            </button>
          </>
        )}
      </div>

      {/* Panel body */}
      <div style={{ flex: 1, overflowY: 'auto', overflowX: 'hidden', opacity: panelCollapsed ? 0 : 1, pointerEvents: panelCollapsed ? 'none' : 'auto', transition: 'opacity 0.18s ease', display: 'flex', flexDirection: 'column' }}>
        {settingsOpen
          ? <WidgetSettings order={widgetOrder} enabled={widgetEnabled} onSave={saveSettings} onClose={() => setSettingsOpen(false)} />
          : widgetOrder.map(id => renderWidget(id))
        }
      </div>
    </div>
  )
}
