package com.izach.android.tile

import kotlinx.coroutines.launch

class DndTileService : BaseTileService() {

    override fun onStartListening() {
        super.onStartListening()
        // Sync tile state with backend
        apiCall {
            api.getDndStatus()
                .onSuccess { s ->
                    if (s.active) setActive("DND ON")
                    else          setInactive("Tap to enable")
                }
                .onFailure { setUnavailable() }
        }
    }

    override fun onClick() {
        super.onClick()
        apiCall {
            val status = api.getDndStatus().getOrNull()
            val action = if (status?.active == true) "off" else "on"
            api.toggleDnd(action, "manual")
                .onSuccess { s ->
                    if (s.active) setActive("DND ON")
                    else          setInactive("DND OFF")
                }
                .onFailure { setUnavailable() }
        }
    }
}
