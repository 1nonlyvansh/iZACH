package com.izach.android.tile

import android.service.quicksettings.Tile
import android.service.quicksettings.TileService
import com.izach.android.network.IZACHApi
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.launch

/**
 * Base for all iZACH Quick Settings tiles.
 * Provides a coroutine scope tied to tile lifecycle and a shared IZACHApi instance.
 */
abstract class BaseTileService : TileService() {

    protected val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    protected lateinit var api: IZACHApi

    override fun onCreate() {
        super.onCreate()
        api = IZACHApi(this)
    }

    override fun onDestroy() {
        scope.cancel()
        super.onDestroy()
    }

    /** Set tile to ACTIVE (on) state with optional subtitle. */
    protected fun setActive(subtitle: String? = null) {
        val t = qsTile ?: return
        t.state    = Tile.STATE_ACTIVE
        t.subtitle = subtitle
        t.updateTile()
    }

    /** Set tile to INACTIVE (off) state. */
    protected fun setInactive(subtitle: String? = null) {
        val t = qsTile ?: return
        t.state    = Tile.STATE_INACTIVE
        t.subtitle = subtitle
        t.updateTile()
    }

    /** Set tile to UNAVAILABLE state (e.g. backend offline). */
    protected fun setUnavailable() {
        val t = qsTile ?: return
        t.state    = Tile.STATE_UNAVAILABLE
        t.subtitle = "Offline"
        t.updateTile()
    }

    /** Run a block in IO coroutine; show unavailable if it throws. */
    protected fun apiCall(block: suspend () -> Unit) {
        scope.launch {
            try { block() }
            catch (e: Exception) { setUnavailable() }
        }
    }
}
