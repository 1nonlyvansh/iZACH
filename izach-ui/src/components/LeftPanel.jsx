import React, { useState, useEffect } from 'react'
import CameraPanel from './CameraPanel.jsx'

function vitalColor(v) {
  if (v > 85) return '#ff3d3d'
  if (v > 65) return '#ffb300'
  return '#00e5ff'
}

function Sparkline({ data, color }) {
  const W = 52, H = 16
  const max = Math.max(...data, 1)
  const pts = data.map((v, i) => `${(i / (data.length - 1)) * W},${H - (v / max) * H}`).join(' ')
  const last = data[data.length - 1]
  const lx = W, ly = H - (last / max) * H
  return (
    <svg width={W} height={H} style={{ overflow: 'visible', flexShrink: 0 }}>
      <polyline
        points={pts} fill="none" stroke={color}
        strokeWidth="1.1" strokeOpacity="0.45"
        strokeLinejoin="round" className="sparkline-path"
      />
      <circle cx={lx} cy={ly} r="1.8" fill={color} fillOpacity="0.85" />
    </svg>
  )
}

const BASE = 'http://localhost:5050'

function VitalBar({ label, value, history }) {
  const safeValue = Math.min(100, Math.max(0, value || 0))
  const color     = vitalColor(safeValue)
  const critical  = safeValue > 85

  return (
    <div style={{ marginBottom: 10, paddingLeft: 12, paddingRight: 12 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 3 }}>
        <span style={{ color: '#3a6070', fontFamily: "'JetBrains Mono'", fontSize: '10px' }}>{label}</span>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          {critical && (
            <span style={{
              width: 5, height: 5, borderRadius: '50%', background: '#ff3d3d',
              boxShadow: '0 0 5px #ff3d3d', display: 'inline-block',
              animation: 'statusPulseRed 1.2s infinite', flexShrink: 0,
            }} />
          )}
          <Sparkline data={history} color={color} />
          <span style={{ color, fontFamily: "'Share Tech Mono'", fontSize: '10px', minWidth: 30, textAlign: 'right' }}>
            {safeValue}%
          </span>
        </div>
      </div>
      <div style={{ height: 3, background: '#0d2a3a', borderRadius: 2, overflow: 'hidden' }}>
        <div style={{
          height: '100%', width: `${safeValue}%`,
          background: `linear-gradient(90deg, ${color}55, ${color})`,
          boxShadow: `0 0 6px ${color}88`, borderRadius: 2,
          transition: 'width 0.7s ease, background 0.6s ease, box-shadow 0.6s ease',
        }} />
      </div>
    </div>
  )
}

function ProcessStats({ procCpu, procMem }) {
  return (
    <div style={{ padding: '4px 12px 10px' }}>
      <p style={{ color: '#1a4a5a', fontFamily: "'Share Tech Mono'", fontSize: '8px', letterSpacing: '0.15em', marginBottom: 6 }}>
        iZ.ACH. PROCESS
      </p>
      {[['CPU', `${procCpu ?? 0}%`], ['MEM', `${procMem ?? 0}%`]].map(([k, v]) => (
        <div key={k} style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 3 }}>
          <span style={{ color: '#1a4a5a', fontFamily: "'JetBrains Mono'", fontSize: '10px' }}>{k}</span>
          <span style={{ color: '#00e5ff', fontFamily: "'Share Tech Mono'", fontSize: '10px' }}>{v}</span>
        </div>
      ))}
    </div>
  )
}

const selectStyle = {
  width: '100%', background: '#0a1628', color: '#00e5ff',
  border: '1px solid #0d2a3a', borderRadius: 3, padding: '4px 6px',
  fontSize: '10px', fontFamily: "'Share Tech Mono'", outline: 'none', cursor: 'pointer',
}

function DeviceSelect({ label, devices, active, onSelect }) {
  return (
    <div style={{ padding: '6px 12px 8px' }}>
      <p style={{ color: '#1a4a5a', fontFamily: "'Share Tech Mono'", fontSize: '8px', letterSpacing: '0.15em', marginBottom: 4 }}>
        {label}
      </p>
      <select
        style={selectStyle}
        value={active ?? ''}
        onChange={e => onSelect(e.target.value === '' ? null : Number(e.target.value))}
      >
        {devices.map(d => (
          <option key={d.index} value={d.index} style={{ background: '#0a1628' }}>
            {typeof d.name === 'string' ? d.name : (d.label ?? `Device ${d.index}`)}
          </option>
        ))}
      </select>
    </div>
  )
}

