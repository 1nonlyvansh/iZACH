package com.izach.android

import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.Bundle
import android.provider.Settings
import android.view.Gravity
import android.widget.ImageButton
import android.widget.LinearLayout
import android.widget.TextView
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import androidx.core.view.ViewCompat
import androidx.core.view.WindowCompat
import androidx.core.view.WindowInsetsCompat
import androidx.lifecycle.lifecycleScope
import com.izach.android.databinding.ActivitySettingsBinding
import com.izach.android.network.IZACHApi
import com.journeyapps.barcodescanner.ScanContract
import com.journeyapps.barcodescanner.ScanOptions
import kotlinx.coroutines.launch
import org.json.JSONObject

class SettingsActivity : AppCompatActivity() {

    private lateinit var binding: ActivitySettingsBinding
    private lateinit var api: IZACHApi
    private val vipList = mutableListOf<String>()

    private val qrLauncher = registerForActivityResult(ScanContract()) { result ->
        if (result?.contents != null) {
            try {
                val json = JSONObject(result.contents)
                val url  = json.getString("backend_url")
                val host = json.getString("ws_host")
                val secret = json.optString("pairing_secret", "")
                api.applyConnection(url, host, secret)
                binding.etBackendUrl.setText(url)
                binding.etWsHost.setText(host)
                binding.etPairingSecret.setText(secret)
                toast("Connected! Restart app to apply.")
                refreshPairingStatus()
            } catch (e: Exception) {
                toast("Invalid QR code — not an iZACH QR")
            }
        }
    }

