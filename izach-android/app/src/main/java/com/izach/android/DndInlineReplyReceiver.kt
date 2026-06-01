package com.izach.android

import android.app.NotificationManager
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.os.Handler
import android.os.Looper
import android.widget.Toast
import androidx.core.app.RemoteInput
import com.izach.android.network.IZACHApi
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch

class DndInlineReplyReceiver : BroadcastReceiver() {

    companion object {
        const val ACTION_INLINE_REPLY  = "com.izach.android.DND_INLINE_REPLY"
        const val EXTRA_REPLY_NUMBER   = "dnd_reply_number"
        const val EXTRA_REPLY_NAME     = "dnd_reply_name"
        const val EXTRA_NOTIF_ID       = "dnd_notif_id"
        const val KEY_REPLY_TEXT       = "dnd_reply_text"
    }

    override fun onReceive(context: Context, intent: Intent) {
        val pending = goAsync()

        // Extract inline reply text from RemoteInput
        val replyBundle = RemoteInput.getResultsFromIntent(intent)
        val replyText   = replyBundle?.getCharSequence(KEY_REPLY_TEXT)?.toString()?.trim()
        if (replyText.isNullOrEmpty()) {
            pending.finish()
            return
        }

        val number  = intent.getStringExtra(EXTRA_REPLY_NUMBER) ?: ""
        val name    = intent.getStringExtra(EXTRA_REPLY_NAME)   ?: ""
        val notifId = intent.getIntExtra(EXTRA_NOTIF_ID, -1)
        val api     = IZACHApi(context)
        val main    = Handler(Looper.getMainLooper())

        CoroutineScope(Dispatchers.IO).launch {
            try {
                api.waSendMessage(number, replyText, name)
                    .onSuccess {
                        // Dismiss the notification
                        if (notifId >= 0) {
                            val nm = context.getSystemService(Context.NOTIFICATION_SERVICE)
                                     as NotificationManager
                            nm.cancel(notifId)
                        }
                        main.post {
                            Toast.makeText(context, "✅ Reply sent to $name", Toast.LENGTH_SHORT).show()
                        }
                    }
                    .onFailure { err ->
                        main.post {
                            Toast.makeText(context, "❌ Reply failed: ${err.message}", Toast.LENGTH_SHORT).show()
                        }
                    }
            } catch (e: Exception) {
                main.post {
                    Toast.makeText(context, "❌ Send error: ${e.message}", Toast.LENGTH_SHORT).show()
                }
            } finally {
                pending.finish()
            }
        }
    }
}
