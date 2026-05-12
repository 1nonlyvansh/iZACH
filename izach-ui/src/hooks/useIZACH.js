import { useState, useEffect, useRef, useCallback } from 'react'

const BASE  = 'http://localhost:5050'
const WA    = 'http://localhost:3000'
const MMA   = 'http://localhost:6060'

async function safeFetch(url, opts = {}, ms = 4000) {
  const ctrl  = new AbortController()
  const timer = setTimeout(() => ctrl.abort(), ms)
  try {
    return await fetch(url, { ...opts, signal: ctrl.signal })
  } finally {
    clearTimeout(timer)
  }
}

function nowStr() {
  return new Date().toLocaleTimeString('en-IN', {
    hour: '2-digit', minute: '2-digit', hour12: false,
  })
}

export function useIZACH() {
  const [messages, setMessages] = useState([
    { id: 1, sender: 'iZACH', text: 'Neural interface online. All systems nominal.', ts: nowStr(), type: 'system' },
  ])
  const [inputText, setInputText]   = useState('')
  const [isLoading, setIsLoading]   = useState(false)
  const [isSpeaking, setIsSpeaking] = useState(false)
  const [micActive, setMicActive]   = useState(true)
  const [liveText, setLiveText]     = useState('')

  // statuses
  const [backendStatus, setBackendStatus] = useState('unknown')
  const [waStatus, setWaStatus]           = useState('offline')
  const [mmaStatus, setMmaStatus]         = useState('offline')
  const [androidDevices, setAndroidDevices] = useState([])

  // system stats
  const [cpuUsage, setCpuUsage]   = useState(0)
  const [ramUsage, setRamUsage]   = useState(0)
  const [gpuUsage, setGpuUsage]   = useState(0)
  const [procCpu,  setProcCpu]    = useState(0)
  const [procMem,  setProcMem]    = useState(0)

  // spotify
  const [spotifyTrack, setSpotifyTrack] = useState({
    playing: false, title: '—', artist: '—', device: '—',
    albumArt: '', progress: 0, duration: 0, volume: 0,
  })

  // settings & memory
  const [memoryEntries, setMemoryEntries] = useState([])
  const [settings,      setSettings]      = useState({})
  const [notifications, setNotifications] = useState([])

  // face verification overlay state
  const [faceState, setFaceState] = useState('idle')

  // whatsapp QR code — raw string, cleared when connected
  const [whatsappQr, setWhatsappQr] = useState(null)

  // calendar events — next 3 days
  const [calendarEvents, setCalendarEvents] = useState([])

  const chatBottomRef = useRef(null)
  const wsRef         = useRef(null)
  const liveTimer     = useRef(null)

  // ── WebSocket — voice chat + live text + notifications ────
  useEffect(() => {
    let cancelled = false
    let reconnectTimer = null

    function connect() {
      if (cancelled) return
      try {
        const ws = new WebSocket('ws://127.0.0.1:5051')
        wsRef.current = ws

        ws.onopen = () => {
          console.log('[WS] Connected to iZACH')
        }

        ws.onmessage = (e) => {
          try {
            const data = JSON.parse(e.data)

            if (data.type === 'chat') {
              setMessages(prev => [
                ...prev,
                {
                  id: Date.now() + Math.random(),
                  sender: data.sender,
                  text: data.text,
                  ts: data.ts || nowStr(),
                  type: 'normal'
                }
              ])
            }
            else if (data.type === 'live_text') {
              setLiveText(data.text || '')
              setIsSpeaking(!!data.text)
            }
            else if (data.type === 'notification' && data.source) {
              // Only accept notifications that have an explicit source tag
              // This prevents iZACH's own chat responses leaking into this panel
              setNotifications(prev => [
                ...prev.slice(-9),
                { text: data.text, ts: data.ts || nowStr(), source: data.source }
              ])
            }
            else if (data.type === 'face_verify') {
              setFaceState(data.state || 'idle')
              if (data.state === 'success' || data.state === 'failed') {
                setTimeout(() => setFaceState('idle'), 3500)
              }
            }
            else if (data.type === 'whatsapp_qr') {
              setWhatsappQr(data.qr || null)
            }
            else if (data.type === 'device_connected') {
              setAndroidDevices(prev => [...prev.filter(d => d !== data.device_name), data.device_name])
            }
            else if (data.type === 'device_disconnected') {
              setAndroidDevices(prev => prev.filter(d => d !== data.device_name))
            }
          } catch {}
        }

        ws.onclose = () => {
          if (!cancelled) {
            console.log('[WS] Disconnected, reconnecting...')
            reconnectTimer = setTimeout(connect, 3000)
          }
        }

        ws.onerror = () => {
          ws.close()
        }
      } catch (err) {
        console.error('[WS CONNECT ERROR]', err)
      }
    }

    connect()
    return () => {
      cancelled = true
      if (reconnectTimer) clearTimeout(reconnectTimer)
      wsRef.current?.close()
    }
  }, [])

  // ── auto-scroll ───────────────────────────────────────────
  useEffect(() => {
    chatBottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  // ── add message ───────────────────────────────────────────
  const addMessage = useCallback((sender, text, type = 'normal') => {
    setMessages(prev => [
      ...prev,
      { id: Date.now() + Math.random(), sender, text, ts: nowStr(), type },
    ])
  }, [])

  // ── poll backend health ───────────────────────────────────
  useEffect(() => {
    let mounted = true

    async function pollAll() {
      try {
        const r = await safeFetch(`${BASE}/health`, {}, 3000)
        if (mounted) setBackendStatus(r.ok ? 'online' : 'offline')
      } catch { if (mounted) setBackendStatus('offline') }

      try {
        const r = await safeFetch(`${WA}/health`, {}, 2500)
        if (r.ok) {
          const d = await r.json().catch(() => ({}))
          const connected = d.status === 'connected'
          if (mounted) {
            setWaStatus(connected ? 'online' : 'offline')
            if (connected) setWhatsappQr(null)
          }
        } else {
          if (mounted) setWaStatus('offline')
        }
      } catch { if (mounted) setWaStatus('offline') }

      try {
        const r = await safeFetch(`${MMA}/health`, {}, 2500)
        if (r.ok) {
          const d = await r.json().catch(() => ({}))
          if (mounted) setMmaStatus(d.status === 'online' ? 'online' : 'offline')
        } else {
          if (mounted) setMmaStatus('offline')
        }
      } catch { if (mounted) setMmaStatus('offline') }
    }

    pollAll()
    const t = setInterval(pollAll, 15000)
    return () => { mounted = false; clearInterval(t) }
  }, [])

  // ── poll system stats ─────────────────────────────────────
  useEffect(() => {
    let mounted = true

    async function pollStats() {
      try {
        const r = await safeFetch(`${BASE}/status`, {}, 4000)
        if (!r.ok) return
        const d = await r.json()
        if (!mounted || !d.ok) return
        setCpuUsage(d.cpu      ?? 0)
        setRamUsage(d.ram      ?? 0)
        setGpuUsage(d.gpu      ?? 0)
        setProcCpu(d.proc_cpu  ?? 0)
        setProcMem(d.proc_mem  ?? 0)
        if (d.android_devices) setAndroidDevices(d.android_devices)
      } catch {}
    }

    const first = setTimeout(pollStats, 1000)
    const t = setInterval(pollStats, 4000)
    return () => { mounted = false; clearTimeout(first); clearInterval(t) }
  }, [])

  // ── poll Calendar (every 5 min) ───────────────────────────
  useEffect(() => {
    let mounted = true
    async function pollCalendar() {
      try {
        const r = await safeFetch(`${BASE}/calendar/events`, {}, 8000)
        if (!r.ok) return
        const d = await r.json()
        if (mounted && d.ok) setCalendarEvents(d.events || [])
      } catch {}
    }
    pollCalendar()
    const t = setInterval(pollCalendar, 5 * 60 * 1000)
    return () => { mounted = false; clearInterval(t) }
  }, [])

  // ── poll Spotify ──────────────────────────────────────────
  useEffect(() => {
    let mounted = true

    async function pollSpotify() {
      try {
        const r = await safeFetch(`${BASE}/spotify`, {}, 4000)
        if (!r.ok) return
        const d = await r.json()
        if (!mounted || !d.ok) return
        setSpotifyTrack({
          playing:  d.playing,
          title:    d.title    || '—',
          artist:   d.artist   || '—',
          device:   d.device   || '—',
          albumArt: d.album_art || '',
          progress: d.progress  || 0,
          duration: d.duration  || 0,
          volume:   d.volume    || 0,
          shuffle:  d.shuffle   || false,
          repeat:   d.repeat    || 'off',
        })
      } catch {}
    }

    const t = setInterval(pollSpotify, 5000)
    pollSpotify()
    return () => { mounted = false; clearInterval(t) }
  }, [])

  // ── load memory & settings ────────────────────────────────
  const loadMemory = useCallback(async () => {
    try {
      const r = await safeFetch(`${BASE}/memory`, {}, 4000)
      const d = await r.json()
      if (d.ok) setMemoryEntries(d.data || [])
    } catch {}
  }, [])

  const loadSettings = useCallback(async () => {
    try {
      const r = await safeFetch(`${BASE}/settings`, {}, 4000)
      const d = await r.json()
      if (d.ok) setSettings(d.settings || {})
    } catch {}
  }, [])

  useEffect(() => {
    loadMemory()
    loadSettings()
  }, [loadMemory, loadSettings])

  const addMemoryEntry = useCallback(async (key, value) => {
    try {
      await safeFetch(`${BASE}/memory`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ key, value }),
      }, 5000)
      loadMemory()
    } catch {}
  }, [loadMemory])

  const deleteMemoryEntry = useCallback(async (key) => {
    try {
      await safeFetch(`${BASE}/memory/${encodeURIComponent(key)}`, { method: 'DELETE' }, 5000)
      loadMemory()
    } catch {}
  }, [loadMemory])

  const saveSettings = useCallback(async (newSettings) => {
    try {
      await safeFetch(`${BASE}/settings`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(newSettings),
      }, 5000)
      loadSettings()
    } catch {}
  }, [loadSettings])

  // ── live word-by-word text ────────────────────────────────
  // function startLiveTyping(text) {
  //   if (!text) return
  //   const words = text.split(' ')
  //   let i = 0
  //   setLiveText('')
  //   clearInterval(liveTimer.current)
  //   liveTimer.current = setInterval(() => {
  //     i++
  //     setLiveText(words.slice(0, i).join(' '))
  //     if (i >= words.length) clearInterval(liveTimer.current)
  //   }, 75)
  // }

  // function clearLiveText() {
  //   clearInterval(liveTimer.current)
  //   setLiveText('')
  // }

  useEffect(() => () => clearInterval(liveTimer.current), [])

  // ── SEND ──────────────────────────────────────────────────
  const send = useCallback(async (text) => {
    const trimmed = text.trim()
    if (!trimmed || isLoading) return

    addMessage('YOU', trimmed)
    setInputText('')
    setIsLoading(true)

    const thinkingId = Date.now()
    setMessages(prev => [
      ...prev,
      { id: thinkingId, sender: 'iZACH', text: '...', ts: nowStr(), type: 'thinking' },
    ])

    try {
      const res = await safeFetch(
        `${BASE}/command`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
          body: JSON.stringify({ text: trimmed, source: 'react_ui' }),
        },
        20000
      )

      setMessages(prev => prev.filter(m => m.id !== thinkingId))

      if (!res.ok) {
        const err = await res.json().catch(() => ({}))
        addMessage('iZACH', err.error || `Backend returned ${res.status}`, 'error')
        return
      }

      const data = await res.json()

      if (data.ok && data.response) {
        // startLiveTyping(data.response)
        addMessage('iZACH', data.response)
        // setTimeout(() => {
        //   clearLiveText()
        //   setIsSpeaking(false)
        // }, data.response.split(' ').length * 80 + 600)
      } else if (data.error) {
        addMessage('iZACH', data.error, 'error')
      } else {
        addMessage('iZACH', 'Command processed.', 'system')
      }
    } catch (err) {
      setMessages(prev => prev.filter(m => m.id !== thinkingId))
      if (err.name === 'AbortError') {
        addMessage('iZACH', 'Request timed out.', 'error')
      } else {
        addMessage('iZACH',
          backendStatus === 'offline'
            ? 'Backend offline — run python main.py'
            : `Connection error: ${err.message}`,
          'error'
        )
      }
    } finally {
      setIsLoading(false)
    }
  }, [isLoading, addMessage, backendStatus])

  // ── Stop speech ───────────────────────────────────────────
  const stopSpeech = useCallback(async () => {
    setLiveText('')
    setIsSpeaking(false)
    try {
      await safeFetch(`${BASE}/stop`, { method: 'POST' }, 3000)
    } catch {}
  }, [])

  // ── Mic toggle ────────────────────────────────────────────
  const toggleMic = useCallback(async () => {
    const newState = !micActive
    setMicActive(newState)
    try {
      await safeFetch(`${BASE}/mic`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ active: newState }),
      }, 3000)
    } catch {}
  }, [micActive])

  return {
    messages, addMessage,
    inputText, setInputText,
    isLoading, isSpeaking, liveText,
    micActive, toggleMic,
    backendStatus, waStatus, mmaStatus, androidDevices,
    cpuUsage, ramUsage, gpuUsage, procCpu, procMem,
    spotifyTrack,
    memoryEntries, settings,
    addMemoryEntry, deleteMemoryEntry, saveSettings, loadMemory,
    notifications,
    faceState,
    whatsappQr,
    calendarEvents, setCalendarEvents,
    chatBottomRef,
    send, stopSpeech,
  }
}