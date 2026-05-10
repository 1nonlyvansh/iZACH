import React, { useState } from 'react'
import TitleBar      from './components/TitleBar.jsx'
import LeftPanel     from './components/LeftPanel.jsx'
import NeuralOrb     from './components/NeuralOrb.jsx'
import ChatPanel     from './components/ChatPanel.jsx'
import RightPanel    from './components/RightPanel.jsx'
import InputBar      from './components/InputBar.jsx'
import StatusBar     from './components/StatusBar.jsx'
import SettingsPanel from './components/SettingsPanel.jsx'
import { useIZACH }  from './hooks/useIZACH.js'

export default function App() {
  const {
    messages,
    inputText, setInputText,
    isLoading, isSpeaking, liveText,
    micActive, toggleMic,
    backendStatus, waStatus, mmaStatus,
    spotifyTrack,
    cpuUsage, ramUsage, gpuUsage, procCpu, procMem,
    memoryEntries, settings,
    addMemoryEntry, deleteMemoryEntry, saveSettings,
    notifications,
    faceState,
    whatsappQr,
    chatBottomRef,
    send, stopSpeech,
  } = useIZACH()

  // Active page: 'home' | 'settings'
  const [page, setPage] = useState('home')

  return (
    <div className="flex flex-col h-screen select-none" style={{ background: 'var(--bg-deep)' }}>
      <TitleBar activePage={page} onNav={setPage} />

      <div className="flex flex-1 overflow-hidden">
        {/* Left panel — always visible */}
        <div style={{ width: 240, minWidth: 240, flexShrink: 0, overflow: 'hidden' }}>
          <LeftPanel cpuUsage={cpuUsage} ramUsage={ramUsage} gpuUsage={gpuUsage} procCpu={procCpu} procMem={procMem} faceState={faceState} />
        </div>

        {/* Center — switches between Home and Settings */}
        <div className="flex-1 flex flex-col overflow-hidden"
          style={{ borderLeft: '1px solid #0d2a3a', borderRight: '1px solid #0d2a3a' }}>

          {page === 'home' && (
            <>
              {/* Neural orb */}
              <div style={{
                flexShrink: 0, display: 'flex', flexDirection: 'column',
                alignItems: 'center', justifyContent: 'center',
                background: 'linear-gradient(180deg, #050d1a 0%, #071020 100%)',
                borderBottom: '1px solid #0d2a3a', minHeight: 380,
              }}>
                <NeuralOrb isSpeaking={isSpeaking || isLoading} liveText={liveText} micActive={micActive} toggleMic={toggleMic} />
              </div>

              {/* Chat */}
              <div className="flex-1 overflow-hidden" style={{ background: 'var(--bg-panel)' }}>
                <ChatPanel messages={messages} chatBottomRef={chatBottomRef} />
              </div>

              {/* Input */}
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

        {/* Right panel — always visible */}
        <div style={{ width: 220, minWidth: 220, flexShrink: 0, overflow: 'hidden' }}>
          <RightPanel
            waStatus={waStatus}
            mmaStatus={mmaStatus}
            spotifyTrack={spotifyTrack}
            notifications={notifications}
            whatsappQr={whatsappQr}
          />
        </div>
      </div>

      <StatusBar cpuUsage={cpuUsage} ramUsage={ramUsage} backendStatus={backendStatus} />
    </div>
  )
}