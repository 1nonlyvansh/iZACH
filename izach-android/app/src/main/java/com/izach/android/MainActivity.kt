package com.izach.android

import android.Manifest
import android.app.AlertDialog
import android.app.DownloadManager
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.ClipData
import android.content.ClipboardManager
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
import android.os.Bundle
import android.os.Environment
import android.speech.RecognitionListener
import android.speech.RecognizerIntent
import android.speech.SpeechRecognizer
import android.text.Editable
import android.text.TextWatcher
import android.view.View
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import androidx.core.app.ActivityCompat
import androidx.core.app.NotificationCompat
import androidx.core.app.RemoteInput
import androidx.core.content.ContextCompat
import androidx.core.content.pm.ShortcutInfoCompat
import androidx.core.content.pm.ShortcutManagerCompat
import androidx.core.graphics.drawable.IconCompat
import androidx.core.net.toUri
import androidx.core.view.GravityCompat
import androidx.core.view.ViewCompat
import androidx.core.view.WindowCompat
import androidx.core.view.WindowInsetsCompat
import androidx.lifecycle.lifecycleScope
import androidx.recyclerview.widget.LinearLayoutManager
import com.izach.android.databinding.ActivityMainBinding
import com.izach.android.model.DndAlert
import com.izach.android.model.Message
import com.izach.android.network.IZACHApi
import com.izach.android.network.IZACHWebSocket
import com.izach.android.widget.DndStatusWidget
import com.izach.android.ui.ChatAdapter
import com.izach.android.ui.DndQueueBottomSheet
import com.izach.android.ui.DownloadEvent
import com.izach.android.ui.DownloadMonitorBottomSheet
import com.izach.android.ui.FilePickerBottomSheet
import com.izach.android.ui.NotificationEntry
import com.izach.android.ui.NotificationHistoryBottomSheet
import com.izach.android.ui.QuickCommandBar
import com.izach.android.ui.TaskEvent
import com.izach.android.ui.TaskStreamBottomSheet
import com.izach.android.ui.WaQuickReplyBottomSheet
import kotlinx.coroutines.launch
import java.util.Locale

class MainActivity : AppCompatActivity() {

    private lateinit var binding: ActivityMainBinding
    private lateinit var api: IZACHApi
    private lateinit var ws: IZACHWebSocket
    private lateinit var adapter: ChatAdapter
    private var speechRecognizer: SpeechRecognizer? = null
    private var listening = false
    private var selectedPcPath: String? = null

    private var taskSheet: TaskStreamBottomSheet? = null
    private val activeTasks = mutableMapOf<String, TaskEvent>()

    private var notifSheet: NotificationHistoryBottomSheet? = null
    private val notificationHistory = mutableListOf<NotificationEntry>()
    private var unreadNotifs = 0

    private var downloadSheet: DownloadMonitorBottomSheet? = null
    private val activeDownloads = mutableMapOf<String, DownloadEvent>()
    private var activeDownloadCount = 0

    // DND / Busy state
    private val dndAlerts = mutableListOf<DndAlert>()
    private var dndActive = false
    private var busyActive = false
    private var dndSheet: DndQueueBottomSheet? = null
    private var dndAlertNotifCounter = 0

    companion object {
        private const val NOTIF_CHANNEL_ID       = "izach_pc_events"
        private const val NOTIF_CHANNEL_DND      = "izach_dnd_alerts"
        private const val NOTIF_CHANNEL_VIP      = "izach_vip_alerts"   // bypasses phone DND
        private const val NOTIF_CHANNEL_REMINDER = "izach_reminders"
        private const val NOTIF_ID_BASE          = 1000
        private const val NOTIF_ID_DND_BASE      = 3000
        private const val NOTIF_ID_REMINDER_BASE = 5000
        private const val NOTIF_ID_HANDOFF_BASE  = 6000
        private var notifCounter      = 0
        private var reminderCounter   = 0
        private var handoffCounter    = 0
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        WindowCompat.setDecorFitsSystemWindows(window, false)
        binding = ActivityMainBinding.inflate(layoutInflater)
        setContentView(binding.root)

        val dp4 = (4 * resources.displayMetrics.density + 0.5f).toInt()
        val dp8 = (8 * resources.displayMetrics.density + 0.5f).toInt()
        ViewCompat.setOnApplyWindowInsetsListener(binding.root) { _, insets ->
            val bars = insets.getInsets(WindowInsetsCompat.Type.systemBars())
            val ime  = insets.getInsets(WindowInsetsCompat.Type.ime())
            binding.topBar.setPadding(dp4, bars.top, dp4, 0)
            binding.bottomBar.setPadding(dp8, dp8, dp8, dp8 + maxOf(ime.bottom, bars.bottom))
            insets
        }

        api = IZACHApi(this)
        ws = IZACHWebSocket(api)
        adapter = ChatAdapter()

        val prefs = getSharedPreferences("izach_prefs", MODE_PRIVATE)

        createNotificationChannel()
        setupRecyclerView()
        setupWebSocket()
        setupInput()
        setupSidebar()
        setupDndBusy()
        setupAppShortcuts()
        loadHistory()
        checkStatus()
        pollDndBusyStatus()
        applyPlatformChips()

        // Play Services drops registered geofences on reboot and can lose
        // them on rare process-death edge cases — cheap to just re-assert
        // the saved list every time the app is opened.
        val savedGeofences = api.getGeofences()
        if (savedGeofences.isNotEmpty()) GeofenceManager.registerAll(this, savedGeofences)

        // Ongoing notification (connection/DND/Busy/PC Background Mode) — on by
        // default, toggleable in Settings. Re-asserted on every launch the same
        // way geofences are above, since a user can swipe the service away.
        if (prefs.getBoolean(StatusNotificationService.PREF_ENABLED, true)) {
            ContextCompat.startForegroundService(this, Intent(this, StatusNotificationService::class.java))
        }

        binding.btnBannerSetup.setOnClickListener {
            startActivity(Intent(this, SettingsActivity::class.java))
        }

        handleIncomingIntent(intent)
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        handleIncomingIntent(intent)
    }

