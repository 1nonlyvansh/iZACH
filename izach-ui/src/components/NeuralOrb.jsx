import React, { useEffect, useRef, useState } from 'react'
import * as THREE from 'three'

const BARS = [
  { h: 0.45, dur: 0.55 }, { h: 0.70, dur: 0.42 }, { h: 0.55, dur: 0.60 },
  { h: 1.00, dur: 0.38 }, { h: 0.80, dur: 0.48 }, { h: 0.65, dur: 0.44 },
  { h: 0.50, dur: 0.52 }, { h: 0.85, dur: 0.40 }, { h: 0.60, dur: 0.57 },
]

export default function NeuralOrb({ isSpeaking, liveText, micActive, toggleMic }) {
  const mountRef      = useRef(null)
  const isSpeakingRef = useRef(isSpeaking)
  const isDraggingRef = useRef(false)
  const lastMouseRef  = useRef({ x: 0, y: 0 })
  const dragDeltaRef  = useRef({ x: 0, y: 0 })
  const [isHovered, setIsHovered] = useState(false)

  // Waveform — canvas ref kept for potential future use but WebAudio capture
  // is intentionally disabled: Chromium exclusive-mode grab would block
  // pyaudio / speech_recognition in the Python backend (Windows shared-mic
  // conflict).  Visual feedback uses the animated bars below instead.
  const waveCanvasRef = useRef(null)

  useEffect(() => { isSpeakingRef.current = isSpeaking }, [isSpeaking])

  // ── Three.js scene ────────────────────────────────────────────
  useEffect(() => {
    const mount = mountRef.current
    if (!mount) return

    const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true })
    renderer.setSize(320, 320)
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2))
    renderer.setClearColor(0x000000, 0)
    mount.appendChild(renderer.domElement)

    const scene  = new THREE.Scene()
    const camera = new THREE.PerspectiveCamera(50, 1, 0.1, 100)
    camera.position.z = 4.2

    const orbGeo = new THREE.IcosahedronGeometry(0.85, 4)
    const orbMat = new THREE.MeshStandardMaterial({
      color: 0x00e5ff, emissive: 0x003344, emissiveIntensity: 0.6,
      roughness: 0.15, metalness: 0.9, wireframe: false, transparent: true, opacity: 0.92,
    })
    const orb = new THREE.Mesh(orbGeo, orbMat)
    scene.add(orb)

    const shellGeo = new THREE.IcosahedronGeometry(0.88, 2)
    const shellMat = new THREE.MeshBasicMaterial({ color: 0x00e5ff, wireframe: true, transparent: true, opacity: 0.12 })
    const shell    = new THREE.Mesh(shellGeo, shellMat)
    scene.add(shell)

    const torusGeo = new THREE.TorusGeometry(1.4, 0.012, 8, 80)
    const torusMat = new THREE.MeshBasicMaterial({ color: 0x00e5ff, transparent: true, opacity: 0.4 })
    const torus    = new THREE.Mesh(torusGeo, torusMat)
    torus.rotation.x = Math.PI / 2
    scene.add(torus)

    const torus2Geo = new THREE.TorusGeometry(1.55, 0.006, 6, 60)
    const torus2Mat = new THREE.MeshBasicMaterial({ color: 0x00e5ff, transparent: true, opacity: 0.18 })
    const torus2    = new THREE.Mesh(torus2Geo, torus2Mat)
    torus2.rotation.x = Math.PI / 3.5
    torus2.rotation.y = Math.PI / 5
    scene.add(torus2)

    const PARTICLE_COUNT = 280
    const pPositions = new Float32Array(PARTICLE_COUNT * 3)
    for (let i = 0; i < PARTICLE_COUNT; i++) {
      const r     = 1.8 + Math.random() * 1.0
      const theta = Math.random() * Math.PI * 2
      const phi   = Math.acos(2 * Math.random() - 1)
      pPositions[i * 3]     = r * Math.sin(phi) * Math.cos(theta)
      pPositions[i * 3 + 1] = r * Math.sin(phi) * Math.sin(theta)
      pPositions[i * 3 + 2] = r * Math.cos(phi)
    }
    const pGeo = new THREE.BufferGeometry()
    pGeo.setAttribute('position', new THREE.BufferAttribute(pPositions, 3))
    const pMat      = new THREE.PointsMaterial({ color: 0x00e5ff, size: 0.022, transparent: true, opacity: 0.55, sizeAttenuation: true })
    const particles = new THREE.Points(pGeo, pMat)
    scene.add(particles)

    scene.add(new THREE.AmbientLight(0x003344, 2.0))
    const pointLight = new THREE.PointLight(0x00e5ff, 3.0, 12)
    pointLight.position.set(2, 2, 2)
    scene.add(pointLight)
    const fillLight = new THREE.PointLight(0x0055aa, 1.5, 10)
    fillLight.position.set(-2, -1, -2)
    scene.add(fillLight)

    let frameId, t = 0

    const animate = () => {
      frameId = requestAnimationFrame(animate)
      t += 0.01

      const speaking = isSpeakingRef.current
      const speed    = speaking ? 1.8 : 0.6
      const pulse    = speaking
        ? 1.0 + 0.12 * Math.sin(t * 6)
        : 1.0 + 0.03 * Math.sin(t * 1.5)

      // Drag rotation
      if (dragDeltaRef.current.x || dragDeltaRef.current.y) {
        orb.rotation.y   += dragDeltaRef.current.x
        orb.rotation.x   += dragDeltaRef.current.y
        shell.rotation.y += dragDeltaRef.current.x * 0.5
        dragDeltaRef.current = { x: 0, y: 0 }
      }

      orb.rotation.y += 0.004 * speed
      orb.rotation.x += 0.002 * speed
      orb.scale.setScalar(pulse)

      shell.rotation.y -= 0.003 * speed
      shell.rotation.z += 0.002 * speed
      torus.rotation.z  += 0.006 * speed
      torus2.rotation.x += 0.004 * speed
      torus2.rotation.y += 0.003 * speed
      particles.rotation.y += 0.0015 * speed

      const glow = speaking ? 1.2 + 0.4 * Math.sin(t * 8) : 0.4
      orbMat.emissiveIntensity   = glow
      torusMat.opacity           = speaking ? 0.7 + 0.2 * Math.sin(t * 6) : 0.4
      torus2Mat.opacity          = speaking ? 0.35 : 0.18
      shellMat.opacity           = speaking ? 0.28 : 0.12
      pMat.opacity               = speaking ? 0.75 : 0.55
      pointLight.intensity       = speaking ? 4.5 + 1.5 * Math.sin(t * 5) : 3.0

      renderer.render(scene, camera)
    }
    animate()

    // Drag rotation events
    const onDown = (e) => {
      isDraggingRef.current    = true
      lastMouseRef.current     = { x: e.clientX, y: e.clientY }
      renderer.domElement.style.cursor = 'grabbing'
    }
    const onMove = (e) => {
      if (!isDraggingRef.current) return
      // Accumulate across multiple mousemoves between frames
      dragDeltaRef.current = {
        x: dragDeltaRef.current.x + (e.clientX - lastMouseRef.current.x) * 0.009,
        y: dragDeltaRef.current.y + (e.clientY - lastMouseRef.current.y) * 0.009,
      }
      lastMouseRef.current = { x: e.clientX, y: e.clientY }
    }
    const onUp = () => {
      isDraggingRef.current            = false
      renderer.domElement.style.cursor = 'grab'
    }

    renderer.domElement.style.cursor = 'grab'
    renderer.domElement.addEventListener('mousedown', onDown)
    window.addEventListener('mousemove', onMove)
    window.addEventListener('mouseup',   onUp)

    return () => {
      cancelAnimationFrame(frameId)
      renderer.domElement.removeEventListener('mousedown', onDown)
      window.removeEventListener('mousemove', onMove)
      window.removeEventListener('mouseup',   onUp)
      renderer.dispose()
      if (mount.contains(renderer.domElement)) mount.removeChild(renderer.domElement)
    }
  }, [])

  // ── Mic waveform ──────────────────────────────────────────────
  // NOTE: We do NOT call getUserMedia here.  Chromium acquires the mic in
  // exclusive mode on Windows, which prevents pyaudio / speech_recognition
  // in the Python backend from opening the same device — breaking all voice
  // commands.  Visual feedback is provided by the animated bars below.

  return (
    <div className="flex flex-col items-center justify-center py-2" style={{ position: 'relative' }}>

      {isSpeaking && (
        <div style={{
          position: 'absolute', width: 310, height: 310, borderRadius: '50%',
          border: '1px solid rgba(0,229,255,0.3)', pointerEvents: 'none', top: 8,
          animation: 'orbRingPulse 1.4s ease-in-out infinite',
        }} />
      )}

      {/* Three.js canvas */}
      <div
        ref={mountRef}
        style={{ width: 320, height: 320, position: 'relative' }}
        onMouseEnter={() => setIsHovered(true)}
        onMouseLeave={() => setIsHovered(false)}
      />

      {/* HUD labels */}
      <div style={{
        position: 'absolute', top: 18, left: 8, fontFamily: "'Share Tech Mono'",
        fontSize: '8px', color: 'rgba(0,229,255,0.35)', letterSpacing: '0.15em',
        pointerEvents: 'none', lineHeight: 1.7,
      }}>
        <div>iZ.ACH</div>
        <div style={{ color: isSpeaking ? 'rgba(0,229,255,0.7)' : micActive ? 'rgba(0,229,255,0.5)' : isHovered ? 'rgba(0,229,255,0.4)' : 'rgba(0,229,255,0.2)' }}>
          {isSpeaking ? 'SPEAKING' : micActive ? 'LISTENING' : isHovered ? 'DRAG ORB' : 'STANDBY'}
        </div>
      </div>

      <div style={{
        position: 'absolute', top: 18, right: 8, fontFamily: "'Share Tech Mono'",
        fontSize: '8px', color: 'rgba(0,229,255,0.35)', letterSpacing: '0.15em',
        pointerEvents: 'none', textAlign: 'right', lineHeight: 1.7,
      }}>
        <div>NEURAL</div>
        <div>CORE</div>
      </div>

      {/* Waveform strip — animated bars for both listening and speaking states */}
      <div style={{ height: 28, marginTop: 2, marginBottom: 2, width: 180, position: 'relative' }}>
        <div style={{
          display: 'flex', alignItems: 'flex-end', justifyContent: 'center',
          gap: 3, height: '100%',
          opacity: (isSpeaking || micActive) ? 1 : 0, transition: 'opacity 0.35s ease',
        }}>
          {BARS.map(({ h, dur }, i) => (
            <div key={i} className="sound-bar" style={{
              width: 3,
              height: micActive && !isSpeaking ? `${(0.2 + h * 0.35) * 100}%` : `${h * 100}%`,
              background: micActive && !isSpeaking
                ? 'linear-gradient(to top, rgba(0,229,255,0.25), rgba(0,229,255,0.55))'
                : 'linear-gradient(to top, rgba(0,229,255,0.4), #00e5ff)',
              borderRadius: 2,
              boxShadow: micActive && !isSpeaking
                ? '0 0 3px rgba(0,229,255,0.3)'
                : '0 0 5px rgba(0,229,255,0.5)',
              animation: (isSpeaking || micActive)
                ? `soundBar ${dur}s ease-in-out ${i * 0.055}s infinite`
                : 'none',
            }} />
          ))}
        </div>
      </div>

      {/* Live text / mic button */}
      <div className="w-full text-center px-4 py-2 transition-all duration-300" style={{
        background: liveText ? 'rgba(0,229,255,0.06)' : 'transparent',
        borderTop: liveText ? '1px solid rgba(0,229,255,0.15)' : '1px solid transparent',
        minHeight: '36px',
      }}>
        {liveText ? (
          <p className="text-xs tracking-wide italic" style={{ color: '#00e5ff', fontFamily: "'JetBrains Mono'" }}>
            {liveText}<span className="blink ml-0.5">|</span>
          </p>
        ) : (
          <button
            onClick={toggleMic}
            style={{
              background: micActive ? 'rgba(0,229,255,0.08)' : 'rgba(255,61,61,0.08)',
              border: `1px solid ${micActive ? 'rgba(0,229,255,0.3)' : 'rgba(255,61,61,0.3)'}`,
              borderRadius: 4, color: micActive ? '#00e5ff' : '#ff3d3d',
              fontFamily: "'Share Tech Mono'", fontSize: '10px', letterSpacing: '0.2em',
              padding: '5px 18px', cursor: 'pointer', transition: 'all 0.2s',
              boxShadow: micActive ? '0 0 12px rgba(0,229,255,0.15)' : '0 0 8px rgba(255,61,61,0.1)',
            }}
            onMouseEnter={e => { e.currentTarget.style.opacity = '0.8' }}
            onMouseLeave={e => { e.currentTarget.style.opacity = '1' }}
          >
            {micActive ? '⬤  MIC ON' : '⬤  MIC OFF'}
          </button>
        )}
      </div>
    </div>
  )
}
