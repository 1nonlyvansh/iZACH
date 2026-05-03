import React, { useState } from 'react'

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

// ── Settings Section ──────────────────────────────────────────
function GeneralSection({ settings, onSave }) {
  const [wakeWord, setWakeWord] = useState(settings.wake_word_enabled ?? false)
  const [voice,    setVoice]    = useState(settings.voice ?? 'en-US-ChristopherNeural')
  const [dirty,    setDirty]    = useState(false)

  function handleToggleWW(v) { setWakeWord(v); setDirty(true) }
  function handleVoice(v)    { setVoice(v);    setDirty(true) }

  function handleSave() {
    onSave({ wake_word_enabled: wakeWord, voice })
    setDirty(false)
  }

  const VOICES = [
    'en-US-ChristopherNeural',
    'en-US-GuyNeural',
    'en-IN-PrabhatNeural',
    'en-GB-RyanNeural',
    'en-AU-WilliamNeural',
  ]

  return (
    <div>
      <SectionHeader label="GENERAL SETTINGS" />
      <Toggle label="Wake Word Detection ('iZACH')" checked={wakeWord} onChange={handleToggleWW} />

      <div style={{ padding: '6px 20px' }}>
        <p style={{ color: '#3a6070', fontFamily: "'Share Tech Mono'", fontSize: '9px', letterSpacing: '0.1em', marginBottom: 6 }}>
          TTS VOICE
        </p>
        <select
          value={voice}
          onChange={e => handleVoice(e.target.value)}
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
            cursor: 'pointer',
          }}
        >
          {VOICES.map(v => <option key={v} value={v}>{v}</option>)}
        </select>
      </div>

      {dirty && (
        <div style={{ padding: '8px 20px' }}>
          <Btn label="SAVE SETTINGS" onClick={handleSave} />
        </div>
      )}
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
  const [tab, setTab] = useState('memory')  // 'memory' | 'general'

  const tabs = [
    { id: 'memory',  label: 'MEMORY'   },
    { id: 'general', label: 'SETTINGS' },
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
              transition: 'all 0.15s',
            }}
          >
            {t.label}
          </button>
        ))}
      </div>

      {/* Content */}
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
    </div>
  )
}