    private fun refreshPairingStatus() {
        if (api.pairingSecret().isBlank()) {
            binding.pairedInfoCard.visibility = android.view.View.GONE
            binding.unpairedSection.visibility = android.view.View.VISIBLE
            return
        }
        lifecycleScope.launch {
            api.verifyPairing()
                .onSuccess { paired ->
                    if (!paired) {
                        // PC actually answered and rejected the secret — genuinely not paired.
                        binding.pairedInfoCard.visibility = android.view.View.GONE
                        binding.unpairedSection.visibility = android.view.View.VISIBLE
                        return@onSuccess
                    }
                    binding.pairedInfoCard.visibility = android.view.View.VISIBLE
                    binding.unpairedSection.visibility = android.view.View.GONE
                    api.getSystemStatus().onSuccess { s ->
                        binding.tvPairedPcName.text = "Connected to ${s.pcName.ifBlank { "PC" }}"
                        binding.tvPairedBattery.text = when {
                            s.batteryPct == null -> "Battery: unavailable"
                            s.batteryPlugged == true -> "Battery: ${s.batteryPct}% (charging)"
                            else -> "Battery: ${s.batteryPct}%"
                        }
                    }
                }
                .onFailure {
                    // Couldn't reach the PC at all — still paired, just offline/unreachable
                    // right now. Don't tell the user to re-scan for a plain connectivity blip.
                    binding.pairedInfoCard.visibility = android.view.View.VISIBLE
                    binding.unpairedSection.visibility = android.view.View.GONE
                    binding.tvPairedPcName.text = "Paired — PC unreachable"
                    binding.tvPairedBattery.text = "Check the PC is on and on the same network"
                }
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        WindowCompat.setDecorFitsSystemWindows(window, false)
        binding = ActivitySettingsBinding.inflate(layoutInflater)
        setContentView(binding.root)

        ViewCompat.setOnApplyWindowInsetsListener(binding.root) { view, insets ->
            val bars = insets.getInsets(WindowInsetsCompat.Type.systemBars())
            view.setPadding(view.paddingLeft, bars.top, view.paddingRight, bars.bottom)
            insets
        }

        api = IZACHApi(this)

        binding.etBackendUrl.setText(api.baseUrl())
        binding.etWsHost.setText(api.wsHost())
        binding.etAlliedUrl.setText(api.alliedBaseUrl())
        binding.etPairingSecret.setText(api.pairingSecret())

        binding.btnScanQr.setOnClickListener {
            val options = ScanOptions()
                .setDesiredBarcodeFormats(ScanOptions.QR_CODE)
                .setPrompt("Scan iZACH QR code shown on your PC")
                .setBeepEnabled(false)
                .setOrientationLocked(false)
                .setCaptureActivity(com.izach.android.ui.QrCaptureActivity::class.java)
            qrLauncher.launch(options)
        }

        binding.btnRepair.setOnClickListener {
            binding.unpairedSection.visibility = android.view.View.VISIBLE
            binding.pairedInfoCard.visibility = android.view.View.GONE
        }

        refreshPairingStatus()

        // Load notification category prefs
        val prefs = getSharedPreferences("izach_prefs", Context.MODE_PRIVATE)
        binding.swNotifSystem.isChecked    = prefs.getBoolean("notif_system", true)
        binding.swNotifDownloads.isChecked = prefs.getBoolean("notif_downloads", true)
        binding.swNotifTransfers.isChecked = prefs.getBoolean("notif_transfers", true)
        binding.swNotifAutomation.isChecked = prefs.getBoolean("notif_automation", true)
        binding.swNotifAlerts.isChecked    = prefs.getBoolean("notif_alerts", true)

        // Load security prefs
        binding.swBiometric.isChecked = prefs.getBoolean("biometric_lock", false)
        binding.swFloatMic.isChecked  = prefs.getBoolean("float_mic_enabled", false)

        binding.swPersistentStatus.isChecked = prefs.getBoolean(StatusNotificationService.PREF_ENABLED, true)

        // Auto-DND schedule
        binding.swAutoDnd.isChecked    = prefs.getBoolean("auto_dnd_enabled", false)
        binding.etDndStart.setText(prefs.getString("auto_dnd_start", "22:00"))
        binding.etDndEnd.setText(prefs.getString("auto_dnd_end",   "08:00"))

        // Proactive agent — lives on the PC (api_keys.json via /settings), not local prefs
        loadProactiveSettings()

        binding.swFloatMic.setOnCheckedChangeListener { _, isChecked ->
            if (isChecked) {
                if (!Settings.canDrawOverlays(this)) {
                    toast("Grant overlay permission first")
                    startActivity(Intent(Settings.ACTION_MANAGE_OVERLAY_PERMISSION,
                        Uri.parse("package:$packageName")))
                    binding.swFloatMic.isChecked = false
                } else {
                    startService(Intent(this, FloatingMicService::class.java))
                }
            } else {
                startService(Intent(this, FloatingMicService::class.java)
                    .setAction(FloatingMicService.ACTION_STOP))
            }
        }

        binding.swPersistentStatus.setOnCheckedChangeListener { _, isChecked ->
            prefs.edit().putBoolean(StatusNotificationService.PREF_ENABLED, isChecked).apply()
            if (isChecked) {
                androidx.core.content.ContextCompat.startForegroundService(
                    this, Intent(this, StatusNotificationService::class.java)
                )
            } else {
                startService(Intent(this, StatusNotificationService::class.java)
                    .setAction(StatusNotificationService.ACTION_STOP))
            }
        }

        binding.btnSave.setOnClickListener {
            val url = binding.etBackendUrl.text.toString().trim().trimEnd('/')
            val wsHost = binding.etWsHost.text.toString().trim()
            if (url.isBlank()) {
                toast("Backend URL required")
                return@setOnClickListener
            }
            api.clearActiveProfileLinkIfDifferentHost(wsHost)
            api.saveBackendUrl(url)
            api.saveWsHost(wsHost)
            api.savePairingSecret(binding.etPairingSecret.text.toString().trim())

            val alliedUrl = binding.etAlliedUrl.text.toString().trim().trimEnd('/')
            if (alliedUrl.isNotBlank()) api.saveAlliedUrl(alliedUrl)

            val dndStart = binding.etDndStart.text.toString().trim().ifBlank { "22:00" }
            val dndEnd   = binding.etDndEnd.text.toString().trim().ifBlank { "08:00" }

            prefs.edit()
                .putBoolean("notif_system",      binding.swNotifSystem.isChecked)
                .putBoolean("notif_downloads",   binding.swNotifDownloads.isChecked)
                .putBoolean("notif_transfers",   binding.swNotifTransfers.isChecked)
                .putBoolean("notif_automation",  binding.swNotifAutomation.isChecked)
                .putBoolean("notif_alerts",      binding.swNotifAlerts.isChecked)
                .putBoolean("biometric_lock",    binding.swBiometric.isChecked)
                .putBoolean("float_mic_enabled", binding.swFloatMic.isChecked)
                .putBoolean("auto_dnd_enabled",  binding.swAutoDnd.isChecked)
                .putString("auto_dnd_start",     dndStart)
                .putString("auto_dnd_end",       dndEnd)
                .apply()

            // Push schedule to backend
            val schedEnabled = binding.swAutoDnd.isChecked
            val (sh, sm) = dndStart.split(":").let { (it.getOrNull(0)?.toIntOrNull() ?: 22) to (it.getOrNull(1)?.toIntOrNull() ?: 0) }
            val (eh, em) = dndEnd.split(":").let { (it.getOrNull(0)?.toIntOrNull() ?: 8) to (it.getOrNull(1)?.toIntOrNull() ?: 0) }
            lifecycleScope.launch {
                api.pushDndSchedule(schedEnabled, sh, sm, eh, em)
            }

            // Save VIP contacts to backend

            lifecycleScope.launch { api.setVipContacts(vipList) }

            // Proactive agent settings — pushed straight to /settings (api_keys.json)
            val briefingTime = binding.etBriefingTime.text.toString().trim().ifBlank { "08:00" }
            val weatherCity  = binding.etWeatherCity.text.toString().trim().ifBlank { "New Delhi" }
            lifecycleScope.launch {
                api.setSetting("proactive_enabled", binding.swProactiveEnabled.isChecked)
                api.setSetting("briefing_calendar", binding.swBriefingCalendar.isChecked)
                api.setSetting("briefing_system", binding.swBriefingSystem.isChecked)
                api.setSetting("pattern_automation_suggestions_enabled", binding.swPatternSuggestions.isChecked)
                api.setSetting("morning_briefing_time", briefingTime)
                api.setSetting("weather_city", weatherCity)
            }

            toast("Saved. Restart app to reconnect.")
            finish()
        }

        binding.btnTest.setOnClickListener {
            val url = binding.etBackendUrl.text.toString().trim().ifBlank { api.baseUrl() }
            binding.tvTestResult.text = "Testing $url ..."
            binding.tvTestResult.setTextColor(getColor(R.color.text_sec))
            lifecycleScope.launch {
                val ok = api.checkStatus()
                binding.tvTestResult.text = if (ok)
                    "✓ Connected to $url"
                else
                    "✗ Cannot reach $url\n• Check PC IP (ipconfig on Windows, ifconfig/System Settings → Network on Mac)\n• Allow port 5050/5051 through the PC's firewall"
                binding.tvTestResult.setTextColor(
                    if (ok) getColor(R.color.cyan) else getColor(R.color.red_neon)
                )
            }
        }

        binding.btnBack.setOnClickListener { finish() }

        // ── VIP contacts ──────────────────────────────────────
        loadVipContacts()
        binding.btnVipAdd.setOnClickListener {
            val entry = binding.etVipInput.text.toString().trim()
            if (entry.isBlank()) return@setOnClickListener
            if (!vipList.contains(entry)) {
                vipList.add(entry)
                addVipRow(entry)
            }
            binding.etVipInput.text?.clear()
        }
    }

    private fun loadProactiveSettings() {
        lifecycleScope.launch {
            api.getProactiveSettings().onSuccess { s ->
                binding.swProactiveEnabled.isChecked = s.get("proactive_enabled")?.asBoolean ?: true
                val calendarDefault = s.get("briefing_events")?.asBoolean ?: true
                binding.swBriefingCalendar.isChecked = s.get("briefing_calendar")?.asBoolean ?: calendarDefault
                binding.swBriefingSystem.isChecked = s.get("briefing_system")?.asBoolean ?: false
                binding.swPatternSuggestions.isChecked = s.get("pattern_automation_suggestions_enabled")?.asBoolean ?: true
                binding.etBriefingTime.setText(s.get("morning_briefing_time")?.asString ?: "08:00")
                binding.etWeatherCity.setText(s.get("weather_city")?.asString ?: "New Delhi")
            }
        }
    }

    private fun loadVipContacts() {
        lifecycleScope.launch {
            api.getVipContacts()
                .onSuccess { list ->
                    vipList.clear()
                    vipList.addAll(list)
                    runOnUiThread {
                        binding.vipListContainer.removeAllViews()
                        list.forEach { addVipRow(it) }
                    }
                }
        }
    }

    private fun addVipRow(entry: String) {
        val dp = resources.displayMetrics.density
        val row = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
            setPadding(0, (4 * dp).toInt(), 0, (4 * dp).toInt())
        }
        val tv = TextView(this).apply {
            text = entry
            setTextColor(getColor(R.color.text_pri))
            textSize = 12f
            typeface = android.graphics.Typeface.MONOSPACE
            layoutParams = LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f)
        }
        val btn = ImageButton(this).apply {
            setImageResource(R.drawable.ic_task_failed)  // X icon
            background = null
            contentDescription = "Remove"
            setOnClickListener {
                vipList.remove(entry)
                binding.vipListContainer.removeView(row)
                saveVipToBackend()
            }
        }
        row.addView(tv)
        row.addView(btn)
        binding.vipListContainer.addView(row)
    }

    private fun saveVipToBackend() {
        lifecycleScope.launch {
            api.setVipContacts(vipList)
        }
    }

    // Also save VIP when hitting main SAVE button
    // (handled via btnSave click — override saveVip there)

    private fun toast(msg: String) = Toast.makeText(this, msg, Toast.LENGTH_SHORT).show()
}
