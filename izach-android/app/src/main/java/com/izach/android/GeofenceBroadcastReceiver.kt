package com.izach.android

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import com.google.android.gms.location.Geofence
import com.google.android.gms.location.GeofencingEvent
import com.izach.android.network.IZACHApi
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch

/** Fires on ENTER/EXIT of any registered geofence, even with the app killed. */
class GeofenceBroadcastReceiver : BroadcastReceiver() {

    override fun onReceive(context: Context, intent: Intent) {
        val event = GeofencingEvent.fromIntent(intent) ?: return
        if (event.hasError()) return

        val transition = event.geofenceTransition
        if (transition != Geofence.GEOFENCE_TRANSITION_ENTER && transition != Geofence.GEOFENCE_TRANSITION_EXIT) return

        val triggered = event.triggeringGeofences ?: return
        val api = IZACHApi(context)
        val locations = api.getGeofences()

        for (g in triggered) {
            val loc = locations.find { it.id == g.requestId } ?: continue
            val command = if (transition == Geofence.GEOFENCE_TRANSITION_ENTER) loc.arriveCommand else loc.leaveCommand
            if (command.isBlank()) continue
            CoroutineScope(Dispatchers.IO).launch {
                api.sendCommand(command)
            }
        }
    }
}
