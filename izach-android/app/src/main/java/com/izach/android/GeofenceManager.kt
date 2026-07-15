package com.izach.android

import android.Manifest
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import androidx.core.content.ContextCompat
import com.google.android.gms.location.Geofence
import com.google.android.gms.location.GeofencingRequest
import com.google.android.gms.location.LocationServices
import com.izach.android.model.GeofenceLocation

/** Re-registers every enabled saved location with Play Services' geofencing API. */
object GeofenceManager {

    private fun pendingIntent(context: Context): PendingIntent {
        val intent = Intent(context, GeofenceBroadcastReceiver::class.java)
        return PendingIntent.getBroadcast(
            context, 0, intent,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_MUTABLE
        )
    }

    fun registerAll(context: Context, locations: List<GeofenceLocation>) {
        val client = LocationServices.getGeofencingClient(context)
        val pi = pendingIntent(context)

        client.removeGeofences(pi).addOnCompleteListener {
            val enabled = locations.filter { it.enabled && it.radius > 0 }
            if (enabled.isEmpty()) return@addOnCompleteListener

            if (ContextCompat.checkSelfPermission(context, Manifest.permission.ACCESS_FINE_LOCATION)
                != PackageManager.PERMISSION_GRANTED
            ) return@addOnCompleteListener

            val geofences = enabled.map { loc ->
                Geofence.Builder()
                    .setRequestId(loc.id)
                    .setCircularRegion(loc.lat, loc.lng, loc.radius)
                    .setExpirationDuration(Geofence.NEVER_EXPIRE)
                    .setTransitionTypes(Geofence.GEOFENCE_TRANSITION_ENTER or Geofence.GEOFENCE_TRANSITION_EXIT)
                    .build()
            }
            val request = GeofencingRequest.Builder()
                .setInitialTrigger(GeofencingRequest.INITIAL_TRIGGER_ENTER)
                .addGeofences(geofences)
                .build()
            client.addGeofences(request, pi)
        }
    }
}
