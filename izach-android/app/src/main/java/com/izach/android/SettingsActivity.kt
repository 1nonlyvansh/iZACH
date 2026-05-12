package com.izach.android

import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.Bundle
import android.provider.Settings
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

            prefs.edit()
                .putBoolean("notif_system",    binding.swNotifSystem.isChecked)
                .putBoolean("notif_downloads", binding.swNotifDownloads.isChecked)
                .putBoolean("notif_transfers", binding.swNotifTransfers.isChecked)
                .putBoolean("notif_automation", binding.swNotifAutomation.isChecked)
                .putBoolean("notif_alerts",    binding.swNotifAlerts.isChecked)
                .putBoolean("biometric_lock",  binding.swBiometric.isChecked)
                .putBoolean("float_mic_enabled", binding.swFloatMic.isChecked)
                .apply()

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
    }

    private fun toast(msg: String) = Toast.makeText(this, msg, Toast.LENGTH_SHORT).show()
}