    private fun handleIncomingIntent(intent: Intent?) {
        intent?.getStringExtra("shortcut_command")?.let { sendCommand(it) }
        if (intent?.getBooleanExtra("start_voice", false) == true) startVoice()

        // App Actions deep link: izach://feature/<name> (see res/xml/actions.xml)
        if (intent?.action == Intent.ACTION_VIEW && intent.data?.scheme == "izach") {
            openFeature(intent.data?.lastPathSegment ?: intent.data?.host)
        }
    }

    private fun openFeature(feature: String?) {
        val target = when (feature) {
            "calendar" -> CalendarActivity::class.java
            "bookmarks" -> BookmarksActivity::class.java
            "memory" -> MemoryActivity::class.java
            "automations" -> AutomationsActivity::class.java
            "recordings" -> RecordingsActivity::class.java
            "whatsapp" -> WhatsAppActivity::class.java
            "news" -> NewsActivity::class.java
            "dashboard" -> SystemDashboardActivity::class.java
            "search" -> SearchActivity::class.java
            "settings" -> SettingsActivity::class.java
            "browser" -> BrowserActivity::class.java
            "geofences" -> GeofencesActivity::class.java
            else -> null
        } ?: return
        startActivity(Intent(this, target))
    }

    private fun createNotificationChannel() {
        val nm = getSystemService(NOTIFICATION_SERVICE) as NotificationManager
        nm.createNotificationChannel(
            NotificationChannel(NOTIF_CHANNEL_ID, "iZACH PC Events", NotificationManager.IMPORTANCE_DEFAULT)
                .apply { description = "Notifications from your PC via iZACH" }
        )
        nm.createNotificationChannel(
            NotificationChannel(NOTIF_CHANNEL_DND, "iZACH DND Alerts", NotificationManager.IMPORTANCE_HIGH)
                .apply {
                    description = "Do Not Disturb alerts — messages & calls intercepted by iZACH"
                    enableVibration(true)
                }
        )
        nm.createNotificationChannel(
            NotificationChannel(NOTIF_CHANNEL_REMINDER, "iZACH Reminders", NotificationManager.IMPORTANCE_HIGH)
                .apply {
                    description = "Calendar event reminders from iZACH"
                    enableVibration(true)
                }
        )
        // VIP channel: IMPORTANCE_HIGH + bypass DND — shows even when phone is silenced
        nm.createNotificationChannel(
            NotificationChannel(NOTIF_CHANNEL_VIP, "iZACH VIP Alerts", NotificationManager.IMPORTANCE_HIGH)
                .apply {
                    description = "Priority contact messages — bypass Do Not Disturb"
                    enableVibration(true)
                    // BYPASS_DND requires system privilege — use setBypassDnd carefully
                    // On API 29+: users must manually enable bypass in channel settings
                }
        )
    }

    private fun setupRecyclerView() {
        val lm = LinearLayoutManager(this).apply { stackFromEnd = true }
        binding.rvChat.layoutManager = lm
        binding.rvChat.adapter = adapter
    }

