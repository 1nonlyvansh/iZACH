package com.izach.android

import android.Manifest
import android.app.NotificationChannel
import android.app.NotificationManager
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
import androidx.core.app.NotificationCompat
import androidx.core.content.ContextCompat
import com.google.firebase.messaging.FirebaseMessagingService
import com.google.firebase.messaging.RemoteMessage
import com.izach.android.network.IZACHApi
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch

/**
 * Fallback delivery path for DND/handoff/reminder alerts when the app is
 * killed and the WebSocket connection (the primary channel) isn't there to
 * receive them. Inert until app/google-services.json is replaced with a real
 * Firebase project — see build.gradle.kts.
 */
class FcmService : FirebaseMessagingService() {

    override fun onNewToken(token: String) {
        super.onNewToken(token)
        val api = IZACHApi(this)
        CoroutineScope(Dispatchers.IO).launch {
            api.registerFcmToken(token)
        }
    }

    override fun onMessageReceived(message: RemoteMessage) {
        super.onMessageReceived(message)
        val data = message.data
        val title = message.notification?.title ?: data["title"] ?: "iZACH"
        val body = message.notification?.body ?: data["body"] ?: ""
        val category = data["category"] ?: "system"
        showPushNotification(title, body, category)
    }

    // FCM can deliver a message before MainActivity has ever run (fresh
    // install, or the app killed since boot), so the notification channels
    // it normally creates may not exist yet — create them here too;
    // createNotificationChannel() is a no-op if the channel already exists.
    private fun ensureChannel(id: String, name: String, importance: Int) {
        val nm = getSystemService(NOTIFICATION_SERVICE) as NotificationManager
        nm.createNotificationChannel(NotificationChannel(id, name, importance))
    }

    private fun showPushNotification(title: String, body: String, category: String) {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU &&
            ContextCompat.checkSelfPermission(this, Manifest.permission.POST_NOTIFICATIONS)
            != PackageManager.PERMISSION_GRANTED) return

        val tapIntent = Intent(this, MainActivity::class.java).apply {
            flags = Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP
        }
        val tapPi = android.app.PendingIntent.getActivity(
            this, 0, tapIntent,
            android.app.PendingIntent.FLAG_UPDATE_CURRENT or android.app.PendingIntent.FLAG_IMMUTABLE
        )
        val channel = when (category) {
            "dnd_alert" -> "izach_dnd_alerts".also { ensureChannel(it, "iZACH DND Alerts", NotificationManager.IMPORTANCE_HIGH) }
            "reminder" -> "izach_reminders".also { ensureChannel(it, "iZACH Reminders", NotificationManager.IMPORTANCE_HIGH) }
            else -> "izach_pc_events".also { ensureChannel(it, "iZACH PC Events", NotificationManager.IMPORTANCE_DEFAULT) }
        }
        val notif = NotificationCompat.Builder(this, channel)
            .setSmallIcon(R.drawable.ic_bell)
            .setContentTitle(title)
            .setContentText(body)
            .setPriority(NotificationCompat.PRIORITY_HIGH)
            .setAutoCancel(true)
            .setContentIntent(tapPi)
            .build()
        (getSystemService(NOTIFICATION_SERVICE) as NotificationManager)
            .notify(System.currentTimeMillis().toInt(), notif)
    }
}
