package com.izach.android

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import com.izach.android.network.IZACHApi

/** Play Services clears all registered geofences on reboot — re-register on boot. */
class BootReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        if (intent.action != Intent.ACTION_BOOT_COMPLETED) return
        val api = IZACHApi(context)
        val locations = api.getGeofences()
        if (locations.isNotEmpty()) {
            GeofenceManager.registerAll(context, locations)
        }
    }
}
