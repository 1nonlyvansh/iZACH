package com.izach.android.widget

import android.app.PendingIntent
import android.appwidget.AppWidgetManager
import android.appwidget.AppWidgetProvider
import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.widget.RemoteViews
import com.google.gson.JsonObject
import com.google.gson.Gson
import com.izach.android.R
import com.izach.android.SystemDashboardActivity
import okhttp3.OkHttpClient
import okhttp3.Request
import java.util.concurrent.TimeUnit

class PCStatusWidget : AppWidgetProvider() {

    override fun onUpdate(context: Context, manager: AppWidgetManager, ids: IntArray) {
        for (id in ids) {
            val pending = goAsync()
            Thread {
                try { fetchAndUpdate(context, manager, id) }
                finally { pending.finish() }
            }.start()
        }
    }

    override fun onReceive(context: Context, intent: Intent) {
        super.onReceive(context, intent)
        if (intent.action == ACTION_REFRESH) {
            val manager = AppWidgetManager.getInstance(context)
            val ids = manager.getAppWidgetIds(ComponentName(context, PCStatusWidget::class.java))
            onUpdate(context, manager, ids)
        }
    }

    companion object {
        const val ACTION_REFRESH = "com.izach.android.WIDGET_REFRESH_STATUS"

        fun fetchAndUpdate(context: Context, manager: AppWidgetManager, id: Int) {
            val prefs = context.getSharedPreferences("izach_prefs", Context.MODE_PRIVATE)
            val baseUrl = prefs.getString("backend_url", "http://192.168.1.100:5050") ?: "http://192.168.1.100:5050"

            val views = RemoteViews(context.packageName, R.layout.widget_pc_status)

            val openIntent = PendingIntent.getActivity(
                context, 0,
                Intent(context, SystemDashboardActivity::class.java),
                PendingIntent.FLAG_IMMUTABLE
            )
            views.setOnClickPendingIntent(R.id.widgetRoot, openIntent)

            val refreshIntent = PendingIntent.getBroadcast(
                context, 0,
                Intent(context, PCStatusWidget::class.java).setAction(ACTION_REFRESH),
                PendingIntent.FLAG_IMMUTABLE
            )
            views.setOnClickPendingIntent(R.id.widgetRefresh, refreshIntent)

            try {
                val client = OkHttpClient.Builder()
                    .connectTimeout(5, TimeUnit.SECONDS)
                    .readTimeout(5, TimeUnit.SECONDS)
                    .build()
                val resp = client.newCall(Request.Builder().url("$baseUrl/status").build()).execute()
                val obj = Gson().fromJson(resp.body?.string() ?: "{}", JsonObject::class.java)

                val cpu = obj.get("cpu")?.asFloat ?: 0f
                val ram = obj.get("ram")?.asFloat ?: 0f
                val gpu = obj.get("gpu")?.asFloat ?: 0f
                val wa = obj.get("whatsapp")?.asBoolean ?: false

                views.setTextViewText(R.id.widgetCpu, "${cpu.toInt()}%")
                views.setTextViewText(R.id.widgetRam, "${ram.toInt()}%")
                views.setTextViewText(R.id.widgetGpu, if (gpu > 0f) "${gpu.toInt()}%" else "N/A")
                views.setProgressBar(R.id.widgetCpuBar, 100, cpu.toInt(), false)
                views.setProgressBar(R.id.widgetRamBar, 100, ram.toInt(), false)
                views.setProgressBar(R.id.widgetGpuBar, 100, gpu.toInt(), false)
                views.setTextViewText(R.id.widgetWa, if (wa) "WA ●" else "WA ○")
                views.setTextColor(R.id.widgetWa,
                    if (wa) 0xFF1db954.toInt() else 0xFF3a6070.toInt())
            } catch (_: Exception) {
                views.setTextViewText(R.id.widgetCpu, "OFFLINE")
                views.setTextViewText(R.id.widgetRam, "")
                views.setTextViewText(R.id.widgetGpu, "")
                views.setProgressBar(R.id.widgetCpuBar, 100, 0, false)
                views.setProgressBar(R.id.widgetRamBar, 100, 0, false)
                views.setProgressBar(R.id.widgetGpuBar, 100, 0, false)
            }

            manager.updateAppWidget(id, views)
        }
    }
}
