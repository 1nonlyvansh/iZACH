package com.izach.android.tile

class BusyTileService : BaseTileService() {

    override fun onStartListening() {
        super.onStartListening()
        apiCall {
            api.getBusyStatus()
                .onSuccess { s ->
                    if (s.active) setActive("Busy ON")
                    else          setInactive("Tap to enable")
                }
                .onFailure { setUnavailable() }
        }
    }

    override fun onClick() {
        super.onClick()
        apiCall {
            val status = api.getBusyStatus().getOrNull()
            val action = if (status?.active == true) "off" else "on"
            api.toggleBusy(action, if (action == "on") "Manual" else "")
                .onSuccess { s ->
                    if (s.active) setActive("Busy ON")
                    else          setInactive("Busy OFF")
                }
                .onFailure { setUnavailable() }
        }
    }
}
