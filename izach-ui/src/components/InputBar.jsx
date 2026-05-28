import React, { useRef, useEffect } from 'react'

const CHIPS = [
  'What time is it?',
  'Play music',
  'Open YouTube',
  'Take a screenshot',
  'Check weather',
]

export default function InputBar({
  inputText, setInputText,
  send, isLoading, isSpeaking,
  micActive, toggleMic, onStop,
}) {
  const inputRef  = useRef(null)
  const histRef   = useRef([])
  const histIdxRef = useRef(-1)

  useEffect(() => {
    if (!isLoading) inputRef.current?.focus()
  }, [isLoading])

  function handleKey(e) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      if (!isLoading && inputText.trim()) {
        histRef.current  = [inputText, ...histRef.current].slice(0, 50)
        histIdxRef.current = -1
        send(inputText)
      }
      return
    }
    if (e.key === 'ArrowUp' && histRef.current.length > 0) {
      e.preventDefault()
      const next = Math.min(histIdxRef.current + 1, histRef.current.length - 1)
      histIdxRef.current = next
      setInputText(histRef.current[next])
      return
    }
    if (e.key === 'ArrowDown') {
      e.preventDefault()
      const next = histIdxRef.current - 1
      if (next < 0) {
        histIdxRef.current = -1
        setInputText('')
      } else {
        histIdxRef.current = next
        setInputText(histRef.current[next])
      }
    }
  }

  function sendChip(chip) {
    histRef.current    = [chip, ...histRef.current].slice(0, 50)
    histIdxRef.current = -1
    send(chip)
  }

  const canSend  = !isLoading && inputText.trim().length > 0
  const busy     = isLoading || isSpeaking
  const showChips = !inputText && !isLoading

  return (
    <div style={{ display: 'flex', flexDirection: 'column', background: '#050d1a', flexShrink: 0, borderTop: '1px solid #0d2a3a' }}>

      {/* Suggestion chips */}
      {showChips && (
        <div style={{
          display: 'flex', gap: 6, padding: '6px 16px 0', flexWrap: 'wrap',
          animation: 'chipFadeIn 0.3s ease-out',
        }}>
          {CHIPS.map(chip => (
            <button
              key={chip}
              onClick={() => sendChip(chip)}
              style={{
                padding: '3px 10px',
                background: 'rgba(0,229,255,0.04)',
                border: '1px solid rgba(0,229,255,0.14)',
                borderRadius: 12, color: '#3a6070',
                fontFamily: "'Share Tech Mono'", fontSize: '9px',
                letterSpacing: '0.05em', cursor: 'pointer',
                transition: 'all 0.15s', whiteSpace: 'nowrap',
              }}
              onMouseEnter={e => {
                e.currentTarget.style.background   = 'rgba(0,229,255,0.1)'
                e.currentTarget.style.color        = '#00e5ff'
                e.currentTarget.style.borderColor  = 'rgba(0,229,255,0.35)'
              }}
              onMouseLeave={e => {
                e.currentTarget.style.background   = 'rgba(0,229,255,0.04)'
                e.currentTarget.style.color        = '#3a6070'
                e.currentTarget.style.borderColor  = 'rgba(0,229,255,0.14)'
              }}
            >
              {chip}
            </button>
          ))}
        </div>
      )}

      {/* Input row */}
      <div style={{
        display: 'flex', alignItems: 'center', gap: 8,
        padding: '8px 16px', position: 'relative',
      }}>
        {isLoading && (
          <div style={{
            position: 'absolute', top: 0, left: 0, right: 0, height: 1,
            background: 'linear-gradient(90deg, transparent 0%, #00e5ff 50%, transparent 100%)',
            animation: 'scanLine 1.4s linear infinite', opacity: 0.85,
          }} />
        )}

        <input
          ref={inputRef}
          type="text"
          value={inputText}
          onChange={e => { setInputText(e.target.value); histIdxRef.current = -1 }}
          onKeyDown={handleKey}
          disabled={isLoading}
          placeholder={isLoading ? 'Processing...' : '[ TYPE COMMAND ]  ↑↓ history  Ctrl+K palette'}
          className="input-glow"
          style={{
            flex: 1, padding: '9px 14px', background: '#071020',
            border: `1px solid ${isLoading ? 'rgba(0,229,255,0.35)' : '#0d2a3a'}`,
            borderRadius: 4, color: isLoading ? '#3a6070' : '#c8e8f0',
            fontFamily: "'JetBrains Mono'", fontSize: '11px', letterSpacing: '0.04em',
            caretColor: '#00e5ff', outline: 'none',
            cursor: isLoading ? 'not-allowed' : 'text',
            transition: 'border-color 0.2s, color 0.2s',
          }}
        />

        {inputText.length > 0 && !isLoading && (
          <span style={{
            color: inputText.length > 200 ? '#ffb300' : '#1a4a5a',
            fontFamily: "'Share Tech Mono'", fontSize: '9px', flexShrink: 0,
            letterSpacing: '0.05em', transition: 'color 0.2s', minWidth: 24, textAlign: 'right',
          }}>
            {inputText.length}
          </span>
        )}

        {isLoading ? (
          <div style={{
            display: 'flex', alignItems: 'center', gap: 6, padding: '9px 16px',
            background: 'rgba(0,229,255,0.04)', border: '1px solid rgba(0,229,255,0.15)',
            borderRadius: 4, color: '#00e5ff', fontFamily: "'Share Tech Mono'",
            fontSize: '10px', letterSpacing: '0.2em', whiteSpace: 'nowrap',
          }}>
            <LoadingDots />
            PROCESSING
          </div>
        ) : (
          <button
            onClick={() => canSend && send(inputText)}
            disabled={!canSend}
            style={{
              padding: '9px 16px',
              background: canSend ? 'rgba(0,229,255,0.08)' : 'rgba(0,229,255,0.02)',
              color: canSend ? '#00e5ff' : '#1a4a5a',
              border: `1px solid ${canSend ? 'rgba(0,229,255,0.3)' : '#0d2a3a'}`,
              borderRadius: 4, fontFamily: "'Share Tech Mono'", fontSize: '10px',
              letterSpacing: '0.2em', cursor: canSend ? 'pointer' : 'not-allowed',
              transition: 'all 0.2s', boxShadow: canSend ? '0 0 10px rgba(0,229,255,0.1)' : 'none',
              whiteSpace: 'nowrap',
            }}
            onMouseEnter={e => {
              if (canSend) {
                e.currentTarget.style.background  = 'rgba(0,229,255,0.14)'
                e.currentTarget.style.boxShadow   = '0 0 14px rgba(0,229,255,0.2)'
              }
            }}
            onMouseLeave={e => {
              if (canSend) {
                e.currentTarget.style.background  = 'rgba(0,229,255,0.08)'
                e.currentTarget.style.boxShadow   = '0 0 10px rgba(0,229,255,0.1)'
              }
            }}
          >
            TRANSMIT
          </button>
        )}

        <button
          onClick={onStop}
          style={{
            display: 'flex', alignItems: 'center', gap: 6, padding: '9px 12px',
            background: busy ? 'rgba(255,61,61,0.12)' : 'rgba(255,61,61,0.05)',
            color: '#ff3d3d',
            border: `1px solid ${busy ? 'rgba(255,61,61,0.4)' : 'rgba(255,61,61,0.2)'}`,
            borderRadius: 4, fontFamily: "'Share Tech Mono'", fontSize: '10px',
            letterSpacing: '0.15em', cursor: 'pointer', transition: 'all 0.2s',
            whiteSpace: 'nowrap', boxShadow: busy ? '0 0 8px rgba(255,61,61,0.15)' : 'none',
          }}
          onMouseEnter={e => {
            e.currentTarget.style.background = 'rgba(255,61,61,0.18)'
            e.currentTarget.style.boxShadow  = '0 0 12px rgba(255,61,61,0.2)'
          }}
          onMouseLeave={e => {
            e.currentTarget.style.background = busy ? 'rgba(255,61,61,0.12)' : 'rgba(255,61,61,0.05)'
            e.currentTarget.style.boxShadow  = busy ? '0 0 8px rgba(255,61,61,0.15)' : 'none'
          }}
        >
          <span style={{
            display: 'inline-block', width: 8, height: 8, background: '#ff3d3d',
            borderRadius: 1, boxShadow: busy ? '0 0 5px #ff3d3d' : 'none',
          }} />
          STOP
        </button>
      </div>
    </div>
  )
}

function LoadingDots() {
  return (
    <span style={{ display: 'flex', gap: 3, alignItems: 'center' }}>
      {[0, 1, 2].map(i => (
        <span key={i} style={{
          width: 4, height: 4, borderRadius: '50%', background: '#00e5ff',
          display: 'inline-block', animation: `blink 1s ${i * 0.2}s infinite`,
        }} />
      ))}
    </span>
  )
}
