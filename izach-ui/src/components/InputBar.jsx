import React, { useRef, useEffect } from 'react'

export default function InputBar({
  inputText,
  setInputText,
  send,
  isLoading,
  isSpeaking,
  micActive,
  toggleMic,
  onStop,
}) {
  const inputRef = useRef(null)

  useEffect(() => {
    if (!isLoading) inputRef.current?.focus()
  }, [isLoading])

  function handleKey(e) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      if (!isLoading && inputText.trim()) send(inputText)
    }
  }

  const canSend = !isLoading && inputText.trim().length > 0
  const busy    = isLoading || isSpeaking

  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 8,
        padding: '8px 16px',
        background: '#050d1a',
        borderTop: '1px solid #0d2a3a',
        flexShrink: 0,
        position: 'relative',
      }}
    >
      {/* Scanning progress line while loading */}
      {isLoading && (
        <div
          style={{
            position: 'absolute',
            top: 0,
            left: 0,
            right: 0,
            height: 1,
            background:
              'linear-gradient(90deg, transparent 0%, #00e5ff 50%, transparent 100%)',
            animation: 'scan 1.4s linear infinite',
            opacity: 0.85,
          }}
        />
      )}

      {/* Text input */}
      <input
        ref={inputRef}
        type="text"
        value={inputText}
        onChange={e => setInputText(e.target.value)}
        onKeyDown={handleKey}
        disabled={isLoading}
        placeholder={isLoading ? 'Processing...' : '[ TYPE COMMAND HERE ]...'}
        className="input-glow"
        style={{
          flex: 1,
          padding: '9px 14px',
          background: '#071020',
          border: `1px solid ${isLoading ? 'rgba(0,229,255,0.35)' : '#0d2a3a'}`,
          borderRadius: 4,
          color: isLoading ? '#3a6070' : '#c8e8f0',
          fontFamily: "'JetBrains Mono'",
          fontSize: '11px',
          letterSpacing: '0.04em',
          caretColor: '#00e5ff',
          outline: 'none',
          cursor: isLoading ? 'not-allowed' : 'text',
          transition: 'border-color 0.2s, color 0.2s',
        }}
      />

      {/* Loading indicator OR TRANSMIT button */}
      {isLoading ? (
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 6,
            padding: '9px 16px',
            background: 'rgba(0,229,255,0.04)',
            border: '1px solid rgba(0,229,255,0.15)',
            borderRadius: 4,
            color: '#00e5ff',
            fontFamily: "'Share Tech Mono'",
            fontSize: '10px',
            letterSpacing: '0.2em',
            whiteSpace: 'nowrap',
          }}
        >
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
            borderRadius: 4,
            fontFamily: "'Share Tech Mono'",
            fontSize: '10px',
            letterSpacing: '0.2em',
            cursor: canSend ? 'pointer' : 'not-allowed',
            transition: 'all 0.2s',
            boxShadow: canSend ? '0 0 10px rgba(0,229,255,0.1)' : 'none',
            whiteSpace: 'nowrap',
          }}
          onMouseEnter={e => {
            if (canSend) {
              e.currentTarget.style.background = 'rgba(0,229,255,0.14)'
              e.currentTarget.style.boxShadow = '0 0 14px rgba(0,229,255,0.2)'
            }
          }}
          onMouseLeave={e => {
            if (canSend) {
              e.currentTarget.style.background = 'rgba(0,229,255,0.08)'
              e.currentTarget.style.boxShadow = '0 0 10px rgba(0,229,255,0.1)'
            }
          }}
        >
          TRANSMIT
        </button>
      )}

      {/* STOP button */}
      <button
        onClick={onStop}
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 6,
          padding: '9px 12px',
          background: busy ? 'rgba(255,61,61,0.12)' : 'rgba(255,61,61,0.05)',
          color: '#ff3d3d',
          border: `1px solid ${busy ? 'rgba(255,61,61,0.4)' : 'rgba(255,61,61,0.2)'}`,
          borderRadius: 4,
          fontFamily: "'Share Tech Mono'",
          fontSize: '10px',
          letterSpacing: '0.15em',
          cursor: 'pointer',
          transition: 'all 0.2s',
          whiteSpace: 'nowrap',
          boxShadow: busy ? '0 0 8px rgba(255,61,61,0.15)' : 'none',
        }}
        onMouseEnter={e => {
          e.currentTarget.style.background = 'rgba(255,61,61,0.18)'
          e.currentTarget.style.boxShadow = '0 0 12px rgba(255,61,61,0.2)'
        }}
        onMouseLeave={e => {
          e.currentTarget.style.background = busy ? 'rgba(255,61,61,0.12)' : 'rgba(255,61,61,0.05)'
          e.currentTarget.style.boxShadow = busy ? '0 0 8px rgba(255,61,61,0.15)' : 'none'
        }}
      >
        <span
          style={{
            display: 'inline-block',
            width: 8,
            height: 8,
            background: '#ff3d3d',
            borderRadius: 1,
            boxShadow: busy ? '0 0 5px #ff3d3d' : 'none',
          }}
        />
        STOP
      </button>
    </div>
  )
}

function LoadingDots() {
  return (
    <span style={{ display: 'flex', gap: 3, alignItems: 'center' }}>
      {[0, 1, 2].map(i => (
        <span
          key={i}
          style={{
            width: 4,
            height: 4,
            borderRadius: '50%',
            background: '#00e5ff',
            display: 'inline-block',
            animation: `blink 1s ${i * 0.2}s infinite`,
          }}
        />
      ))}
    </span>
  )
}