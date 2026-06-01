package com.izach.android.tile

class MutePcTileService : BaseTileService() {

    private var muted = false

    override fun onStartListening() {
        super.onStartListening()
        // Sync with backend volume state
        apiCall {
            api.getSystemStatus()
                .onSuccess {
                    // No direct mute field in SystemStatus — start inactive
                    setInactive(if (muted) "Muted" else "Tap to mute")
                }
                .onFailure { setUnavailable() }
        }
    }

    override fun onClick() {
        super.onClick()
        muted = !muted
        val cmd = if (muted) "mute" else "unmute"
        if (muted) setActive("Muted") else setInactive("Unmuted")

        apiCall {
            api.quickAction(cmd)
        }
    }
}
