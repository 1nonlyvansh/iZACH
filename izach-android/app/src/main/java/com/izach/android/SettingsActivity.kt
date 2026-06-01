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
                api.saveBackendUrl(url)
                api.saveWsHost(host)
                binding.etBackendUrl.setText(url)
                binding.etWsHost.setText(host)
                toast("Connected! Restart app to apply.")
            } catch (e: Exception) {
                toast("Invalid QR code — not an iZACH QR")
            }
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        binding = ActivitySettingsBinding.inflate(layoutInflater)
        setContentView(binding.root)
        api = IZACHApi(this)

        binding.etBackendUrl.setText(api.baseUrl())
        binding.etWsHost.setText(api.wsHost())
        binding.etAlliedUrl.setText(api.alliedBaseUrl())

        binding.btnScanQr.setOnClickListener {
            val options = ScanOptions()
                .setDesiredBarcodeFormats(ScanOptions.QR_CODE)
                .setPrompt("Scan iZACH QR code shown on your PC")
                .setBeepEnabled(false)
                .setOrientationLocked(false)
            qrLauncher.launch(options)
        }

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

        // Auto-DND schedule
        binding.swAutoDnd.isChecked    = prefs.getBoolean("auto_dnd_enabled", false)
        binding.etDndStart.setText(prefs.getString("auto_dnd_start", "22:00"))
        binding.etDndEnd.setText(prefs.getString("auto_dnd_end",   "08:00"))

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

        binding.btnSave.setOnClickListener {
            val url = binding.etBackendUrl.text.toString().trim().trimEnd('/')
            val wsHost = binding.etWsHost.text.toString().trim()
            if (url.isBlank()) {
                toast("Backend URL required")
                return@setOnClickListener
            }
            api.saveBackendUrl(url)
            api.saveWsHost(wsHost)

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
            launch { api.setVipContacts(vipList) }

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
                    "✗ Cannot reach $url\n• Check PC IP (run ipconfig on PC)\n• Allow port 5050/5051 in Windows Firewall"
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
