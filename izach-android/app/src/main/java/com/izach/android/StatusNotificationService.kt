package com.izach.android

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Intent
import android.os.IBinder
import androidx.core.app.NotificationCompat
import com.izach.android.network.IZACHApi
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch

/**
 * Ongoing foreground-service notification showing live PC connection state,
 * DND mode, Busy mode, and the PC's own Background Mode status. Polls
 * lightweight status routes on an interval rather than sharing MainActivity's
 * WebSocket, so the notification stays accurate even when the app itself
 * isn't in the foreground (as long as Android keeps this foreground service
 * alive, which it prioritizes over a plain background process).
 */
class StatusNotificationService : Service() {

    private lateinit var api: IZACHApi
    private val job = SupervisorJob()
    private val scope = CoroutineScope(Dispatchers.IO + job)

    private data class Snapshot(
        val paired: Boolean,
        val connected: Boolean,
        val pcName: String = "",
        val dndActive: Boolean = false,
        val dndReason: String = "",
        val busyActive: Boolean = false,
        val busyReason: String = "",
        val uiMode: String = "",
    )

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onCreate() {
        super.onCreate()
        api = IZACHApi(this)
        createNotificationChannel()
        // Must call startForeground synchronously and promptly — post a
        // "checking…" placeholder immediately, refine it once the first poll
        // (which needs network round-trips) actually completes.
        startForeground(NOTIF_ID, render(Snapshot(paired = api.pairingSecret().isNotBlank(), connected = false)))
        scope.launch {
            while (true) {
                refresh()
                delay(POLL_INTERVAL_MS)
            }
        }
    }

    private suspend fun refresh() {
        if (api.pairingSecret().isBlank()) {
            post(Snapshot(paired = false, connected = false))
            return
        }
        val verify = api.verifyPairing()
        if (verify.isFailure) {
            // Couldn't reach the PC at all — still paired, just offline right now.
            post(Snapshot(paired = true, connected = false))
            return
        }
        if (verify.getOrDefault(false) == false) {
            // PC answered and rejected the secret — genuinely not paired.
            post(Snapshot(paired = false, connected = false))
            return
        }
        val status = api.getSystemStatus().getOrNull()
        if (status == null) {
            post(Snapshot(paired = true, connected = false))
            return
        }
        val dnd = api.getDndStatus().getOrNull()
        val busy = api.getBusyStatus().getOrNull()
        val uiMode = api.getUiMode().getOrNull() ?: "normal"
        post(
            Snapshot(
                paired = true,
                connected = true,
                pcName = status.pcName,
                dndActive = dnd?.active ?: false,
                dndReason = dnd?.reason ?: "",
                busyActive = busy?.active ?: false,
                busyReason = busy?.reason ?: "",
                uiMode = uiMode,
            )
        )
    }

    private fun post(snapshot: Snapshot) {
        (getSystemService(NOTIFICATION_SERVICE) as NotificationManager).notify(NOTIF_ID, render(snapshot))
    }

    private fun render(s: Snapshot): Notification {
        val title = when {
            !s.paired -> "iZACH — Not Paired"
            s.connected -> "iZACH — Connected" + (if (s.pcName.isNotBlank()) " to ${s.pcName}" else "")
            else -> "iZACH — Disconnected"
        }
        val text = when {
            !s.paired -> "Scan the QR code in Settings to pair this device"
            !s.connected -> "Check the PC is on and on the same network"
            else -> {
                val dnd = if (s.dndActive) "On" + (s.dndReason.takeIf { it.isNotBlank() && it != "manual" }?.let { " ($it)" } ?: "") else "Off"
                val busy = if (s.busyActive) "On" + (s.busyReason.takeIf { it.isNotBlank() }?.let { " ($it)" } ?: "") else "Off"
                val mode = if (s.uiMode == "background") "Background" else "Normal"
                "DND: $dnd · Busy: $busy · PC Mode: $mode"
            }
        }

        val tapIntent = PendingIntent.getActivity(
            this, 0,
            Intent(this, MainActivity::class.java).setFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP),
            PendingIntent.FLAG_IMMUTABLE
        )
        val stopIntent = PendingIntent.getService(
            this, 0,
            Intent(this, StatusNotificationService::class.java).setAction(ACTION_STOP),
            PendingIntent.FLAG_IMMUTABLE
        )

        return NotificationCompat.Builder(this, CHANNEL_ID)
            .setSmallIcon(R.drawable.ic_bell)
            .setContentTitle(title)
            .setContentText(text)
            .setStyle(NotificationCompat.BigTextStyle().bigText(text))
            .setContentIntent(tapIntent)
            .addAction(0, "Stop", stopIntent)
            .setOngoing(true)
            .setSilent(true)
            .setPriority(NotificationCompat.PRIORITY_LOW)
            .build()
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (intent?.action == ACTION_STOP) {
            getSharedPreferences("izach_prefs", MODE_PRIVATE).edit()
                .putBoolean(PREF_ENABLED, false).apply()
            stopSelf()
        }
        return START_STICKY
    }

    override fun onDestroy() {
        super.onDestroy()
        job.cancel()
    }

    private fun createNotificationChannel() {
        val ch = NotificationChannel(CHANNEL_ID, "iZACH Status", NotificationManager.IMPORTANCE_LOW).apply {
            setShowBadge(false)
        }
        (getSystemService(NOTIFICATION_SERVICE) as NotificationManager).createNotificationChannel(ch)
    }

    companion object {
        const val ACTION_STOP = "com.izach.android.STATUS_STOP"
        const val PREF_ENABLED = "persistent_status_enabled"
        private const val CHANNEL_ID = "izach_status"
        private const val NOTIF_ID = 4001
        private const val POLL_INTERVAL_MS = 20_000L
    }
}