    private fun setupWebSocket() {
        ws.onChat = { sender, text, ts ->
            if (sender != "YOU") runOnUiThread {
                adapter.add(Message(text, sender, ts))
                scrollBottom()
            }
        }
        ws.onNotification = { text ->
            runOnUiThread {
                adapter.add(Message(text, "system"))
                scrollBottom()
            }
        }
        ws.onConnected    = {
            runOnUiThread { syncDownloadState(); flushOfflineQueue() }
            // The WS accept path has no pairing check — any device on the LAN
            // gets onConnected — so it can't be used to prove pairing either.
            checkStatus()
        }
        ws.onDisconnected = { runOnUiThread { setStatus(false) } }

        ws.onScreenshot = { filename ->
            runOnUiThread {
                adapter.add(Message("📸 Screenshot ready — tap to view", "iZACH"))
                scrollBottom()
                startActivity(
                    Intent(this, ScreenshotViewerActivity::class.java)
                        .putExtra("filename", filename)
                )
            }
        }

        ws.onClipboard = { text ->
            runOnUiThread {
                val preview = text.take(60) + if (text.length > 60) "…" else ""
                adapter.add(Message("📋 PC clipboard: $preview", "system"))
                scrollBottom()
                val cm = getSystemService(CLIPBOARD_SERVICE) as ClipboardManager
                cm.setPrimaryClip(ClipData.newPlainText("iZACH", text))
            }
        }

        ws.onTaskEvent = { type, id, name, progress, message ->
            runOnUiThread {
                val resolvedName = name.ifBlank { activeTasks[id]?.name ?: "" }
                val event = TaskEvent(
                    id, resolvedName, progress,
                    when (type) { "task_completed" -> "completed"; "task_failed" -> "failed"; else -> "running" },
                    message
                )
                activeTasks[id] = event
                taskSheet?.upsertTask(event)
                val running = activeTasks.values.count { it.status == "running" }
                if (running > 0) {
                    binding.sidebarTasksBadge.text = "$running"
                    binding.sidebarTasksBadge.visibility = View.VISIBLE
                } else {
                    binding.sidebarTasksBadge.visibility = View.GONE
                }
            }
        }

        ws.onPcNotification = { title, body, category ->
            runOnUiThread {
                val entry = NotificationEntry(title, category, body)
                notificationHistory.add(0, entry)
                if (notificationHistory.size > 50) notificationHistory.removeAt(notificationHistory.lastIndex)
                notifSheet?.addNotification(entry)

                unreadNotifs++
                binding.sidebarBellBadge.text = "$unreadNotifs"
                binding.sidebarBellBadge.visibility = View.VISIBLE

                if (isCategoryEnabled(category)) showSystemNotification(title, body)
            }
        }

        ws.onDndAlert = { alert ->
            runOnUiThread {
                val idx = dndAlerts.indexOfFirst { it.id == alert.id }
                if (idx >= 0) dndAlerts[idx] = alert else dndAlerts.add(0, alert)
                dndSheet?.upsertAlert(alert)
                updateDndBadge()
                if (alert.action == null) showDndAlertNotification(alert, dndAlerts.indexOfFirst { it.id == alert.id })
            }
        }

        ws.onDndStatus = { status ->
            runOnUiThread {
                dndActive = status.active
                updateDndChip()
                if (status.queueCount > 0) updateDndBadge()
            }
        }

        ws.onBusyStatus = { active, reason ->
            runOnUiThread {
                busyActive = active
                updateBusyChip()
            }
        }

        ws.onReminder = { title, body ->
            runOnUiThread { showReminderNotification(title, body) }
        }

        ws.onDownloadEvent = { type, filename, size, speedStr ->
            runOnUiThread {
                val status = when (type) {
                    "download_completed" -> "completed"
                    "download_failed"    -> "failed"
                    else                 -> "downloading"
                }
                val event = DownloadEvent(filename, size, speedStr, status)
                if (status == "completed" || status == "failed") {
                    activeDownloads.remove(filename)
                } else {
                    activeDownloads[filename] = event
                }
                downloadSheet?.upsertDownload(event)

                activeDownloadCount = activeDownloads.size
                if (activeDownloadCount > 0) {
                    binding.sidebarDlBadge.text = "$activeDownloadCount"
                    binding.sidebarDlBadge.visibility = View.VISIBLE
                } else {
                    binding.sidebarDlBadge.visibility = View.GONE
                }

                if (type == "download_completed") {
                    val entry = NotificationEntry("Download complete: $filename", "downloads", "")
                    notificationHistory.add(0, entry)
                    notifSheet?.addNotification(entry)
                    if (isCategoryEnabled("downloads")) showSystemNotification("Download complete", filename)
                }
            }
        }

        ws.onBrowserHandoff = { url, title ->
            runOnUiThread { showBrowserHandoffNotification(url, title) }
        }

        ws.connect()
    }

    private fun isCategoryEnabled(category: String): Boolean {
        return getSharedPreferences("izach_prefs", MODE_PRIVATE)
            .getBoolean("notif_$category", true)
    }

    private fun showSystemNotification(title: String, body: String) {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU &&
            ContextCompat.checkSelfPermission(this, Manifest.permission.POST_NOTIFICATIONS)
            != PackageManager.PERMISSION_GRANTED) return

