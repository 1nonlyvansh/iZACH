import React, { useState, useEffect } from 'react'
import TitleBar        from './components/TitleBar.jsx'
import LeftPanel       from './components/LeftPanel.jsx'
import NeuralOrb       from './components/NeuralOrb.jsx'
import ChatPanel       from './components/ChatPanel.jsx'
import RightPanel      from './components/RightPanel.jsx'
import InputBar        from './components/InputBar.jsx'
import StatusBar       from './components/StatusBar.jsx'
import SettingsPanel   from './components/SettingsPanel.jsx'
import CommandPalette  from './components/CommandPalette.jsx'
import { useIZACH }   from './hooks/useIZACH.js'

export default function App() {
  const {
    messages,
    inputText, setInputText,
    isLoading, isSpeaking, liveText,
    micActive, toggleMic,
    backendStatus, waStatus, mmaStatus, androidDevices,
    spotifyTrack,
    cpuUsage, ramUsage, gpuUsage, procCpu, procMem,
    memoryEntries, settings,
    addMemoryEntry, deleteMemoryEntry, saveSettings,
    notifications,
    faceState,
    whatsappQr,
    calendarEvents, setCalendarEvents,
    shellConfirm, setShellConfirm,
    shellOutput,  setShellOutput,
    activeAgent,
    dndActive, dndAlert, toggleDnd, dismissDndAlert, handleDndAlert, busyDndAlert,
    busyActive, busyReason, busyBriefing, toggleBusy, dismissBusyBriefing,
    chatBottomRef,
    send, stopSpeech,
  } = useIZACH()

  const [page,         setPage]         = useState('home')
  const [paletteOpen,  setPaletteOpen]  = useState(false)
  const [camVisible,   setCamVisible]   = useState(false)

  // Ctrl+K opens command palette
  useEffect(() => {
    const handler = (e) => {
      if ((e.ctrlKey || e.metaKey) && e.key === 'k') {
        e.preventDefault()
        setPaletteOpen(prev => !prev)
      }
      if (e.key === 'Escape') setPaletteOpen(false)
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [])

  return (
    <div className="flex flex-col h-screen select-none" style={{ background: 'var(--bg-deep)' }}>
      <TitleBar activePage={page} onNav={setPage} activeAgent={activeAgent} camVisible={camVisible} onToggleCam={() => setCamVisible(v => !v)} dndActive={dndActive} onToggleDnd={toggleDnd} busyActive={busyActive} busyReason={busyReason} onToggleBusy={toggleBusy} />

      <CommandPalette
        open={paletteOpen}
        onClose={() => setPaletteOpen(false)}
        onCommand={(cmd) => send(cmd)}
      />

      <div className="flex flex-1 overflow-hidden">
        {/* Left panel — self-manages its own width via collapse state */}
        <div style={{ flexShrink: 0, overflow: 'hidden' }}>
          <LeftPanel
            cpuUsage={cpuUsage} ramUsage={ramUsage} gpuUsage={gpuUsage}
            procCpu={procCpu} procMem={procMem} faceState={faceState}
            camVisible={camVisible}
          />
        </div>

        {/* Center */}
        <div
          className="flex-1 flex flex-col overflow-hidden"
          style={{ borderLeft: '1px solid #0d2a3a', borderRight: '1px solid #0d2a3a' }}
        >
          {page === 'home' && (
            <>
              <div style={{
                flexShrink: 0, display: 'flex', flexDirection: 'column',
                alignItems: 'center', justifyContent: 'center',
                background: 'linear-gradient(180deg, #050d1a 0%, #071020 100%)',
                borderBottom: '1px solid #0d2a3a', minHeight: 380,
              }}>
                <NeuralOrb
                  isSpeaking={isSpeaking || isLoading}
                  liveText={liveText}
                  micActive={micActive}
                  toggleMic={toggleMic}
                />
              </div>

              <div className="flex-1 overflow-hidden" style={{ background: 'var(--bg-panel)' }}>
                <ChatPanel messages={messages} chatBottomRef={chatBottomRef} />
              </div>

              <InputBar
                inputText={inputText}
                setInputText={setInputText}
                send={send}
                isLoading={isLoading}
                isSpeaking={isSpeaking}
                micActive={micActive}
                toggleMic={toggleMic}
                onStop={stopSpeech}
              />
            </>
          )}

          {page === 'settings' && (
            <div className="flex-1 overflow-hidden">
              <SettingsPanel
                memoryEntries={memoryEntries}
                settings={settings}
                onAddMemory={addMemoryEntry}
                onDeleteMemory={deleteMemoryEntry}
                onSaveSettings={saveSettings}
              />
            </div>
          )}
        </div>

        {/* Right panel — self-manages its own width via collapse state */}
        <div style={{ flexShrink: 0, overflow: 'hidden' }}>
          <RightPanel
            waStatus={waStatus}
            mmaStatus={mmaStatus}
            spotifyTrack={spotifyTrack}
            notifications={notifications}
            whatsappQr={whatsappQr}
            androidDevices={androidDevices}
            calendarEvents={calendarEvents}
            onCalendarUpdate={setCalendarEvents}
            shellConfirm={shellConfirm}
            setShellConfirm={setShellConfirm}
            shellOutput={shellOutput}
            setShellOutput={setShellOutput}
          />
        </div>
      </div>

      <StatusBar cpuUsage={cpuUsage} ramUsage={ramUsage} backendStatus={backendStatus} />

      {/* Busy mode top bar */}
      {busyActive && !dndActive && (
        <div style={{
          position: 'fixed', top: 36, left: 0, right: 0, zIndex: 3900,
          background: 'rgba(255,140,0,0.88)', color: '#fff',
          fontSize: 10, letterSpacing: '0.12em', textAlign: 'center',
          padding: '3px 8px', fontFamily: "'Share Tech Mono'",
          borderBottom: '1px solid rgba(255,180,50,0.5)',
        }}>
          🔶 BUSY MODE ACTIVE — WA AUTO-REPLY ON &nbsp;·&nbsp; {busyReason.toUpperCase()} &nbsp;·&nbsp;
          <span style={{ cursor: 'pointer', textDecoration: 'underline' }} onClick={() => toggleBusy()}>TURN OFF</span>
        </div>
      )}

      {/* Post-busy briefing popup */}
      {busyBriefing && (
        <div style={{
          position: 'fixed', bottom: 90, right: 18, zIndex: 5500,
          background: 'rgba(1,5,20,0.97)', border: '1px solid rgba(255,140,0,0.55)',
          borderRadius: 10, minWidth: 260, maxWidth: 340, padding: '14px 16px',
          fontFamily: "'Share Tech Mono'", fontSize: 11, color: '#f0d0a0',
          boxShadow: '0 4px 24px rgba(255,140,0,0.2)',
        }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
            <span style={{ color: '#ffaa30', fontSize: 12, letterSpacing: '0.1em' }}>
              🔶 BUSY SESSION COMPLETE
            </span>
            <span style={{ cursor: 'pointer', opacity: 0.6, fontSize: 14 }} onClick={dismissBusyBriefing}>✕</span>
          </div>
          <div style={{ marginBottom: 10, color: '#c8c0a0', lineHeight: 1.6 }}>
            <strong>{busyBriefing.duration_min} min</strong> busy session ended.<br />
            <strong>{busyBriefing.msg_count}</strong> message{busyBriefing.msg_count !== 1 ? 's' : ''} handled by iZACH.
          </div>
          {busyBriefing.messages?.length > 0 && (
            <div style={{ maxHeight: 120, overflowY: 'auto', marginBottom: 8 }}>
              {busyBriefing.messages.slice(0, 5).map((m, i) => (
                <div key={i} style={{ borderLeft: '2px solid rgba(255,140,0,0.4)', paddingLeft: 8, marginBottom: 4, fontSize: 10, color: '#b0a080' }}>
                  <strong>{m.sender}</strong>: {m.text?.slice(0, 60)}
                </div>
              ))}
            </div>
          )}
          <button onClick={dismissBusyBriefing} style={{
            width: '100%', padding: 6, borderRadius: 6,
            background: 'rgba(255,140,0,0.15)', border: '1px solid rgba(255,140,0,0.4)',
            color: '#ffaa30', fontSize: 9, cursor: 'pointer',
            letterSpacing: '0.1em', fontFamily: 'inherit',
          }}>GOT IT</button>
        </div>
      )}

      {/* DND top bar */}
      {dndActive && (
        <div style={{
          position: 'fixed', top: 36, left: 0, right: 0, zIndex: 4000,
          background: 'rgba(200,40,40,0.92)', color: '#fff',
          fontSize: 10, letterSpacing: '0.12em', textAlign: 'center',
          padding: '3px 8px', fontFamily: "'Share Tech Mono'",
          borderBottom: '1px solid rgba(255,100,100,0.5)',
        }}>
          ⛔ DO NOT DISTURB ACTIVE — MIC PAUSED &nbsp;·&nbsp;
          <span style={{ cursor: 'pointer', textDecoration: 'underline' }} onClick={toggleDnd}>TURN OFF</span>
        </div>
      )}

      {/* DND alert popup — normal or URGENT */}
      {dndAlert && (
        dndAlert.urgent ? (
          /* URGENT overlay — centered, full attention */
          <div style={{
            position: 'fixed', inset: 0, zIndex: 9999,
            background: 'rgba(180,10,10,0.15)',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            backdropFilter: 'blur(2px)',
          }}>
            <div style={{
              background: 'rgba(3,0,12,0.97)', border: '2px solid rgba(255,50,50,0.8)',
              borderRadius: 14, padding: '28px 32px', maxWidth: 420, width: '90%',
              fontFamily: "'Share Tech Mono'",
              boxShadow: '0 0 60px rgba(255,30,30,0.4)',
            }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 14 }}>
                <div>
                  <div style={{ color: '#ff3030', fontSize: 11, letterSpacing: '0.25em', marginBottom: 4 }}>🚨 URGENT MESSAGE</div>
                  <div style={{ color: '#ff8080', fontSize: 14, letterSpacing: '0.15em' }}>{dndAlert.from || 'Unknown'}</div>
                </div>
                <span style={{ cursor: 'pointer', color: 'rgba(255,80,80,0.5)', fontSize: 18 }} onClick={dismissDndAlert}>✕</span>
              </div>
              <div style={{
                color: '#f0d0d0', fontSize: 12, lineHeight: 1.6, marginBottom: 18,
                padding: '10px 12px', background: 'rgba(255,50,50,0.06)',
                borderRadius: 6, borderLeft: '3px solid rgba(255,50,50,0.4)',
              }}>{dndAlert.text}</div>
              <button onClick={dismissDndAlert} style={{
                width: '100%', padding: 8, borderRadius: 6,
                background: 'rgba(255,50,50,0.15)', border: '1px solid rgba(255,50,50,0.4)',
                color: '#ff8080', fontSize: 9, cursor: 'pointer',
                letterSpacing: '0.1em', fontFamily: 'inherit',
              }}>ACKNOWLEDGED</button>
            </div>
          </div>
        ) : (
          /* Normal DND alert — bottom-right */
          <div style={{
            position: 'fixed', bottom: 90, right: 18, zIndex: 5000,
            background: 'rgba(1,5,20,0.97)', border: '1px solid rgba(255,60,60,0.55)',
            borderRadius: 10, minWidth: 260, maxWidth: 320, padding: '14px 16px',
            fontFamily: "'Share Tech Mono'", fontSize: 11, color: '#e8b4b4',
            boxShadow: '0 4px 24px rgba(200,40,40,0.25)',
          }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
              <span style={{ color: '#ff6060', fontSize: 12, letterSpacing: '0.1em' }}>
                {dndAlert.type === 'whatsapp_message' ? '📱' : dndAlert.type === 'phone_call' ? '📞' : '⛔'}
                {' '}DND — {(dndAlert.type || 'alert').replace('_', ' ').toUpperCase()}
              </span>
              <span style={{ cursor: 'pointer', opacity: 0.6, fontSize: 14 }} onClick={dismissDndAlert}>✕</span>
            </div>
            <div style={{ marginBottom: 12, color: '#c8c8e0', lineHeight: 1.5 }}>
              <strong>{dndAlert.from || 'Unknown'}</strong><br />
              {dndAlert.text ? (dndAlert.text.length > 80 ? dndAlert.text.slice(0, 80) + '…' : dndAlert.text) : ''}
            </div>
            <div style={{ display: 'flex', gap: 8 }}>
              <button onClick={() => handleDndAlert(dndAlert.id)} style={{
                flex: 1, padding: 6, borderRadius: 6,
                background: 'rgba(0,148,255,0.2)', border: '1px solid rgba(0,148,255,0.5)',
                color: '#6ab0e0', fontSize: 10, cursor: 'pointer',
                letterSpacing: '0.1em', fontFamily: 'inherit',
              }}>HANDLE</button>
              <button onClick={() => busyDndAlert(dndAlert.id)} style={{
                flex: 1, padding: 6, borderRadius: 6,
                background: 'rgba(200,40,40,0.2)', border: '1px solid rgba(200,40,40,0.5)',
                color: '#ff8080', fontSize: 10, cursor: 'pointer',
                letterSpacing: '0.1em', fontFamily: 'inherit',
              }}>I'M BUSY</button>
              <button onClick={dismissDndAlert} style={{
                flex: 1, padding: 6, borderRadius: 6,
                background: 'rgba(255,255,255,0.05)', border: '1px solid rgba(255,255,255,0.15)',
                color: '#888', fontSize: 10, cursor: 'pointer',
                letterSpacing: '0.1em', fontFamily: 'inherit',
              }}>DISMISS</button>
            </div>
          </div>
        )
      )}
    </div>
  )
}
