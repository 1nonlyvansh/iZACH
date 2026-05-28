package com.izach.android.widget

import android.app.PendingIntent
import android.appwidget.AppWidgetManager
import android.appwidget.AppWidgetProvider
import android.content.Context
import android.content.Intent
import android.widget.RemoteViews
import com.izach.android.MainActivity
import com.izach.android.R

class DndStatusWidget : AppWidgetProvider() {

    override fun onUpdate(context: Context, appWidgetManager: AppWidgetManager, appWidgetIds: IntArray) {
        for (id in appWidgetIds) updateWidget(context, appWidgetManager, id)
    }

    companion object {
        fun updateWidget(context: Context, appWidgetManager: AppWidgetManager, appWidgetId: Int) {
            val prefs = context.getSharedPreferences("izach_prefs", Context.MODE_PRIVATE)
            val dndActive   = prefs.getBoolean("dnd_active", false)
            val queueCount  = prefs.getInt("dnd_queue_count", 0)
            val busyActive  = prefs.getBoolean("busy_active", false)

            val views = RemoteViews(context.packageName, R.layout.widget_dnd_status)

            // DND state
            views.setTextViewText(R.id.widgetDndStatus, if (dndActive) "ON" else "OFF")
            views.setTextColor(R.id.widgetDndStatus,
                if (dndActive) 0xFFff8c00.toInt() else 0xFF3a6070.toInt())

            // Queue badge
            views.setTextViewText(R.id.widgetDndQueue,
                if (queueCount > 0) "$queueCount pending" else "")
            views.setViewVisibility(R.id.widgetDndQueue,
                if (queueCount > 0) android.view.View.VISIBLE else android.view.View.GONE)

            // Busy state
            views.setTextViewText(R.id.widgetBusyStatus, if (busyActive) "BUSY ON" else "BUSY OFF")
            views.setTextColor(R.id.widgetBusyStatus,
                if (busyActive) 0xFFffb300.toInt() else 0xFF3a6070.toInt())

            // Tap → open MainActivity
            val tapIntent = Intent(context, MainActivity::class.java).apply {
                flags = Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP
            }
            val tapPi = PendingIntent.getActivity(
                context, 0, tapIntent,
                PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
            )
            views.setOnClickPendingIntent(R.id.widgetDndRoot, tapPi)

            appWidgetManager.updateAppWidget(appWidgetId, views)
        }

        /** Call from MainActivity whenever DND/Busy state changes. */
        fun pushState(context: Context, dndActive: Boolean, queueCount: Int, busyActive: Boolean) {
            context.getSharedPreferences("izach_prefs", Context.MODE_PRIVATE).edit()
                .putBoolean("dnd_active", dndActive)
                .putInt("dnd_queue_count", queueCount)
                .putBoolean("busy_active", busyActive)
                .apply()

            val mgr = AppWidgetManager.getInstance(context)
            val ids = mgr.getAppWidgetIds(
                android.content.ComponentName(context, DndStatusWidget::class.java)
            )
            for (id in ids) updateWidget(context, mgr, id)
        }
    }
}