        val nm = getSystemService(NOTIFICATION_SERVICE) as NotificationManager
        val notif = NotificationCompat.Builder(this, NOTIF_CHANNEL_ID)
            .setSmallIcon(R.drawable.ic_bell)
            .setContentTitle(title)
            .setContentText(body.ifBlank { null })
            .setPriority(NotificationCompat.PRIORITY_DEFAULT)
            .setAutoCancel(true)
            .build()
        nm.notify(NOTIF_ID_BASE + notifCounter++, notif)
    }

    private fun setupInput() {
        binding.etInput.addTextChangedListener(object : TextWatcher {
            override fun beforeTextChanged(s: CharSequence?, start: Int, count: Int, after: Int) {}
            override fun onTextChanged(s: CharSequence?, start: Int, before: Int, count: Int) {}
            override fun afterTextChanged(s: Editable?) {
                if (s?.toString() == "/") { s.clear(); openFilePicker() }
            }
        })

        binding.btnSend.setOnClickListener {
            val text = binding.etInput.text?.toString()?.trim() ?: return@setOnClickListener
            if (text.isNotEmpty()) { binding.etInput.text?.clear(); sendCommand(text) }
        }

        binding.btnVoice.setOnClickListener { if (listening) stopVoice() else startVoice() }

        binding.btnQuick.setOnClickListener {
            QuickCommandBar().show(supportFragmentManager, "quick_cmds")
        }

        binding.btnMenu.setOnClickListener {
            binding.drawerLayout.openDrawer(GravityCompat.START)
        }
    }

    private fun setupSidebar() {
        fun closeThen(action: () -> Unit) {
            binding.drawerLayout.closeDrawer(GravityCompat.START)
            binding.drawerLayout.post { action() }
        }

        binding.sidebarDnd.setOnClickListener { closeThen { openDndSheet() } }

        binding.sidebarQuick.setOnClickListener {
            closeThen { QuickCommandBar().show(supportFragmentManager, "quick_cmds") }
        }

        binding.sidebarScreenshot.setOnClickListener {
            closeThen {
                lifecycleScope.launch {
                    api.captureScreenshot().onSuccess { filename ->
                        startActivity(
                            Intent(this@MainActivity, ScreenshotViewerActivity::class.java)
                                .putExtra("filename", filename)
                        )
                    }.onFailure {
                        Toast.makeText(this@MainActivity, "Screenshot failed: ${it.message}", Toast.LENGTH_SHORT).show()
                    }
                }
            }
        }

        binding.sidebarClipboard.setOnClickListener {
            closeThen { startActivity(Intent(this, ClipboardActivity::class.java)) }
        }

        binding.sidebarTasks.setOnClickListener {
            closeThen {
                binding.sidebarTasksBadge.visibility = View.GONE
                taskSheet = TaskStreamBottomSheet()
                taskSheet?.preloadTasks(activeTasks.values)
                taskSheet?.show(supportFragmentManager, "tasks")
            }
        }

        binding.sidebarBell.setOnClickListener {
            closeThen {
                unreadNotifs = 0
                binding.sidebarBellBadge.visibility = View.GONE
                notifSheet = NotificationHistoryBottomSheet()
                notifSheet?.preload(notificationHistory)
                notifSheet?.show(supportFragmentManager, "notifications")
            }
        }

        binding.sidebarDownloads.setOnClickListener {
            closeThen {
                downloadSheet = DownloadMonitorBottomSheet()
                downloadSheet?.preload(activeDownloads.values)
                downloadSheet?.show(supportFragmentManager, "downloads")
            }
        }

        binding.sidebarFiles.setOnClickListener {
            closeThen { startActivity(Intent(this, FileTransferActivity::class.java)) }
        }

        binding.sidebarMedia.setOnClickListener {
            closeThen { startActivity(Intent(this, SpotifyRemoteActivity::class.java)) }
        }

        binding.sidebarAudioStream.setOnClickListener {
            closeThen { openAudioStream() }
        }

        binding.sidebarAlliedNode.setOnClickListener {
            closeThen { startActivity(Intent(this, AlliedNodeActivity::class.java)) }
        }

        binding.sidebarDashboard.setOnClickListener {
            closeThen { startActivity(Intent(this, SystemDashboardActivity::class.java)) }
        }

        binding.sidebarMyShortcuts.setOnClickListener {
            closeThen { startActivity(Intent(this, QuickShortcutsActivity::class.java)) }
        }

        binding.sidebarCalendar.setOnClickListener {
            closeThen { startActivity(Intent(this, CalendarActivity::class.java)) }
        }

        binding.sidebarRecordings.setOnClickListener {
            closeThen { startActivity(Intent(this, RecordingsActivity::class.java)) }
        }

        binding.sidebarMemory.setOnClickListener {
            closeThen { startActivity(Intent(this, MemoryActivity::class.java)) }
        }

        binding.sidebarAutomations.setOnClickListener {
            closeThen { startActivity(Intent(this, AutomationsActivity::class.java)) }
        }

        binding.sidebarBookmarks.setOnClickListener {
            closeThen { startActivity(Intent(this, BookmarksActivity::class.java)) }
        }

        binding.sidebarWhatsApp.setOnClickListener {
            closeThen { startActivity(Intent(this, WhatsAppActivity::class.java)) }
        }

        binding.sidebarNews.setOnClickListener {
            closeThen { startActivity(Intent(this, NewsActivity::class.java)) }
        }

        binding.sidebarBrowser.setOnClickListener {
            closeThen { startActivity(Intent(this, BrowserActivity::class.java)) }
        }

        binding.sidebarSearch.setOnClickListener {
            closeThen { startActivity(Intent(this, SearchActivity::class.java)) }
        }

        binding.sidebarGeofences.setOnClickListener {
            closeThen { startActivity(Intent(this, GeofencesActivity::class.java)) }
        }

        binding.sidebarSettings.setOnClickListener {
            closeThen { startActivity(Intent(this, SettingsActivity::class.java)) }
        }
    }

    private fun setupDndBusy() {
        binding.chipDnd.setOnClickListener { showDndToggleDialog() }
        binding.chipBusy.setOnClickListener { showBusyToggleDialog() }
        binding.chipBgMode.setOnClickListener {
            startActivity(Intent(this, QuickShortcutsActivity::class.java))
        }
    }

    // Background Mode doesn't exist on macOS iZACH — hide the header chip
    // entirely (not just disable) when connected to Mac, same treatment as
    // the Forge/Background tiles in Quick Shortcuts. Uses the cached
    // platform on the active profile if already known (no visible flash),
    // then confirms with a live check in case it's stale or unknown yet.
    private fun applyPlatformChips() {
        binding.chipBgMode.visibility = if (api.activePlatform() == "mac") View.GONE else View.VISIBLE
        lifecycleScope.launch {
            api.getSystemStatus().onSuccess { status ->
                binding.chipBgMode.visibility = if (status.platform == "mac") View.GONE else View.VISIBLE
            }
        }
    }

    private fun pollDndBusyStatus() {
        lifecycleScope.launch {
            api.getDndStatus().onSuccess { s ->
                dndActive = s.active
                updateDndChip()
            }
            api.getBusyStatus().onSuccess { s ->
                busyActive = s.active
                updateBusyChip()
            }
            // Load existing queue
            api.getDndQueue().onSuccess { queue ->
                dndAlerts.clear()
                dndAlerts.addAll(queue.reversed()) // newest first
                updateDndBadge()
            }
        }
    }

    private fun updateDndChip() {
        val active = dndActive
        binding.chipDnd.text = if (active) "DND ON" else "DND"
        binding.chipDnd.setTextColor(if (active) 0xFFff8c00.toInt() else 0xFF3a6070.toInt())
        val bg = if (active) "#40ff8c00" else "#10ff8c00"
        binding.chipDnd.setBackgroundColor(android.graphics.Color.parseColor(bg))
        pushWidgetState()
    }

    private fun updateBusyChip() {
        val active = busyActive
        binding.chipBusy.text = if (active) "BUSY ON" else "BUSY"
        binding.chipBusy.setTextColor(if (active) 0xFFffb300.toInt() else 0xFF3a6070.toInt())
        val bg = if (active) "#40ffb300" else "#10ffb300"
        binding.chipBusy.setBackgroundColor(android.graphics.Color.parseColor(bg))
        pushWidgetState()
    }

    private fun pushWidgetState() {
        DndStatusWidget.pushState(
            this,
            dndActive,
            dndAlerts.count { it.action == null },
            busyActive
        )
    }

    private fun updateDndBadge() {
        val unhandled = dndAlerts.count { it.action == null }
        if (unhandled > 0) {
            binding.sidebarDndBadge.text = "$unhandled"
            binding.sidebarDndBadge.visibility = View.VISIBLE
        } else {
            binding.sidebarDndBadge.visibility = View.GONE
        }
    }

    private fun openDndSheet() {
        binding.drawerLayout.closeDrawer(GravityCompat.START)
        val sheet = DndQueueBottomSheet()
        dndSheet = sheet
        sheet.preload(dndAlerts)

        sheet.onRefresh = {
            lifecycleScope.launch {
                api.getDndQueue().onSuccess { queue ->
                    dndAlerts.clear()
                    dndAlerts.addAll(queue.reversed())
                    sheet.preload(dndAlerts)
                    updateDndBadge()
                }
            }
        }

        sheet.onHandle = { alert, _ ->
            val idx = dndAlerts.indexOfFirst { it.id == alert.id }
            if (idx >= 0) {
                lifecycleScope.launch {
                    api.dndHandle(idx)
                        .onSuccess {
                            val replySheet = WaQuickReplyBottomSheet.newInstance(
                                alert.from, alert.number, alert.text, api
                            )
                            replySheet.onSend = { number, text, name ->
                                lifecycleScope.launch {
                                    api.waSendMessage(number, text, name)
                                        .onSuccess { Toast.makeText(this@MainActivity, "✅ Reply sent!", Toast.LENGTH_SHORT).show() }
                                        .onFailure { Toast.makeText(this@MainActivity, "Send failed: ${it.message}", Toast.LENGTH_SHORT).show() }
                                }
                            }
                            replySheet.show(supportFragmentManager, "wa_reply")
                            refreshDndQueue(sheet)
                        }
                        .onFailure { Toast.makeText(this@MainActivity, "Handle failed: ${it.message}", Toast.LENGTH_SHORT).show() }
                }
            }
        }

        sheet.onBusy = { alert, _ ->
            val idx = dndAlerts.indexOfFirst { it.id == alert.id }
            if (idx >= 0) {
                lifecycleScope.launch {
                    api.dndBusy(idx)
                        .onSuccess {
                            Toast.makeText(this@MainActivity, "📵 Busy reply sent", Toast.LENGTH_SHORT).show()
                            refreshDndQueue(sheet)
                        }
                        .onFailure { Toast.makeText(this@MainActivity, "Busy failed: ${it.message}", Toast.LENGTH_SHORT).show() }
                }
            }
        }

        sheet.show(supportFragmentManager, "dnd_queue")
    }

    private fun refreshDndQueue(sheet: DndQueueBottomSheet) {
        lifecycleScope.launch {
            api.getDndQueue().onSuccess { queue ->
                dndAlerts.clear()
                dndAlerts.addAll(queue.reversed())
                sheet.preload(dndAlerts)
                updateDndBadge()
            }
        }
    }

    private fun showDndToggleDialog() {
        val action = if (dndActive) "off" else "on"
        val label  = if (dndActive) "Turn DND OFF?" else "Turn DND ON?"
        val msg    = if (dndActive) "Disable Do Not Disturb. Queued alerts will be shown."
                     else "Enable Do Not Disturb. Incoming messages will be held silently."
        AlertDialog.Builder(this)
            .setTitle(label)
            .setMessage(msg)
            .setPositiveButton(action.uppercase()) { _, _ ->
                lifecycleScope.launch {
                    api.toggleDnd(action, "manual")
                        .onSuccess { status ->
                            dndActive = status.active
                            updateDndChip()
                            Toast.makeText(this@MainActivity,
                                if (dndActive) "DND ON" else "DND OFF",
                                Toast.LENGTH_SHORT).show()
                            // If DND just turned off and queue has items, open queue sheet
                            if (!dndActive && dndAlerts.any { it.action == null }) openDndSheet()
                        }
                        .onFailure { Toast.makeText(this@MainActivity, "Failed: ${it.message}", Toast.LENGTH_SHORT).show() }
                }
            }
            .setNeutralButton("VIEW QUEUE") { _, _ -> openDndSheet() }
            .setNegativeButton("CANCEL", null)
            .show()
    }

    private fun showBusyToggleDialog() {
        val action = if (busyActive) "off" else "on"
        val label  = if (busyActive) "Turn Busy Mode OFF?" else "Turn Busy Mode ON?"
        val msg    = if (busyActive) "iZACH will stop sending busy auto-replies."
                     else "iZACH will auto-reply as busy to incoming messages."
        AlertDialog.Builder(this)
            .setTitle(label)
            .setMessage(msg)
            .setPositiveButton(action.uppercase()) { _, _ ->
                lifecycleScope.launch {
                    api.toggleBusy(action, if (action == "on") "Manual" else "")
                        .onSuccess {
                            busyActive = !busyActive
                            updateBusyChip()
                            Toast.makeText(this@MainActivity,
                                if (busyActive) "Busy mode ON" else "Busy mode OFF",
                                Toast.LENGTH_SHORT).show()
                        }
                        .onFailure { Toast.makeText(this@MainActivity, "Failed: ${it.message}", Toast.LENGTH_SHORT).show() }
                }
            }
            .setNegativeButton("CANCEL", null)
            .show()
    }

    private fun showDndAlertNotification(alert: DndAlert, queueIndex: Int) {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU &&
            ContextCompat.checkSelfPermission(this, Manifest.permission.POST_NOTIFICATIONS)
            != PackageManager.PERMISSION_GRANTED) return

        val isCall     = alert.type == "phone_call"
        val isPriority = alert.isPriority
        val channel    = if (isPriority) NOTIF_CHANNEL_VIP else NOTIF_CHANNEL_DND
        val titlePrefix = when {
            isPriority && isCall -> "⭐📞 VIP CALL from ${alert.from}"
            isPriority           -> "⭐💬 VIP MSG from ${alert.from}"
            isCall               -> "📞 DND — Call from ${alert.from}"
            else                 -> "💬 DND — Msg from ${alert.from}"
        }
        val title   = titlePrefix
        val body    = if (isCall) "Incoming WhatsApp call blocked" else alert.text.take(120)
        val notifId = NOTIF_ID_DND_BASE + dndAlertNotifCounter++

        fun makeActionPi(action: String, reqCode: Int): PendingIntent {
            val i = Intent(this, DndActionReceiver::class.java).apply {
                this.action = action
                putExtra(DndActionReceiver.EXTRA_INDEX, queueIndex)
            }
            return PendingIntent.getBroadcast(this, reqCode,
                i, PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE)
        }

        val builder = NotificationCompat.Builder(this, channel)
            .setSmallIcon(R.drawable.ic_bell)
            .setContentTitle(title)
            .setContentText(body)
            .setPriority(NotificationCompat.PRIORITY_HIGH)
            .setAutoCancel(true)
            // Lock-screen visibility — show full content
            .setVisibility(NotificationCompat.VISIBILITY_PUBLIC)
            .addAction(0, "✅ HANDLE", makeActionPi(DndActionReceiver.ACTION_HANDLE, queueIndex * 10))
            .addAction(0, "📵 BUSY",   makeActionPi(DndActionReceiver.ACTION_BUSY,   queueIndex * 10 + 1))

        // Add inline WhatsApp reply action for messages (not calls)
        if (!isCall && alert.number.isNotBlank()) {
            val remoteInput = RemoteInput.Builder(DndInlineReplyReceiver.KEY_REPLY_TEXT)
                .setLabel("Reply to ${alert.from}…")
                .build()

            val replyIntent = Intent(this, DndInlineReplyReceiver::class.java).apply {
                action = DndInlineReplyReceiver.ACTION_INLINE_REPLY
                putExtra(DndInlineReplyReceiver.EXTRA_REPLY_NUMBER, alert.number)
                putExtra(DndInlineReplyReceiver.EXTRA_REPLY_NAME,   alert.from)
                putExtra(DndInlineReplyReceiver.EXTRA_NOTIF_ID,     notifId)
            }
            // FLAG_MUTABLE required for RemoteInput on API 31+; not available on older APIs
            val replyFlags = PendingIntent.FLAG_UPDATE_CURRENT or
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) PendingIntent.FLAG_MUTABLE else 0
            val replyPi = PendingIntent.getBroadcast(
                this, queueIndex * 10 + 2, replyIntent, replyFlags
            )
            val replyAction = NotificationCompat.Action.Builder(
                R.drawable.ic_bell, "↩ REPLY", replyPi
            ).addRemoteInput(remoteInput).build()

            builder.addAction(replyAction)
        }

        (getSystemService(NOTIFICATION_SERVICE) as NotificationManager)
            .notify(notifId, builder.build())
    }

    private fun showReminderNotification(title: String, body: String) {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU &&
            ContextCompat.checkSelfPermission(this, Manifest.permission.POST_NOTIFICATIONS)
            != PackageManager.PERMISSION_GRANTED) return

        val tapIntent = Intent(this, MainActivity::class.java).apply {
            flags = Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP
        }
        val tapPi = PendingIntent.getActivity(
            this, 0, tapIntent,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        )
        val notif = NotificationCompat.Builder(this, NOTIF_CHANNEL_REMINDER)
            .setSmallIcon(R.drawable.ic_bell)
            .setContentTitle("⏰ $title")
            .setContentText(body)
            .setPriority(NotificationCompat.PRIORITY_HIGH)
            .setVisibility(NotificationCompat.VISIBILITY_PUBLIC)
            .setAutoCancel(true)
            .setContentIntent(tapPi)
            .build()
        (getSystemService(NOTIFICATION_SERVICE) as NotificationManager)
            .notify(NOTIF_ID_REMINDER_BASE + reminderCounter++, notif)
    }

    private fun showBrowserHandoffNotification(url: String, title: String) {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU &&
            ContextCompat.checkSelfPermission(this, Manifest.permission.POST_NOTIFICATIONS)
            != PackageManager.PERMISSION_GRANTED) return

        val tapIntent = Intent(this, BrowserActivity::class.java).apply {
            putExtra(BrowserActivity.EXTRA_URL, url)
        }
        val tapPi = PendingIntent.getActivity(
            this, handoffCounter, tapIntent,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        )
        val notif = NotificationCompat.Builder(this, NOTIF_CHANNEL_ID)
            .setSmallIcon(R.drawable.ic_browser)
            .setContentTitle("📱 Sent from PC")
            .setContentText(title)
            .setPriority(NotificationCompat.PRIORITY_DEFAULT)
            .setAutoCancel(true)
            .setContentIntent(tapPi)
            .build()
        (getSystemService(NOTIFICATION_SERVICE) as NotificationManager)
            .notify(NOTIF_ID_HANDOFF_BASE + handoffCounter++, notif)
    }

    private fun setupAppShortcuts() {
        if (!ShortcutManagerCompat.isRequestPinShortcutSupported(this)) return

        fun makeIntent(command: String? = null, startVoice: Boolean = false): Intent =
            Intent(this, MainActivity::class.java).apply {
                action = "com.izach.android.SHORTCUT_ACTION"
                flags  = Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP
                if (command != null) putExtra("shortcut_command", command)
                if (startVoice)      putExtra("start_voice", true)
            }

        // lock_pc, screenshot and voice_command are already declared as static
        // shortcuts in res/xml/shortcuts.xml. Manifest (static) shortcuts are
        // immutable — pushing dynamic shortcuts with the same IDs throws
        // IllegalArgumentException("...may not be manipulated via APIs") and
        // crashes onCreate() on every launch. Only push IDs not covered statically.
        val shortcuts = listOf(
            ShortcutInfoCompat.Builder(this, "toggle_dnd")
                .setShortLabel("Toggle DND")
                .setLongLabel("Toggle Do Not Disturb")
                .setIcon(IconCompat.createWithResource(this, R.drawable.ic_bell))
                .setIntent(makeIntent("toggle dnd"))
                .build(),
        )

        ShortcutManagerCompat.setDynamicShortcuts(this, shortcuts)
    }

    private fun openAudioStream() {
        startActivity(Intent(this, AudioStreamActivity::class.java))
    }

    private fun sendCommand(text: String) {
        val pcPath = selectedPcPath
        selectedPcPath = null

        if (pcPath != null) {
            val displayName = text.trimStart('/')
            adapter.add(Message("↓ $displayName", "YOU"))
            scrollBottom()
            binding.etInput.text?.clear()
            downloadPcFile(displayName, pcPath)
            return
        }

        adapter.add(Message(text, "YOU"))
        scrollBottom()
        binding.typingIndicator.visibility = View.VISIBLE

        lifecycleScope.launch {
            val result = api.sendCommand(text)
            binding.typingIndicator.visibility = View.GONE
            result.onSuccess { cmd ->
                if (cmd.requiresConfirmation && cmd.confirmationToken != null) {
                    showConfirmationDialog(cmd.confirmationToken, cmd.text)
                } else {
                    // Always show HTTP response — backend captures speak() so WS
                    // doesn't deliver the iZACH reply for /command calls.
                    adapter.add(Message(cmd.text, "iZACH"))
                    scrollBottom()
                    if (cmd.action == "open_file_picker") openFilePicker()
                }
            }.onFailure { err ->
                if (err is com.izach.android.network.PairingRejectedException) {
                    adapter.add(Message("🔒 Not paired with this PC — scan the QR code in Settings to pair again.", "system"))
                } else {
                    api.enqueueOfflineCommand(text)
                    adapter.add(Message("📥 PC unreachable — queued, will send once reconnected (${err.message})", "system"))
                }
                scrollBottom()
            }
        }
    }

    private var flushingOfflineQueue = false

    private fun flushOfflineQueue() {
        if (flushingOfflineQueue) return
        val queued = api.getQueuedCommands()
        if (queued.isEmpty()) return
        flushingOfflineQueue = true
        lifecycleScope.launch {
            var sentCount = 0
            var pairingRejected = false
            for (text in queued) {
                val result = api.sendCommand(text)
                if (result.isSuccess) {
                    api.removeQueuedCommand(text)
                    sentCount++
                } else {
                    // A rejected pairing secret will reject every remaining
                    // queued command too — no point retrying them right now.
                    if (result.exceptionOrNull() is com.izach.android.network.PairingRejectedException) pairingRejected = true
                    break // stop at the first failure — still offline (or unpaired), retry next reconnect
                }
            }
            if (sentCount > 0) {
                adapter.add(Message("📤 Sent $sentCount queued command${if (sentCount != 1) "s" else ""}", "system"))
                scrollBottom()
            }
            if (pairingRejected) {
                adapter.add(Message("🔒 Queued commands couldn't be sent — this device isn't paired with the PC. Scan the QR code in Settings.", "system"))
                scrollBottom()
            }
            flushingOfflineQueue = false
        }
    }

    private fun showConfirmationDialog(token: String, commandText: String) {
        AlertDialog.Builder(this)
            .setTitle("Confirm")
            .setMessage(commandText)
            .setPositiveButton("CONFIRM") { _, _ ->
                lifecycleScope.launch {
                    api.confirmCommand(token).onSuccess { cmd ->
                        run {
                            adapter.add(Message(cmd.text, "iZACH"))
                            scrollBottom()
                        }
                    }.onFailure {
                        adapter.add(Message("Confirm failed: ${it.message}", "system"))
                        scrollBottom()
                    }
                }
            }
            .setNegativeButton("CANCEL", null)
            .show()
    }

    private fun openFilePicker() {
        val sheet = FilePickerBottomSheet()
        sheet.onFileSelected = { entry ->
            selectedPcPath = entry.path
            binding.etInput.setText("/${entry.name}")
            binding.etInput.setSelection(binding.etInput.text?.length ?: 0)
        }
        sheet.show(supportFragmentManager, "file_picker")
    }

    private fun downloadPcFile(displayName: String, pcPath: String) {
        val url = api.fetchFileUrl(pcPath)
        val req = DownloadManager.Request(url.toUri()).apply {
            setTitle(displayName)
            setDescription("iZACH → Phone")
            setNotificationVisibility(DownloadManager.Request.VISIBILITY_VISIBLE_NOTIFY_COMPLETED)
            setDestinationInExternalPublicDir(Environment.DIRECTORY_DOWNLOADS, displayName)
            setAllowedOverMetered(true)
        }
        (getSystemService(DOWNLOAD_SERVICE) as DownloadManager).enqueue(req)
        adapter.add(Message("Downloading $displayName…", "iZACH"))
        scrollBottom()
    }

    private fun loadHistory() {
        lifecycleScope.launch {
            api.getHistory(30).onSuccess { msgs ->
                if (msgs.isNotEmpty() && adapter.isEmpty()) {
                    adapter.setAll(msgs)
                    scrollBottom()
                }
            }
        }
    }

    private fun checkStatus() {
        // /status alone only proves the PC is reachable, not that this device
        // is actually paired (it's HMAC-exempt so any device on the LAN gets
        // a 200) — that mismatch is exactly what let the banner show ONLINE
        // while every real command still 401'd as unpaired. verifyPairing()
        // hits a signed, non-exempt route so it reflects what commands see.
        lifecycleScope.launch { setStatus(api.verifyPairing().getOrDefault(false)) }
    }

    private fun startVoice() {
        if (ContextCompat.checkSelfPermission(this, Manifest.permission.RECORD_AUDIO)
            != PackageManager.PERMISSION_GRANTED) {
            ActivityCompat.requestPermissions(this, arrayOf(Manifest.permission.RECORD_AUDIO), 100)
            return
        }
        if (speechRecognizer == null) {
            speechRecognizer = SpeechRecognizer.createSpeechRecognizer(this)
            speechRecognizer?.setRecognitionListener(object : RecognitionListener {
                override fun onResults(results: Bundle?) {
                    val text = results?.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION)
                        ?.firstOrNull() ?: return
                    stopVoice(); sendCommand(text)
                }
                override fun onError(error: Int) { stopVoice() }
                override fun onReadyForSpeech(p: Bundle?) {}
                override fun onBeginningOfSpeech() {}
                override fun onRmsChanged(v: Float) {}
                override fun onBufferReceived(b: ByteArray?) {}
                override fun onEndOfSpeech() {}
                override fun onPartialResults(p: Bundle?) {}
                override fun onEvent(t: Int, p: Bundle?) {}
            })
        }
        listening = true
        binding.btnVoice.setImageResource(R.drawable.ic_mic_active)
        val intent = Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH).apply {
            putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM)
            putExtra(RecognizerIntent.EXTRA_LANGUAGE, Locale.getDefault())
        }
        speechRecognizer?.startListening(intent)
    }

    private fun stopVoice() {
        listening = false
        binding.btnVoice.setImageResource(R.drawable.ic_mic)
        speechRecognizer?.stopListening()
        // Destroy and null out so next tap gets a fresh recognizer.
        // Reusing the same instance after onResults/onError causes silent failures.
        speechRecognizer?.destroy()
        speechRecognizer = null
    }

    private fun setStatus(connected: Boolean) {
        binding.tvStatus.text = if (connected) "ONLINE" else "OFFLINE"
        binding.tvStatus.setTextColor(ContextCompat.getColor(this,
            if (connected) R.color.cyan else R.color.red_neon))
        binding.statusDot.setBackgroundResource(
            if (connected) R.drawable.dot_connected else R.drawable.dot_disconnected)
        binding.bannerConnect.visibility = if (connected) View.GONE else View.VISIBLE
    }

    private fun syncDownloadState() {
        lifecycleScope.launch {
            api.getActiveDownloads().onSuccess { activeNames ->
                val stale = activeDownloads.keys.filter { it !in activeNames }
                stale.forEach { name ->
                    activeDownloads.remove(name)
                    downloadSheet?.upsertDownload(DownloadEvent(name, 0, "", "completed"))
                }
                activeDownloadCount = activeDownloads.size
                if (activeDownloadCount > 0) {
                    binding.sidebarDlBadge.text = "$activeDownloadCount"
                    binding.sidebarDlBadge.visibility = View.VISIBLE
                } else {
                    binding.sidebarDlBadge.visibility = View.GONE
                }
            }
        }
    }

    private fun scrollBottom() {
        binding.rvChat.post { binding.rvChat.scrollToPosition(adapter.itemCount - 1) }
    }

    override fun onBackPressed() {
        if (binding.drawerLayout.isDrawerOpen(GravityCompat.START)) {
            binding.drawerLayout.closeDrawer(GravityCompat.START)
        } else {
            super.onBackPressed()
        }
    }

    override fun onRequestPermissionsResult(requestCode: Int, permissions: Array<out String>, results: IntArray) {
        super.onRequestPermissionsResult(requestCode, permissions, results)
        if (requestCode == 100 && results.firstOrNull() == PackageManager.PERMISSION_GRANTED) startVoice()
    }

    override fun onDestroy() {
        super.onDestroy()
        ws.disconnect()
        speechRecognizer?.destroy()
    }
}
