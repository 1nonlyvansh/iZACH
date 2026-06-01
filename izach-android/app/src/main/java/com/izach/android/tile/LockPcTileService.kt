package com.izach.android.tile

import android.service.quicksettings.Tile

class LockPcTileService : BaseTileService() {

    override fun onStartListening() {
        super.onStartListening()
        // Lock is a one-shot action — always show as inactive/ready
        val t = qsTile ?: return
        t.state    = Tile.STATE_INACTIVE
        t.subtitle = "Tap to lock"
        t.updateTile()
    }

    override fun onClick() {
        super.onClick()
        val t = qsTile ?: return
        t.state    = Tile.STATE_ACTIVE
        t.subtitle = "Locking…"
        t.updateTile()

        apiCall {
            api.pcPower("lock")
            // Reset tile after action
            val t2 = qsTile ?: return@apiCall
            t2.state    = Tile.STATE_INACTIVE
            t2.subtitle = "Locked"
            t2.updateTile()
        }
    }
}
