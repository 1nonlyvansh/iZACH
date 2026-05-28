import React, { useState, useRef, useEffect } from 'react'

// Typewriter that animates on mount, then shows full text
function TypewriterText({ text, onDone }) {
  const [displayed, setDisplayed] = useState('')
  const [done, setDone] = useState(false)

  useEffect(() => {
    if (!text) { setDone(true); onDone?.(); return }
    // For very long text use a faster interval
    const speed = text.length > 300 ? 4 : text.length > 120 ? 7 : 11
    let i = 0
    setDisplayed('')
    setDone(false)
    const id = setInterval(() => {
      i++
      setDisplayed(text.slice(0, i))
      if (i >= text.length) {
        clearInterval(id)
        setDone(true)
        onDone?.()
      }
    }, speed)
    return () => clearInterval(id)
  }, [text])

  return (
    <>
      {displayed}
      {!done && <span className="blink" style={{ marginLeft: 1, fontWeight: 400 }}>▋</span>}
    </>
  )
}

function ThinkingBubble() {
  return (
    <div className="chat-message flex flex-col items-start mb-3">
      <span style={{ color: '#3a6070', fontFamily: "'Share Tech Mono'", fontSize: '10px', letterSpacing: '0.15em', marginBottom: 4 }}>
        iZACH
      </span>
      <div style={{
        padding: '10px 14px', background: 'rgba(7,16,32,0.9)',
        border: '1px solid #0d2a3a', borderRadius: '2px 8px 8px 8px',
        display: 'flex', alignItems: 'center', gap: 5,
      }}>
        {[0, 1, 2].map(i => (
          <span key={i} style={{
            width: 5, height: 5, borderRadius: '50%', background: '#00e5ff',
            display: 'inline-block', opacity: 0.6,
            animation: `blink 1.2s ${i * 0.25}s infinite`,
          }} />
        ))}
      </div>
    </div>
  )
}

function ChatMessage({ msg, isTyping, onTypeDone }) {
  const [hovered, setHovered] = useState(false)
  const [copied,  setCopied]  = useState(false)

  const isUser     = msg.sender === 'YOU'
  const isThinking = msg.type  === 'thinking'
  const isError    = msg.type  === 'error'
  const isSystem   = msg.type  === 'system'

  if (isThinking) return <ThinkingBubble />

  let bubbleColor = isUser ? 'rgba(0,229,255,0.06)' : 'rgba(255,255,255,0.03)'
  let borderColor = isUser ? 'rgba(0,229,255,0.22)' : 'rgba(0,229,255,0.12)'
  let textColor   = '#c8e8f0'

  if (isError)  { bubbleColor = 'rgba(255,61,61,0.06)'; borderColor = 'rgba(255,61,61,0.25)'; textColor = '#ff9090' }
  if (isSystem) { bubbleColor = 'rgba(0,0,0,0)'; borderColor = 'transparent'; textColor = '#3a6070' }

  function copy() {
    if (!msg.text) return
    import('../utils/clipboard.js').then(({ copyToClipboard }) => {
      copyToClipboard(msg.text).then(ok => {
        if (ok) {
          setCopied(true)
          setTimeout(() => setCopied(false), 2000)
        }
      })
    })
  }

  return (
    <div
      className="chat-message"
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      style={{
        display: 'flex', flexDirection: 'column',
        alignItems: isUser ? 'flex-end' : 'flex-start',
        marginBottom: 12, position: 'relative',
      }}
    >
      <span style={{
        color: isUser ? '#00e5ff' : isError ? '#ff3d3d' : '#3a6070',
        fontFamily: "'Share Tech Mono'", fontSize: '10px', letterSpacing: '0.15em', marginBottom: 4,
      }}>
        {msg.sender}{isError && ' ⚠'}
      </span>

      <div style={{ position: 'relative', maxWidth: '87%' }}>
        <div
          className="chat-bubble"
          style={{
            padding: isSystem ? '2px 0' : '9px 13px',
            background: bubbleColor, border: `1px solid ${borderColor}`,
            borderRadius: isUser ? '8px 2px 8px 8px' : '2px 8px 8px 8px',
            color: textColor, fontFamily: "'JetBrains Mono'",
            fontSize: '11px', lineHeight: '1.65', wordBreak: 'break-word',
            boxShadow: isUser
              ? '0 0 16px rgba(0,229,255,0.05)'
              : isError ? '0 0 12px rgba(255,61,61,0.05)' : '0 1px 8px rgba(0,0,0,0.25)',
            fontStyle: isSystem ? 'italic' : 'normal',
            transition: 'border-color 0.15s',
          }}
        >
          {isTyping
            ? <TypewriterText text={msg.text} onDone={onTypeDone} />
            : msg.text
          }
        </div>

        {hovered && !isSystem && (
          <button
            onClick={copy}
            title={copied ? 'Copied!' : 'Copy'}
            style={{
              position: 'absolute', top: 4,
              [isUser ? 'left' : 'right']: -26,
              width: 20, height: 20,
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              background: copied ? 'rgba(29,185,84,0.12)' : 'rgba(0,229,255,0.08)',
              border: `1px solid ${copied ? 'rgba(29,185,84,0.3)' : 'rgba(0,229,255,0.2)'}`,
              borderRadius: 3, color: copied ? '#1db954' : '#00e5ff',
              fontSize: 10, cursor: 'pointer', transition: 'all 0.15s',
              animation: 'chatFadeIn 0.12s ease-out', flexShrink: 0,
            }}
          >
            {copied ? '✓' : '⧉'}
          </button>
        )}
      </div>

      <span style={{ color: '#1a4a5a', fontFamily: "'JetBrains Mono'", fontSize: '9px', marginTop: 3 }}>
        {msg.ts}
      </span>
    </div>
  )
}

