import React, { useEffect, useRef } from 'react'

export default function NeuralOrb({ isSpeaking, liveText, micActive, toggleMic }) {
  const canvasRef = useRef(null)
  const animRef   = useRef(null)
  const nodesRef  = useRef([])
  const timeRef   = useRef(0)

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')
    const W = canvas.width  = 320
    const H = canvas.height = 320
    const CX = W / 2, CY = H / 2

    // Generate neural nodes
    const NODES = 18
    nodesRef.current = Array.from({ length: NODES }, (_, i) => {
      const angle = (i / NODES) * Math.PI * 2
      const r = 60 + Math.random() * 55
      return {
        x: CX + Math.cos(angle) * r,
        y: CY + Math.sin(angle) * r,
        ox: CX + Math.cos(angle) * r,
        oy: CY + Math.sin(angle) * r,
        vx: (Math.random() - 0.5) * 0.3,
        vy: (Math.random() - 0.5) * 0.3,
        size: 2 + Math.random() * 2,
        phase: Math.random() * Math.PI * 2,
      }
    })
    // Add center node
    nodesRef.current.push({ x: CX, y: CY, ox: CX, oy: CY, vx: 0, vy: 0, size: 6, phase: 0, center: true })

    function draw(t) {
      timeRef.current = t * 0.001
      const time = timeRef.current
      const speaking = isSpeaking

      ctx.clearRect(0, 0, W, H)

      // Background glow
      const grad = ctx.createRadialGradient(CX, CY, 0, CX, CY, 120)
      grad.addColorStop(0, speaking ? 'rgba(0,229,255,0.08)' : 'rgba(0,229,255,0.04)')
      grad.addColorStop(1, 'rgba(0,229,255,0)')
      ctx.fillStyle = grad
      ctx.fillRect(0, 0, W, H)

      const nodes = nodesRef.current
      const n = nodes.length

      // Move nodes
      nodes.forEach(nd => {
        if (nd.center) return
        nd.x += nd.vx
        nd.y += nd.vy
        // gentle orbit
        nd.vx += (nd.ox - nd.x) * 0.002 + Math.sin(time + nd.phase) * 0.04
        nd.vy += (nd.oy - nd.y) * 0.002 + Math.cos(time + nd.phase) * 0.04
        nd.vx *= 0.97
        nd.vy *= 0.97
      })

      // Draw edges
      for (let i = 0; i < n; i++) {
        for (let j = i + 1; j < n; j++) {
          const a = nodes[i], b = nodes[j]
          const dist = Math.hypot(a.x - b.x, a.y - b.y)
          if (dist < 120) {
            const alpha = (1 - dist / 120) * 0.4 * (speaking ? 1.5 : 1)
            ctx.beginPath()
            ctx.moveTo(a.x, a.y)
            ctx.lineTo(b.x, b.y)
            ctx.strokeStyle = `rgba(0,229,255,${Math.min(alpha, 0.6)})`
            ctx.lineWidth = 0.5
            ctx.stroke()
          }
        }
      }

      // Draw nodes
      nodes.forEach(nd => {
        const pulse = speaking
          ? 0.6 + Math.sin(time * 4 + nd.phase) * 0.4
          : 0.4 + Math.sin(time * 1.5 + nd.phase) * 0.2
        const r = nd.size * pulse

        // outer glow
        const g = ctx.createRadialGradient(nd.x, nd.y, 0, nd.x, nd.y, r * 4)
        g.addColorStop(0, `rgba(0,229,255,${nd.center ? 0.6 : 0.3})`)
        g.addColorStop(1, 'rgba(0,229,255,0)')
        ctx.fillStyle = g
        ctx.beginPath()
        ctx.arc(nd.x, nd.y, r * 4, 0, Math.PI * 2)
        ctx.fill()

        // core dot
        ctx.fillStyle = nd.center
          ? `rgba(0,229,255,${0.7 + Math.sin(time * 2) * 0.3})`
          : `rgba(0,229,255,${pulse})`
        ctx.beginPath()
        ctx.arc(nd.x, nd.y, r, 0, Math.PI * 2)
        ctx.fill()
      })

      // Outer ring
      ctx.beginPath()
      ctx.arc(CX, CY, 130, 0, Math.PI * 2)
      ctx.strokeStyle = `rgba(0,229,255,${0.06 + (speaking ? 0.06 : 0)})`
      ctx.lineWidth = 1
      ctx.stroke()

      animRef.current = requestAnimationFrame(draw)
    }

    animRef.current = requestAnimationFrame(draw)
    return () => cancelAnimationFrame(animRef.current)
  }, [isSpeaking])

  return (
    <div className="flex flex-col items-center justify-center py-2">
      <canvas
        ref={canvasRef}
        width={320}
        height={320}
        style={{ imageRendering: 'crisp-edges' }}
      />
      {/* Live text bar */}
      <div
        className="w-full text-center px-4 py-2 transition-all duration-300"
        style={{
          background: liveText ? 'rgba(0,229,255,0.06)' : 'transparent',
          borderTop: liveText ? '1px solid rgba(0,229,255,0.15)' : '1px solid transparent',
          minHeight: '36px',
        }}
      >
        {liveText ? (
          <p className="text-xs tracking-wide italic" style={{ color: '#00e5ff', fontFamily: "'JetBrains Mono'" }}>
            {liveText}
            <span className="blink ml-0.5">|</span>
          </p>
        ) : (
          <button
            onClick={toggleMic}
            style={{
              background: micActive ? 'rgba(0,229,255,0.08)' : 'rgba(255,61,61,0.08)',
              border: `1px solid ${micActive ? 'rgba(0,229,255,0.3)' : 'rgba(255,61,61,0.3)'}`,
              borderRadius: 4,
              color: micActive ? '#00e5ff' : '#ff3d3d',
              fontFamily: "'Share Tech Mono'",
              fontSize: '10px',
              letterSpacing: '0.2em',
              padding: '5px 18px',
              cursor: 'pointer',
              transition: 'all 0.2s',
            }}
          >
            {micActive ? '⬤  MIC ON' : '⬤  MIC OFF'}
          </button>
        )}
      </div>
    </div>
  )
}