export default function LeftPanel({ cpuUsage, ramUsage, gpuUsage, procCpu, procMem, faceState, camVisible = false }) {
  const [collapsed, setCollapsed] = useState(false)

  const [cameras, setCameras]           = useState([{ index: 0, name: 'Default Camera' }])
  const [activeCam, setActiveCam]       = useState(0)
  const [mics, setMics]                 = useState([{ index: null, name: 'Default Microphone' }])
  const [activeMic, setActiveMic]       = useState(null)
  const [devicesLoaded, setDevicesLoaded] = useState(false)

  const HIST_LEN = 22
  const [cpuHist, setCpuHist] = useState(Array(HIST_LEN).fill(0))
  const [ramHist, setRamHist] = useState(Array(HIST_LEN).fill(0))
  const [gpuHist, setGpuHist] = useState(Array(HIST_LEN).fill(0))

  useEffect(() => { setCpuHist(h => [...h.slice(1), cpuUsage || 0]) }, [cpuUsage])
  useEffect(() => { setRamHist(h => [...h.slice(1), ramUsage || 0]) }, [ramUsage])
  useEffect(() => { setGpuHist(h => [...h.slice(1), gpuUsage || 0]) }, [gpuUsage])

  const fetchDevices = () => {
    fetch(`${BASE}/vision/cameras`).then(r => r.json()).then(d => {
      if (d.ok && (d.cameras || []).length > 0) {
        // API returns [{index, name}, ...] — use directly; handle legacy int[] too
        setCameras((d.cameras || []).map(c =>
          typeof c === 'object' ? c : { index: c, name: `Camera ${c}` }
        ))
        setActiveCam(d.active ?? 0)
      }
    }).catch(() => {})
    fetch(`${BASE}/mic/devices`).then(r => r.json()).then(d => {
      if (d.ok && (d.devices || []).length > 0) { setMics(d.devices || []); setActiveMic(d.active ?? null) }
      setDevicesLoaded(true)
    }).catch(() => { setDevicesLoaded(true) })
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

  return (
    <div style={{
      width: collapsed ? 36 : 240,
      transition: 'width 0.28s cubic-bezier(0.22,1,0.36,1)',
      height: '100%', overflow: 'hidden',
      background: '#0a1628', borderRight: '1px solid #0d2a3a',
      display: 'flex', flexDirection: 'column', position: 'relative',
    }}>
      {/* Panel header with collapse toggle */}
      <div style={{
        display: 'flex', alignItems: 'center', gap: 6,
        padding: '10px 8px', borderBottom: '1px solid #0d2a3a',
        flexShrink: 0, minWidth: 36,
      }}>
        <button
          onClick={() => setCollapsed(!collapsed)}
          title={collapsed ? 'Expand panel' : 'Collapse panel'}
          style={{
            background: 'transparent', border: 'none',
            color: 'rgba(0,229,255,0.5)', fontFamily: "'Share Tech Mono'",
            fontSize: '14px', cursor: 'pointer', lineHeight: 1,
            padding: '2px 4px', flexShrink: 0,
            transition: 'color 0.15s',
          }}
          onMouseEnter={e => { e.currentTarget.style.color = '#00e5ff' }}
          onMouseLeave={e => { e.currentTarget.style.color = 'rgba(0,229,255,0.5)' }}
        >
          {collapsed ? '›' : '‹'}
        </button>
        {!collapsed && (
          <span style={{
            color: '#00e5ff', fontFamily: "'Share Tech Mono'",
            fontSize: '10px', letterSpacing: '0.18em', whiteSpace: 'nowrap',
            opacity: collapsed ? 0 : 1, transition: 'opacity 0.2s',
          }}>
            SYS.PANEL
          </span>
        )}
      </div>

      {/* Panel content — fades with collapse, always mounted for smooth transition */}
      <div style={{
        flex: 1, overflowY: 'auto', overflowX: 'hidden',
        opacity: collapsed ? 0 : 1,
        pointerEvents: collapsed ? 'none' : 'auto',
        transition: 'opacity 0.18s ease',
      }}>
        {/* System Vitals */}
          <div style={{ flexShrink: 0 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 2, padding: '8px 12px 4px' }}>
              <span style={{ color: '#00e5ff', fontSize: 9 }}>*</span>
              <span style={{ color: '#00e5ff', fontFamily: "'Share Tech Mono'", fontSize: '10px', letterSpacing: '0.2em' }}>
                SYSTEM VITALS
              </span>
              <div style={{ flex: 1, height: 1, background: '#0d2a3a', marginLeft: 6 }} />
            </div>
            <VitalBar label="CPU" value={cpuUsage} history={cpuHist} />
            <VitalBar label="RAM" value={ramUsage} history={ramHist} />
            <VitalBar label="GPU" value={gpuUsage} history={gpuHist} />
            <ProcessStats procCpu={procCpu} procMem={procMem} />
          </div>

          {/* Camera / Vision — shown only when optics toggled on */}
          {camVisible && (
            <>
              <div style={{ height: 1, margin: '0 12px', background: '#0d2a3a' }} />
              <CameraPanel faceState={faceState} />
              <div style={{ height: 1, margin: '0 12px', background: '#0d2a3a' }} />
            </>
          )}

          {/* Device selects */}
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '6px 12px 2px' }}>
            <span style={{ color: '#1a4a5a', fontFamily: "'Share Tech Mono'", fontSize: '8px', letterSpacing: '0.15em' }}>
              HARDWARE
            </span>
            <button
              onClick={fetchDevices}
              title="Refresh devices"
              style={{
                background: 'transparent', border: 'none', color: '#1a4a5a',
                fontFamily: "'Share Tech Mono'", fontSize: '9px', cursor: 'pointer',
                padding: '0 2px', lineHeight: 1,
              }}
            >
              ⟳
            </button>
          </div>

          <DeviceSelect label="CAMERA INPUT"     devices={cameras} active={activeCam} onSelect={switchCamera} />
          <div style={{ height: 1, margin: '0 12px', background: '#0d2a3a' }} />
          <DeviceSelect label="MICROPHONE INPUT" devices={mics}    active={activeMic} onSelect={switchMic} />
      </div>

    </div>
  )
}
