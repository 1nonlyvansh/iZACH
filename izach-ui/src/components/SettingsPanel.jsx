import React, { useState, useEffect } from 'react'

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

// ── Settings Section ──────────────────────────────────────────
function GeneralSection({ settings, onSave }) {
  const [form, setForm] = useState({
    wake_word_enabled:       settings.wake_word_enabled       ?? false,
    voice:                   settings.voice                   ?? 'en-US-ChristopherNeural',
    tts_speed:               settings.tts_speed               ?? 0,
    response_style:          settings.response_style          ?? 'casual',
    response_verbosity:      settings.response_verbosity      ?? 'balanced',
    safe_mode_enabled:       settings.safe_mode_enabled       ?? true,
    notif_performance:       settings.notif_performance       ?? true,
    notif_whatsapp:          settings.notif_whatsapp          ?? true,
    notif_downloads:         settings.notif_downloads         ?? true,
    command_history_enabled: settings.command_history_enabled ?? true,
    log_retention_days:      settings.log_retention_days      ?? 30,
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
            <option key={d.index} value={d.index}>{d.name}</option>
          ))}
        </select>
        <p style={{ color: '#1a4a5a', fontFamily: "'JetBrains Mono'", fontSize: '9px', marginTop: 4 }}>
          Applied immediately — no restart needed
        </p>
      </div>

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
      'play something chill on spotify',
      'play <song name>',
      'pause / resume music',
      'next song / previous song',
      'set volume to 60',
      'what song is this',
      'play my liked songs',
      'shuffle playlist',
    ],
  },
  {
    id: 'whatsapp',
    label: 'WHATSAPP',
    icon: '✉',
    commands: [
      'read my messages',
      'what did <name> say',
      'reply to <name> — <message>',
      'send <name> a message — <text>',
      'any new messages',
      'read last message from <name>',
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
      'how much ram is being used',
      'what\'s my cpu temperature',
      'take a screenshot',
      'lock the screen',
      'shutdown / restart',
      'empty recycle bin',
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
    id: 'face',
    label: 'FACE AUTH',
    icon: '⬡',
    commands: [
      'enroll my face',
      'verify my identity',
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

// ── Main SettingsPanel export ─────────────────────────────────
export default function SettingsPanel({
  memoryEntries,
  settings,
  onAddMemory,
  onDeleteMemory,
  onSaveSettings,
}) {
  const [tab, setTab] = useState('memory')  // 'memory' | 'general' | 'commands'

  const tabs = [
    { id: 'memory',   label: 'MEMORY'   },
    { id: 'general',  label: 'SETTINGS' },
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
      {tab === 'commands' && (
        <CommandsSection />
      )}
    </div>
  )
}