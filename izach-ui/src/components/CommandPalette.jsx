import React, { useState, useEffect, useRef } from 'react'

const ALL_COMMANDS = [
  { label: 'Play / Pause Music',   icon: '♫', cmd: 'play music' },
  { label: 'Next Track',           icon: '⏭', cmd: 'next track' },
  { label: 'Previous Track',       icon: '⏮', cmd: 'previous track' },
  { label: 'Volume Up',            icon: '▲', cmd: 'volume up' },
  { label: 'Volume Down',          icon: '▼', cmd: 'volume down' },
  { label: 'Open YouTube',         icon: '▶', cmd: 'open YouTube' },
  { label: 'Open Chrome',          icon: '◉', cmd: 'open Chrome' },
  { label: 'Open Spotify',         icon: '◎', cmd: 'open Spotify' },
  { label: 'Open WhatsApp',        icon: '◈', cmd: 'open WhatsApp' },
  { label: 'Open File Explorer',   icon: '□', cmd: 'open file explorer' },
  { label: 'Take Screenshot',      icon: '⊡', cmd: 'take a screenshot' },
  { label: 'What time is it?',     icon: '◷', cmd: 'what time is it' },
  { label: 'Check weather',        icon: '◌', cmd: 'what is the weather' },
  { label: 'Search Google',        icon: '⊙', cmd: 'search Google for' },
  { label: 'Set a reminder',       icon: '◎', cmd: 'set a reminder' },
  { label: 'Lock the screen',      icon: '⊠', cmd: 'lock the screen' },
  { label: 'Shutdown computer',    icon: '⊗', cmd: 'shutdown the computer' },
  { label: 'What can you do?',     icon: '?', cmd: 'what can you do' },
]

export default function CommandPalette({ open, onClose, onCommand }) {
  const [query, setQuery]     = useState('')
  const [selected, setSelected] = useState(0)
  const inputRef = useRef(null)
  const listRef  = useRef(null)

  const filtered = query.trim()
    ? ALL_COMMANDS.filter(c => c.label.toLowerCase().includes(query.toLowerCase()))
    : ALL_COMMANDS

  useEffect(() => {
    if (open) {
      setQuery('')
      setSelected(0)
      setTimeout(() => inputRef.current?.focus(), 40)
    }
  }, [open])

  useEffect(() => { setSelected(0) }, [query])

  // Scroll selected item into view on keyboard navigation
  useEffect(() => {
    const container = listRef.current
    if (!container) return
    const item = container.children[selected]
    if (item) item.scrollIntoView({ block: 'nearest' })
  }, [selected])

  function execute(cmd) {
    onCommand(cmd)
    onClose()
    setQuery('')
  }

  function handleKey(e) {
    if (e.key === 'Escape') { onClose(); return }
    if (e.key === 'ArrowDown') {
      e.preventDefault()
      setSelected(s => Math.min(s + 1, filtered.length - 1))
    }
    if (e.key === 'ArrowUp') {
      e.preventDefault()
      setSelected(s => Math.max(s - 1, 0))
    }
    if (e.key === 'Enter' && filtered[selected]) {
      execute(filtered[selected].cmd)
    }
  }

  if (!open) return null

  return (
    <div
      onClick={onClose}
      style={{
        position: 'fixed', inset: 0, zIndex: 1000,
        background: 'rgba(5,13,26,0.72)',
        backdropFilter: 'blur(4px)',
        display: 'flex', alignItems: 'flex-start', justifyContent: 'center',
        paddingTop: '11vh',
      }}
    >
      <div
        onClick={e => e.stopPropagation()}
        style={{
          width: 460, maxHeight: 440,
          background: '#071020',
          border: '1px solid rgba(0,229,255,0.28)',
          borderRadius: 6,
          boxShadow: '0 0 48px rgba(0,229,255,0.1), 0 12px 60px rgba(0,0,0,0.65)',
          display: 'flex', flexDirection: 'column',
          overflow: 'hidden',
          animation: 'paletteSlideIn 0.18s cubic-bezier(0.22,1,0.36,1)',
        }}
      >
        {/* Search row */}
        <div style={{
          display: 'flex', alignItems: 'center', gap: 10,
          padding: '12px 16px',
          borderBottom: '1px solid #0d2a3a',
          flexShrink: 0,
        }}>
          <span style={{ color: 'rgba(0,229,255,0.4)', fontSize: 15, lineHeight: 1 }}>⌘</span>
          <input
            ref={inputRef}
            value={query}
            onChange={e => setQuery(e.target.value)}
            onKeyDown={handleKey}
            placeholder="Search commands..."
            style={{
              flex: 1, background: 'transparent', border: 'none', outline: 'none',
              color: '#c8e8f0', fontFamily: "'JetBrains Mono'", fontSize: '13px',
              caretColor: '#00e5ff',
            }}
          />
          <span style={{ color: '#1a4a5a', fontFamily: "'Share Tech Mono'", fontSize: '9px', letterSpacing: '0.15em' }}>
            ESC
          </span>
        </div>

        {/* Results list */}
        <div ref={listRef} style={{ overflowY: 'auto', flex: 1 }}>
          {filtered.length === 0 ? (
            <div style={{
              padding: '24px 16px', color: '#1a4a5a',
              fontFamily: "'Share Tech Mono'", fontSize: '10px',
              letterSpacing: '0.15em', textAlign: 'center',
            }}>
              NO COMMANDS FOUND
            </div>
          ) : filtered.map((c, i) => (
            <div
              key={c.cmd}
              onClick={() => execute(c.cmd)}
              onMouseEnter={() => setSelected(i)}
              style={{
                display: 'flex', alignItems: 'center', gap: 12,
                padding: '9px 16px',
                background: selected === i ? 'rgba(0,229,255,0.07)' : 'transparent',
                borderLeft: `2px solid ${selected === i ? '#00e5ff' : 'transparent'}`,
                cursor: 'pointer',
                transition: 'background 0.08s',
              }}
            >
              <span style={{
                fontSize: 13, width: 20, textAlign: 'center', flexShrink: 0,
                color: selected === i ? '#00e5ff' : '#1a4a5a',
                lineHeight: 1,
              }}>
                {c.icon}
              </span>
              <span style={{
                color: selected === i ? '#c8e8f0' : '#3a6070',
                fontFamily: "'JetBrains Mono'", fontSize: '11px',
                flex: 1,
              }}>
                {c.label}
              </span>
              {selected === i && (
                <span style={{ color: '#1a4a5a', fontFamily: "'Share Tech Mono'", fontSize: '9px', letterSpacing: '0.12em' }}>
                  ENTER
                </span>
              )}
            </div>
          ))}
        </div>

        {/* Footer hint */}
        <div style={{
          padding: '7px 16px',
          borderTop: '1px solid #0d2a3a',
          display: 'flex', gap: 16, flexShrink: 0,
        }}>
          {[['↑↓', 'navigate'], ['↵', 'execute'], ['ESC', 'close']].map(([key, label]) => (
            <span key={key} style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
              <span style={{
                color: '#00e5ff', fontFamily: "'Share Tech Mono'",
                fontSize: '9px', letterSpacing: '0.05em',
                background: 'rgba(0,229,255,0.07)',
                border: '1px solid rgba(0,229,255,0.15)',
                borderRadius: 2, padding: '1px 5px',
              }}>{key}</span>
              <span style={{ color: '#1a4a5a', fontFamily: "'Share Tech Mono'", fontSize: '8px', letterSpacing: '0.1em' }}>
                {label}
              </span>
            </span>
          ))}
        </div>
      </div>
    </div>
  )
}
