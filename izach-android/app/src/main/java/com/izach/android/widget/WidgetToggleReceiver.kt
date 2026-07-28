package com.izach.android.widget

import android.appwidget.AppWidgetManager
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import com.izach.android.network.IZACHApi
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.launch

class WidgetToggleReceiver : BroadcastReceiver() {

    companion object {
        const val ACTION_TOGGLE_DND  = "com.izach.android.TOGGLE_DND"
        const val ACTION_TOGGLE_BUSY = "com.izach.android.TOGGLE_BUSY"
    }

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)

    override fun onReceive(context: Context, intent: Intent) {
        val api = IZACHApi(context)
        val prefs = context.getSharedPreferences("izach_prefs", Context.MODE_PRIVATE)

        // goAsync() keeps this receiver's process alive long enough for the
        // toggle call below to finish — without it Android can kill it right
        // after onReceive() returns, silently dropping the widget tap.
        val pendingResult = goAsync()
        when (intent.action) {
            ACTION_TOGGLE_DND -> {
                val dndActive = prefs.getBoolean("dnd_active", false)
                val action = if (dndActive) "off" else "on"
                scope.launch {
                    try {
                        val result = api.toggleDnd(action, "manual")
                        result.onSuccess { status ->
                            DndStatusWidget.pushState(
                                context,
                                status.active,
                                status.queueCount,
                                prefs.getBoolean("busy_active", false)
                            )
                        }
                    } catch (_: Exception) {
                    } finally {
                        pendingResult.finish()
                    }
                }
            }
            ACTION_TOGGLE_BUSY -> {
                val busyActive = prefs.getBoolean("busy_active", false)
                val action = if (busyActive) "off" else "on"
                scope.launch {
                    try {
                        val result = api.toggleBusy(action, if (action == "on") "Manual" else "")
                        result.onSuccess { status ->
                            DndStatusWidget.pushState(
                                context,
                                prefs.getBoolean("dnd_active", false),
                                prefs.getInt("dnd_queue_count", 0),
                                status.active
                            )
                        }
                    } catch (_: Exception) {
                    } finally {
                        pendingResult.finish()
                    }
                }
            }
            else -> pendingResult.finish()
        }
    }
}
