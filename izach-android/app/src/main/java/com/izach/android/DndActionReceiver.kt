package com.izach.android

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.os.Handler
import android.os.Looper
import android.widget.Toast
import com.izach.android.network.IZACHApi
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch

class DndActionReceiver : BroadcastReceiver() {

    companion object {
        const val ACTION_HANDLE = "com.izach.android.DND_HANDLE"
        const val ACTION_BUSY   = "com.izach.android.DND_BUSY"
        const val EXTRA_INDEX   = "dnd_index"
    }

    override fun onReceive(context: Context, intent: Intent) {
        val pending  = goAsync()
        val index    = intent.getIntExtra(EXTRA_INDEX, 0)
        val isHandle = intent.action == ACTION_HANDLE
        val api      = IZACHApi(context)
        val main     = Handler(Looper.getMainLooper())

        CoroutineScope(Dispatchers.IO).launch {
            try {
                if (isHandle) api.dndHandle(index) else api.dndBusy(index)
                main.post {
                    Toast.makeText(
                        context,
                        if (isHandle) "✅ Handling message…" else "📵 Busy reply sent",
                        Toast.LENGTH_SHORT
                    ).show()
                }
            } catch (e: Exception) {
                main.post {
                    Toast.makeText(context, "Action failed: ${e.message}", Toast.LENGTH_SHORT).show()
                }
            } finally {
                pending.finish()
            }
        }
    }
}
