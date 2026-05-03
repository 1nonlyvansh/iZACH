import React from 'react'

function ThinkingBubble() {
  return (
    <div className="chat-message flex flex-col items-start mb-3">
      <span
        style={{
          color: '#3a6070',
          fontFamily: "'Share Tech Mono'",
          fontSize: '10px',
          letterSpacing: '0.15em',
          marginBottom: 4,
        }}
      >
        iZACH
      </span>
      <div
        style={{
          padding: '10px 14px',
          background: 'rgba(7,16,32,0.9)',
          border: '1px solid #0d2a3a',
          borderRadius: '2px 8px 8px 8px',
          display: 'flex',
          alignItems: 'center',
          gap: 5,
        }}
      >
        {[0, 1, 2].map(i => (
          <span
            key={i}
            style={{
              width: 5,
              height: 5,
              borderRadius: '50%',
              background: '#00e5ff',
              display: 'inline-block',
              opacity: 0.6,
              animation: `blink 1.2s ${i * 0.25}s infinite`,
            }}
          />
        ))}
      </div>
    </div>
  )
}

function ChatMessage({ msg }) {
  const isUser     = msg.sender === 'YOU'
  const isThinking = msg.type  === 'thinking'
  const isError    = msg.type  === 'error'
  const isSystem   = msg.type  === 'system'

  if (isThinking) return <ThinkingBubble />

  let bubbleColor = isUser ? 'rgba(0,229,255,0.06)' : 'rgba(7,16,32,0.9)'
  let borderColor = isUser ? 'rgba(0,229,255,0.22)' : '#0d2a3a'
  let textColor   = '#c8e8f0'

  if (isError) {
    bubbleColor = 'rgba(255,61,61,0.06)'
    borderColor = 'rgba(255,61,61,0.25)'
    textColor   = '#ff9090'
  }
  if (isSystem) {
    bubbleColor = 'rgba(0,0,0,0)'
    borderColor = 'transparent'
    textColor   = '#3a6070'
  }

  return (
    <div
      className="chat-message"
      style={{
        display: 'flex',
        flexDirection: 'column',
        alignItems: isUser ? 'flex-end' : 'flex-start',
        marginBottom: 12,
      }}
    >
      <span
        style={{
          color: isUser ? '#00e5ff' : isError ? '#ff3d3d' : '#3a6070',
          fontFamily: "'Share Tech Mono'",
          fontSize: '10px',
          letterSpacing: '0.15em',
          marginBottom: 4,
        }}
      >
        {msg.sender}
        {isError && ' ⚠'}
      </span>

      <div
        style={{
          maxWidth: '87%',
          padding: isSystem ? '2px 0' : '9px 13px',
          background: bubbleColor,
          border: `1px solid ${borderColor}`,
          borderRadius: isUser ? '8px 2px 8px 8px' : '2px 8px 8px 8px',
          color: textColor,
          fontFamily: "'JetBrains Mono'",
          fontSize: '11px',
          lineHeight: '1.65',
          wordBreak: 'break-word',
          boxShadow: isUser
            ? '0 0 16px rgba(0,229,255,0.05)'
            : isError
            ? '0 0 12px rgba(255,61,61,0.05)'
            : '0 1px 8px rgba(0,0,0,0.25)',
          fontStyle: isSystem ? 'italic' : 'normal',
        }}
      >
        {msg.text}
      </div>

      <span
        style={{
          color: '#1a4a5a',
          fontFamily: "'JetBrains Mono'",
          fontSize: '9px',
          marginTop: 3,
        }}
      >
        {msg.ts}
      </span>
    </div>
  )
}

export default function ChatPanel({ messages, chatBottomRef }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      {/* Header */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 8,
          padding: '10px 16px',
          borderBottom: '1px solid #0d2a3a',
          flexShrink: 0,
        }}
      >
        <span style={{ color: '#00e5ff' }}>*</span>
        <span
          style={{
            color: '#00e5ff',
            fontFamily: "'Share Tech Mono'",
            fontSize: '10px',
            letterSpacing: '0.2em',
          }}
        >
          COMMAND LOG
        </span>
        <div style={{ flex: 1, height: 1, background: '#0d2a3a' }} />
        <span
          style={{
            color: '#1a4a5a',
            fontFamily: "'Share Tech Mono'",
            fontSize: '9px',
            letterSpacing: '0.1em',
          }}
        >
          {messages.length} MSG
        </span>
      </div>

      {/* Messages area */}
      <div
        style={{
          flex: 1,
          overflowY: 'auto',
          padding: '12px 16px',
          scrollbarWidth: 'thin',
        }}
      >
        {messages.length === 0 && (
          <p
            style={{
              color: '#1a4a5a',
              fontFamily: "'Share Tech Mono'",
              fontSize: '10px',
              letterSpacing: '0.15em',
              textAlign: 'center',
              marginTop: 32,
            }}
          >
            AWAITING INPUT
          </p>
        )}

        {messages.map(msg => (
          <ChatMessage key={msg.id} msg={msg} />
        ))}

        <div ref={chatBottomRef} />
      </div>
    </div>
  )
}