export default function ChatPanel({ messages, chatBottomRef }) {
  const scrollRef      = useRef(null)
  const lastSeenIdRef  = useRef(messages.length > 0 ? messages[messages.length - 1].id : null)
  const [showFab, setShowFab]   = useState(false)
  const [typingId, setTypingId] = useState(null)

  // Detect new iZACH messages → trigger typewriter
  useEffect(() => {
    if (messages.length === 0) return
    const last = messages[messages.length - 1]
    // Only typewrite if this is a genuinely new message (different ID from last seen)
    if (last.id !== lastSeenIdRef.current) {
      lastSeenIdRef.current = last.id
      if (last.sender !== 'YOU' && !last.type) {
        setTypingId(last.id)
      }
    }
  }, [messages])

  function handleScroll() {
    const el = scrollRef.current
    if (!el) return
    setShowFab(el.scrollHeight - el.scrollTop - el.clientHeight > 60)
  }

  function scrollToBottom() {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' })
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', position: 'relative' }}>
      {/* Header */}
      <div style={{
        display: 'flex', alignItems: 'center', gap: 8,
        padding: '10px 16px', borderBottom: '1px solid #0d2a3a', flexShrink: 0,
      }}>
        <span style={{ color: '#00e5ff' }}>*</span>
        <span style={{ color: '#00e5ff', fontFamily: "'Share Tech Mono'", fontSize: '10px', letterSpacing: '0.2em' }}>
          COMMAND LOG
        </span>
        <div style={{ flex: 1, height: 1, background: '#0d2a3a' }} />
        {messages.length > 0 && (
          <span style={{
            color: '#00e5ff', fontFamily: "'Share Tech Mono'", fontSize: '9px', letterSpacing: '0.1em',
            background: 'rgba(0,229,255,0.06)', border: '1px solid rgba(0,229,255,0.15)',
            borderRadius: 3, padding: '1px 6px',
          }}>
            {messages.length}
          </span>
        )}
      </div>

      {/* Messages */}
      <div
        ref={scrollRef}
        onScroll={handleScroll}
        style={{ flex: 1, overflowY: 'auto', padding: '12px 20px 12px 16px', scrollbarWidth: 'thin' }}
      >
        {messages.length === 0 && (
          <div style={{ textAlign: 'center', marginTop: 40, padding: '0 20px' }}>
            <div style={{ display: 'inline-flex', gap: 5, alignItems: 'center', marginBottom: 10 }}>
              {[0, 1, 2].map(i => (
                <span key={i} style={{
                  width: 4, height: 4, borderRadius: '50%', background: '#0d2a3a',
                  display: 'inline-block', animation: `blink 2s ${i * 0.4}s infinite`,
                }} />
              ))}
            </div>
            <p style={{ color: '#1a4a5a', fontFamily: "'Share Tech Mono'", fontSize: '10px', letterSpacing: '0.2em' }}>
              AWAITING INPUT
            </p>
            <p style={{ color: '#0d2a3a', fontFamily: "'JetBrains Mono'", fontSize: '9px', marginTop: 6, letterSpacing: '0.05em' }}>
              speak or type a command
            </p>
          </div>
        )}

        {messages.map(msg => (
          <ChatMessage
            key={msg.id}
            msg={msg}
            isTyping={msg.id === typingId}
            onTypeDone={() => setTypingId(cur => cur === msg.id ? null : cur)}
          />
        ))}

        <div ref={chatBottomRef} />
      </div>

      {showFab && (
        <button
          onClick={scrollToBottom}
          className="scroll-fab"
          style={{
            position: 'absolute', bottom: 12, right: 10,
            width: 26, height: 26, borderRadius: '50%',
            background: 'rgba(0,229,255,0.1)', border: '1px solid rgba(0,229,255,0.3)',
            color: '#00e5ff', cursor: 'pointer', fontSize: 13,
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            boxShadow: '0 0 12px rgba(0,229,255,0.2)', zIndex: 10,
          }}
          title="Scroll to latest"
        >
          ↓
        </button>
      )}
    </div>
  )
}
