import React from 'react'
import CameraPanel from './CameraPanel.jsx'

function SectionHeader({ label }) {
  return (
    <div className="flex items-center gap-2 px-3 py-2">
      <span style={{ color: '#00e5ff' }}>*</span>
      <span
        className="text-xs tracking-[0.2em]"
        style={{ color: '#00e5ff', fontFamily: "'Share Tech Mono'" }}
      >
        {label}
      </span>
      <div className="flex-1 h-px" style={{ background: '#0d2a3a' }} />
    </div>
  )
}

function VitalBar({ label, value, color }) {
  const safeValue = Math.min(100, Math.max(0, value || 0))

  return (
    <div style={{ marginBottom: 8, paddingLeft: 12, paddingRight: 12 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 3 }}>
        <span style={{ color: '#3a6070', fontFamily: "'JetBrains Mono'", fontSize: '10px' }}>
          {label}
        </span>
        <span style={{ color: color, fontFamily: "'Share Tech Mono'", fontSize: '10px' }}>
          {safeValue}%
        </span>
      </div>
      <div
        style={{
          height: 3,
          background: '#0d2a3a',
          borderRadius: 2,
          overflow: 'hidden',
        }}
      >
        <div
          style={{
            height: '100%',
            width: `${safeValue}%`,
            background: `linear-gradient(90deg, ${color}55, ${color})`,
            boxShadow: `0 0 6px ${color}88`,
            borderRadius: 2,
            transition: 'width 0.7s ease',
          }}
        />
      </div>
    </div>
  )
}

function ProcessStats({ procCpu, procMem }) {
  return (
    <div style={{ padding: '4px 12px 10px' }}>
      <p style={{
        color: '#1a4a5a',
        fontFamily: "'Share Tech Mono'",
        fontSize: '8px',
        letterSpacing: '0.15em',
        marginBottom: 6,
      }}>
        iZ.ACH. PROCESS
      </p>
      {[['CPU', `${procCpu ?? 0}%`], ['MEM', `${procMem ?? 0}%`]].map(([k, v]) => (
        <div
          key={k}
          style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 3 }}
        >
          <span style={{ color: '#1a4a5a', fontFamily: "'JetBrains Mono'", fontSize: '10px' }}>{k}</span>
          <span style={{ color: '#00e5ff', fontFamily: "'Share Tech Mono'", fontSize: '10px' }}>{v}</span>
        </div>
      ))}
    </div>
  )
}

export default function LeftPanel({ cpuUsage, ramUsage, gpuUsage, procCpu, procMem }) {
  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        height: '100%',
        overflow: 'hidden',
        background: '#0a1628',
        borderRight: '1px solid #0d2a3a',
      }}
    >
      {/* System Vitals block */}
      <div style={{ flexShrink: 0 }}>
        <SectionHeader label="SYSTEM VITALS" />
        <VitalBar label="CPU" value={cpuUsage} color="#00e5ff" />
        <VitalBar label="RAM" value={ramUsage} color="#ffb300" />
        <VitalBar label="GPU" value={gpuUsage} color="#1db954" />
        <ProcessStats procCpu={procCpu} procMem={procMem} />
      </div>

      {/* Divider */}
      <div style={{ height: 1, margin: '0 12px', background: '#0d2a3a', flexShrink: 0 }} />

      {/* Camera / Vision block — scrolls if needed */}
      <div style={{ flex: 1, overflowY: 'auto', overflowX: 'hidden' }}>
        <CameraPanel />
      </div>
    </div>
  )
}