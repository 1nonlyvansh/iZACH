package com.izach.android

import android.Manifest
import android.app.AlertDialog
import android.app.DownloadManager
import android.app.NotificationChannel
import android.app.NotificationManager
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
import androidx.biometric.BiometricPrompt
import androidx.core.app.ActivityCompat
import androidx.core.app.NotificationCompat
import androidx.core.content.ContextCompat
import androidx.core.view.GravityCompat
import androidx.core.view.ViewCompat
import androidx.core.view.WindowInsetsCompat
import androidx.lifecycle.lifecycleScope
import androidx.recyclerview.widget.LinearLayoutManager
import com.izach.android.databinding.ActivityMainBinding
import com.izach.android.model.Message
import com.izach.android.network.IZACHApi
import com.izach.android.network.IZACHWebSocket
import com.izach.android.ui.ChatAdapter
import com.izach.android.ui.DownloadEvent
import com.izach.android.ui.DownloadMonitorBottomSheet
import com.izach.android.ui.FilePickerBottomSheet
import com.izach.android.ui.NotificationEntry
import com.izach.android.ui.NotificationHistoryBottomSheet
import com.izach.android.ui.QuickCommandBar
import com.izach.android.ui.TaskEvent
import com.izach.android.ui.TaskStreamBottomSheet
import kotlinx.coroutines.launch
import androidx.core.net.toUri
import android.content.ClipboardManager
import android.content.ClipData
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

    companion object {
        private const val NOTIF_CHANNEL_ID = "izach_pc_events"
        private const val NOTIF_ID_BASE = 1000
        private var notifCounter = 0
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
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
        if (prefs.getBoolean("biometric_lock", false)) showBiometricPrompt()

        createNotificationChannel()
        setupRecyclerView()
        setupWebSocket()
        setupInput()
        setupSidebar()
        loadHistory()
        checkStatus()

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
    }

    private fun showBiometricPrompt() {
        val executor = ContextCompat.getMainExecutor(this)
        val prompt = BiometricPrompt(this, executor, object : BiometricPrompt.AuthenticationCallback() {
            override fun onAuthenticationSucceeded(result: BiometricPrompt.AuthenticationResult) {}
            override fun onAuthenticationError(errorCode: Int, errString: CharSequence) { finish() }
            override fun onAuthenticationFailed() {}
        })
        val info = BiometricPrompt.PromptInfo.Builder()
            .setTitle("iZACH")
            .setSubtitle("Authenticate to continue")
            .setNegativeButtonText("Cancel")
            .build()
        prompt.authenticate(info)
    }

    private fun createNotificationChannel() {
        val channel = NotificationChannel(
            NOTIF_CHANNEL_ID, "iZACH PC Events",
            NotificationManager.IMPORTANCE_DEFAULT
        ).apply { description = "Notifications from your PC via iZACH" }
        (getSystemService(NOTIFICATION_SERVICE) as NotificationManager)
            .createNotificationChannel(channel)
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
        ws.onConnected    = { runOnUiThread { setStatus(true); syncDownloadState() } }
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

        binding.sidebarDashboard.setOnClickListener {
            closeThen { startActivity(Intent(this, SystemDashboardActivity::class.java)) }
        }

        binding.sidebarMyShortcuts.setOnClickListener {
            closeThen { startActivity(Intent(this, QuickShortcutsActivity::class.java)) }
        }

        binding.sidebarSettings.setOnClickListener {
            closeThen { startActivity(Intent(this, SettingsActivity::class.java)) }
        }
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
                    if (!ws.isConnected) {
                        adapter.add(Message(cmd.text, "iZACH"))
                        scrollBottom()
                    }
                    if (cmd.action == "open_file_picker") openFilePicker()
                }
            }.onFailure { err ->
                adapter.add(Message("Error: ${err.message}", "system"))
                scrollBottom()
            }
        }
    }

    private fun showConfirmationDialog(token: String, commandText: String) {
        AlertDialog.Builder(this)
            .setTitle("Confirm")
            .setMessage(commandText)
            .setPositiveButton("CONFIRM") { _, _ ->
                lifecycleScope.launch {
                    api.confirmCommand(token).onSuccess { cmd ->
                        if (!ws.isConnected) {
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
        lifecycleScope.launch { setStatus(api.checkStatus()) }
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
